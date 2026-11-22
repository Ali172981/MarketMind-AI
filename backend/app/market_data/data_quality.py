"""Cross-provider quote validation and bounded market-observation storage.

Comparisons are diagnostic only. They do not assert that two venues are
executable equivalents, and they never merge provider price histories.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from app.market_data import candle_store

_last_persisted: dict[tuple[str, str], float] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def init_quality_db() -> None:
    with candle_store.db_connection() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS market_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            symbol TEXT NOT NULL,
            observation_type TEXT NOT NULL,
            provider_timestamp TEXT,
            received_at TEXT NOT NULL,
            price REAL,
            payload_json TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_market_observations_lookup ON market_observations(symbol, observation_type, received_at DESC)")
        conn.execute("""CREATE TABLE IF NOT EXISTS provider_comparisons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            primary_provider TEXT NOT NULL,
            reference_provider TEXT NOT NULL,
            primary_price REAL NOT NULL,
            reference_price REAL NOT NULL,
            deviation_bps REAL NOT NULL,
            primary_age_seconds REAL,
            reference_age_seconds REAL,
            source_timestamp_skew_seconds REAL,
            status TEXT NOT NULL,
            observed_at TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_provider_comparisons_lookup ON provider_comparisons(symbol, observed_at DESC)")


def record_observation(provider: str, item: dict[str, Any], observation_type: str = "trade", min_interval: float = 1.0) -> bool:
    """Persist a sampled observation; returns False when rate-throttled."""
    symbol = str(item.get("symbol", "")).upper()
    price = item.get("price")
    if not symbol or price is None or float(price) <= 0:
        return False
    now = time.monotonic()
    key = (provider, symbol + ":" + observation_type)
    if now - _last_persisted.get(key, 0.0) < max(0.0, min_interval):
        return False
    _last_persisted[key] = now
    init_quality_db()
    received_at = str(item.get("received_at") or _utc_now())
    with candle_store.db_connection() as conn:
        conn.execute(
            "INSERT INTO market_observations(provider,symbol,observation_type,provider_timestamp,received_at,price,payload_json) VALUES(?,?,?,?,?,?,?)",
            (provider, symbol, observation_type, item.get("timestamp"), received_at, float(price), json.dumps(item, separators=(",", ":"), default=str)),
        )
    return True


def record_comparison(row: dict[str, Any]) -> None:
    init_quality_db()
    with candle_store.db_connection() as conn:
        conn.execute("""INSERT INTO provider_comparisons(
            symbol,primary_provider,reference_provider,primary_price,reference_price,
            deviation_bps,primary_age_seconds,reference_age_seconds,
            source_timestamp_skew_seconds,status,observed_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
            row["symbol"], row["primary_provider"], row["reference_provider"],
            row["primary_price"], row["reference_price"], row["deviation_bps"],
            row.get("primary_age_seconds"), row.get("reference_age_seconds"),
            row.get("source_timestamp_skew_seconds"), row["status"], row["observed_at"],
        ))


def compare_quotes(primary: dict[str, Any] | None, reference: dict[str, Any] | None,
                   symbol: str, primary_provider: str, reference_provider: str,
                   max_age_seconds: float = 90.0) -> dict[str, Any]:
    now = time.time()
    p = float(primary.get("price", 0)) if primary else 0.0
    r = float(reference.get("price", 0)) if reference else 0.0
    p_received = _parse_time(primary.get("received_at") or primary.get("timestamp")) if primary else None
    r_received = _parse_time(reference.get("received_at") or reference.get("timestamp")) if reference else None
    p_age = max(0.0, now - p_received) if p_received is not None else None
    r_age = max(0.0, now - r_received) if r_received is not None else None
    p_source_ts = _parse_time(primary.get("timestamp")) if primary else None
    r_source_ts = _parse_time(reference.get("timestamp")) if reference else None
    skew = abs(p_source_ts - r_source_ts) if p_source_ts is not None and r_source_ts is not None else None
    if p <= 0 or r <= 0:
        status, deviation = "INSUFFICIENT_DATA", None
    elif p_age is None or r_age is None or p_age > max_age_seconds or r_age > max_age_seconds:
        status, deviation = "STALE", abs(p-r) / ((p+r)/2) * 10000
    else:
        deviation = abs(p-r) / ((p+r)/2) * 10000
        # Gold/silver sources are indicative and can differ by venue/basis; use wider bands.
        warning_bps = 100.0 if symbol in {"XAUUSD", "XAGUSD"} else 25.0
        outlier_bps = 250.0 if symbol in {"XAUUSD", "XAGUSD"} else 75.0
        if deviation >= outlier_bps:
            status = "OUTLIER"
        elif deviation >= warning_bps or (skew is not None and skew > 120):
            status = "WARNING"
        else:
            status = "WITHIN_BAND"
    return {
        "symbol": symbol, "primary_provider": primary_provider,
        "reference_provider": reference_provider,
        "primary_price": p or None, "reference_price": r or None,
        "deviation_bps": round(deviation, 4) if deviation is not None else None,
        "primary_age_seconds": round(p_age, 3) if p_age is not None else None,
        "reference_age_seconds": round(r_age, 3) if r_age is not None else None,
        "source_timestamp_skew_seconds": round(skew, 3) if skew is not None else None,
        "status": status, "observed_at": _utc_now(),
        "interpretation": "Diagnostic comparison only; provider instruments, venues, timestamps and executable conditions may differ.",
    }


def recent_comparisons(limit: int = 100) -> list[dict[str, Any]]:
    init_quality_db()
    with candle_store.db_connection() as conn:
        rows = conn.execute("SELECT * FROM provider_comparisons ORDER BY id DESC LIMIT ?", (min(max(int(limit), 1), 500),)).fetchall()
    return [dict(row) for row in rows]


def recent_observations(symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    init_quality_db()
    query = "SELECT id,provider,symbol,observation_type,provider_timestamp,received_at,price FROM market_observations"
    args: list[Any] = []
    if symbol:
        query += " WHERE symbol=?"
        args.append(symbol.upper())
    query += " ORDER BY id DESC LIMIT ?"
    args.append(min(max(int(limit), 1), 500))
    with candle_store.db_connection() as conn:
        rows = conn.execute(query, args).fetchall()
    return [dict(row) for row in rows]


def quality_summary(limit: int = 100) -> dict[str, Any]:
    rows = recent_comparisons(limit)
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest.setdefault(row["symbol"], row)
    counts = {name: sum(1 for row in rows if row["status"] == name) for name in ("WITHIN_BAND", "WARNING", "OUTLIER", "STALE", "INSUFFICIENT_DATA")}
    return {
        "status": "NO_COMPARISONS" if not rows else ("ATTENTION_REQUIRED" if counts["OUTLIER"] or counts["STALE"] else "MONITORING"),
        "comparisons_in_window": len(rows), "status_counts": counts,
        "latest_by_symbol": latest,
        "thresholds": {"crypto_warning_bps": 25, "crypto_outlier_bps": 75, "metals_warning_bps": 100, "metals_outlier_bps": 250},
        "notice": "Cross-provider differences are diagnostic, not proof of a bad feed. Crypto spot and indicative metals prices may represent different venues, liquidity, timestamps or instrument conventions.",
    }


def prune_observations(retention_days: int = 14) -> dict[str, int]:
    init_quality_db()
    days = min(max(int(retention_days), 1), 365)
    with candle_store.db_connection() as conn:
        a = conn.execute("DELETE FROM market_observations WHERE julianday(received_at) < julianday('now', ?)", (f"-{days} days",)).rowcount
        b = conn.execute("DELETE FROM provider_comparisons WHERE julianday(observed_at) < julianday('now', ?)", (f"-{days} days",)).rowcount
    return {"observations_deleted": a, "comparisons_deleted": b, "retention_days": days}


async def run_data_quality_monitor() -> None:
    """Compare AllTick observations with independent public reference feeds."""
    import asyncio
    import logging

    from app.core.config import settings
    from app.market_data.alltick_provider import get_quotes as alltick_rest_quotes
    from app.market_data.alltick_websocket import get_quotes as alltick_ws_quotes, get_orderbooks, get_status as ws_status
    from app.market_data.binance_provider import get_live_quotes
    from app.market_data.xaus_provider import get_metals_quotes

    logger = logging.getLogger(__name__)
    init_quality_db()
    last_prune = 0.0
    while True:
        try:
            if settings.alltick_ws_enabled:
                primary_items = alltick_ws_quotes()
                if settings.alltick_ws_subscription.strip().lower() == "depth":
                    primary_items = []
                    for book in get_orderbooks():
                        if book.get("price"):
                            primary_items.append({
                                "symbol": book["symbol"], "price": book["price"],
                                "timestamp": book.get("timestamp"), "received_at": book.get("received_at"),
                                "source": "AllTick WebSocket order-book midpoint", "data_status": book.get("data_status"),
                            })
            else:
                primary_items = alltick_rest_quotes()
            primary = {str(q.get("symbol")): q for q in primary_items}
            references = {str(q.get("symbol")): q for q in (get_live_quotes() + get_metals_quotes())}
            for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "XAGUSD"):
                p = primary.get(symbol)
                r = references.get(symbol)
                reference_name = "Binance Spot WebSocket" if symbol.endswith("USDT") else "XAUS public indicative spot"
                result = compare_quotes(
                    p, r, symbol, "AllTick", reference_name,
                    max_age_seconds=max(15, settings.data_quality_max_quote_age_seconds),
                )
                record_comparison(result)
            if time.monotonic() - last_prune > 3600:
                prune_observations(settings.tick_storage_retention_days)
                last_prune = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Cross-provider data-quality monitor error: %s", str(exc)[:200])
        await asyncio.sleep(max(10, settings.data_quality_poll_seconds))
