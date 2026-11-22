"""Scheduled, observation-only collector for the prospective SMC paper log.

The worker polls public closed-candle data, advances prior observations and
captures a structure event on the latest closed candle. It never creates a
probability, trading recommendation, broker fill or order.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from app.analysis.paper_execution import advance_paper_executions
from app.analysis.paper_observations import (
    advance_open_observations,
    record_latest_structure_observations,
    save_recorder_run,
)
from app.analysis.research import _normalise_candles
from app.core.config import settings
from app.market_data.candle_provider import INTERVALS, SYMBOLS, get_ohlcv

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = {
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}

_runtime: dict[str, Any] = {
    "state": "DISABLED",
    "started_at": None,
    "last_cycle_at": None,
    "last_error": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv_values(value: str, allowed: set[str], default: tuple[str, ...], *, uppercase: bool = False) -> tuple[list[str], list[str]]:
    raw_items = [part.strip() for part in value.split(",") if part.strip()] or list(default)
    normalised = [item.upper() if uppercase else item for item in raw_items]
    valid = list(dict.fromkeys(item for item in normalised if item in allowed))
    invalid = list(dict.fromkeys(item for item in normalised if item not in allowed))
    return valid, invalid


def recorder_config() -> dict[str, Any]:
    symbols, invalid_symbols = _csv_values(
        settings.paper_recorder_symbols, SYMBOLS, ("BTCUSDT", "ETHUSDT", "SOLUSDT"), uppercase=True,
    )
    intervals, invalid_intervals = _csv_values(
        settings.paper_recorder_intervals, INTERVALS, ("1h",),
    )
    configured = bool(settings.paper_recorder_enabled)
    mode_ok = settings.data_mode.lower() == "binance"
    config_ok = bool(symbols and intervals) and not invalid_symbols and not invalid_intervals
    blocked_reason = None
    if configured and not mode_ok:
        blocked_reason = "Set DATA_MODE=binance to enable real-market observation collection."
    elif configured and not config_ok:
        blocked_reason = "Correct unsupported PAPER_RECORDER_SYMBOLS or PAPER_RECORDER_INTERVALS values."
    return {
        "configured_enabled": configured,
        "enabled": configured and mode_ok and config_ok,
        "blocked_reason": blocked_reason,
        "invalid_symbols": invalid_symbols,
        "invalid_intervals": invalid_intervals,
        "data_mode": settings.data_mode,
        "symbols": symbols,
        "intervals": intervals,
        "poll_seconds": max(20, int(settings.paper_recorder_poll_seconds)),
        "candle_limit": max(100, min(int(settings.paper_recorder_candle_limit), 5000)),
        "max_closed_candle_age_seconds": 0,
        "probabilities_recorded": False,
        "orders_submitted": False,
    }


def runtime_status() -> dict[str, Any]:
    return dict(_runtime)


async def run_recorder_cycle(
    *,
    trigger: str = "SCHEDULED",
    symbols: list[str] | None = None,
    intervals: list[str] | None = None,
    limit: int | None = None,
    fetcher: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Run one sequential collection cycle and persist its audit record."""
    config = recorder_config()
    chosen_symbols = symbols or config["symbols"]
    chosen_intervals = intervals or config["intervals"]
    chosen_limit = limit or config["candle_limit"]
    fetch = fetcher or get_ohlcv
    started_at = _utc_now()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    metrics = {"pairs_processed": 0, "observations_created": 0, "observations_advanced": 0, "observations_settled": 0}

    for symbol in chosen_symbols:
        for interval in chosen_intervals:
            pair = {"symbol": symbol, "interval": interval}
            try:
                payload = await fetch(symbol, interval, chosen_limit)
                source = str(payload.get("source", "unknown"))
                if "binance" not in source.lower():
                    raise RuntimeError(f"Non-Binance data source rejected: {source}")
                candles = _normalise_candles(payload.get("items", []))
                if len(candles) < 80:
                    raise RuntimeError(f"Only {len(candles)} valid closed candles available; at least 80 are required.")

                duration = INTERVAL_SECONDS[interval]
                latest_open_time = int(candles[-1]["time"])
                # Binance candle `time` is the open timestamp. Treat a candle as
                # fresh only while its close is within two full interval lengths.
                age_since_close = max(0.0, time.time() - (latest_open_time + duration))
                stale_limit = max(duration * 2, config["poll_seconds"] * 3)
                if age_since_close > stale_limit:
                    raise RuntimeError(
                        f"Latest closed candle is stale by {int(age_since_close)}s "
                        f"(maximum accepted age {int(stale_limit)}s)."
                    )

                advancement = advance_open_observations(symbol, interval, candles)
                recording = record_latest_structure_observations(
                    symbol, interval, candles, data_source=source,
                )
                execution = advance_paper_executions(symbol, interval, candles)
                metrics["pairs_processed"] += 1
                metrics["observations_created"] += int(recording.get("observations_created", 0))
                metrics["observations_advanced"] += int(advancement.get("advanced", 0))
                metrics["observations_settled"] += int(advancement.get("settled", 0))
                results.append({
                    **pair,
                    "status": "OK",
                    "data_status": payload.get("data_status", "UNKNOWN"),
                    "source": source,
                    "closed_candles": len(candles),
                    "latest_closed_candle_time": latest_open_time,
                    "age_since_close_seconds": round(age_since_close, 1),
                    "recording": recording,
                    "advancement": advancement,
                    "execution": execution,
                })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = {**pair, "error": str(exc)[:240]}
                errors.append(error)
                results.append({**pair, "status": "ERROR", "error": error["error"]})
                logger.warning("Paper recorder failed for %s %s: %s", symbol, interval, exc)

    pairs_total = len(chosen_symbols) * len(chosen_intervals)
    if not errors:
        status = "OK"
    elif metrics["pairs_processed"]:
        status = "PARTIAL"
    else:
        status = "FAILED"
    finished_at = _utc_now()
    audit = {
        "trigger": trigger,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "pairs_total": pairs_total,
        **metrics,
        "errors": errors,
        "results": results,
    }
    run_id = save_recorder_run(audit)
    return {
        "run_id": run_id,
        **audit,
        "probabilities_recorded": False,
        "orders_submitted": False,
    }


async def run_paper_recorder() -> None:
    """Lifespan task. Runs one cycle immediately, then polls at configured cadence."""
    config = recorder_config()
    if not config["enabled"]:
        _runtime.update({"state": "DISABLED", "last_error": config["blocked_reason"]})
        return

    _runtime.update({"state": "STARTING", "started_at": _utc_now(), "last_error": None})
    logger.info(
        "Starting observation-only paper recorder: symbols=%s intervals=%s poll=%ss",
        ",".join(config["symbols"]), ",".join(config["intervals"]), config["poll_seconds"],
    )
    try:
        while True:
            _runtime["state"] = "RUNNING"
            try:
                result = await run_recorder_cycle(trigger="SCHEDULED")
                _runtime["last_cycle_at"] = result["finished_at"]
                _runtime["last_error"] = "; ".join(item["error"] for item in result["errors"][:3]) or None
                _runtime["state"] = "DEGRADED" if result["status"] != "OK" else "SLEEPING"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _runtime.update({"state": "DEGRADED", "last_error": str(exc)[:240]})
                logger.exception("Paper recorder cycle failed unexpectedly")
            await asyncio.sleep(config["poll_seconds"])
    except asyncio.CancelledError:
        _runtime["state"] = "STOPPED"
        logger.info("Paper recorder stopped")
        raise
