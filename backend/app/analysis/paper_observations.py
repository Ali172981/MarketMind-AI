"""Prospective SMC event-observation recorder; never emits probabilities or orders.

Records only structure-break events confirmed on the latest closed candle. The
next candle's open is used as a hypothetical entry when it becomes available.
Observed OHLC bars advance the record until stop, target or timeout. This is
an observation study, not broker execution or a trading recommendation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.analysis.research import (
    FEATURE_NAMES,
    _causal_volatility_regimes,
    _feature_vector,
    _market_regime,
    _normalise_candles,
)
from app.analysis.smc import _atr, _pivot_points, _structure_events
from app.market_data.candle_store import db_connection, init_db

PAPER_SCHEMA_VERSION = "mm-paper-observations-1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_paper_db() -> None:
    init_db()
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                schema_version TEXT NOT NULL,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                event_time INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_close REAL NOT NULL,
                structure_level REAL NOT NULL,
                atr_at_signal REAL NOT NULL,
                stop_multiple REAL NOT NULL,
                reward_risk REAL NOT NULL,
                horizon_bars INTEGER NOT NULL,
                features_json TEXT NOT NULL,
                market_regime TEXT NOT NULL,
                volatility_regime TEXT NOT NULL,
                data_source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'WAITING_FOR_ENTRY',
                entry_time INTEGER,
                entry_price REAL,
                stop_price REAL,
                target_price REAL,
                exit_time INTEGER,
                exit_price REAL,
                outcome TEXT,
                outcome_label INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(symbol, interval, event_time, event_type, direction)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_obs_symbol_time ON paper_observations(symbol, interval, event_time DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_obs_status ON paper_observations(status, symbol, interval)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_recorder_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                status TEXT NOT NULL,
                pairs_total INTEGER NOT NULL,
                pairs_processed INTEGER NOT NULL,
                observations_created INTEGER NOT NULL,
                observations_advanced INTEGER NOT NULL,
                observations_settled INTEGER NOT NULL,
                errors_json TEXT NOT NULL,
                results_json TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_recorder_runs_started ON paper_recorder_runs(started_at DESC)")


def _public_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    if "features_json" in result:
        try:
            result["features"] = json.loads(result.pop("features_json"))
        except (TypeError, ValueError):
            result["features"] = {}
    return result


def record_latest_structure_observations(
    symbol: str,
    interval: str,
    raw_candles: list[dict[str, Any]],
    *,
    atr_period: int = 14,
    stop_multiple: float = 1.5,
    reward_risk: float = 2.0,
    horizon_bars: int = 48,
    data_source: str = "unknown",
) -> dict[str, Any]:
    """Idempotently record only SMC events that occurred on the latest closed bar."""
    candles = _normalise_candles(raw_candles)
    if len(candles) < max(80, atr_period + 20):
        return {
            "status": "INSUFFICIENT_DATA", "observations_created": 0,
            "latest_closed_candle_time": candles[-1]["time"] if candles else None,
            "message": "At least 80 closed candles are required to observe a confirmed structure event.",
        }

    latest_index = len(candles) - 1
    latest_time = int(candles[latest_index]["time"])
    highs, lows = _pivot_points(candles, 3, 3)
    events, _ = _structure_events(candles, highs, lows)
    latest_events = [event for event in events if int(event.get("time", -1)) == latest_time]
    atr_value = _atr(candles[: latest_index + 1], atr_period)
    if atr_value is None or atr_value <= 0:
        return {
            "status": "INSUFFICIENT_DATA", "observations_created": 0,
            "latest_closed_candle_time": latest_time,
            "message": "ATR is unavailable; no observation was recorded.",
        }

    volatility_regimes = _causal_volatility_regimes(candles, atr_period=atr_period)
    created = []
    created_ids: list[int] = []
    init_paper_db()
    now = _now()
    with db_connection() as conn:
        for event in latest_events:
            features = _feature_vector(candles, latest_index, event, atr_period)
            if features is None:
                continue
            event_type = str(event.get("type", "STRUCTURE_BREAK"))
            direction = "LONG" if event.get("direction") == "BULLISH" else "SHORT"
            cursor = conn.execute("""
                INSERT OR IGNORE INTO paper_observations (
                    schema_version, symbol, interval, event_time, event_type, direction,
                    signal_close, structure_level, atr_at_signal, stop_multiple, reward_risk,
                    horizon_bars, features_json, market_regime, volatility_regime,
                    data_source, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WAITING_FOR_ENTRY', ?, ?)
            """, (
                PAPER_SCHEMA_VERSION, symbol.upper(), interval, latest_time, event_type, direction,
                float(candles[-1]["close"]), float(event.get("level", candles[-1]["close"])),
                float(atr_value), float(stop_multiple), float(reward_risk), int(horizon_bars),
                json.dumps(dict(zip(FEATURE_NAMES, features)), separators=(",", ":")),
                _market_regime(candles, latest_index), volatility_regimes[latest_index],
                str(data_source)[:120], now, now,
            ))
            if cursor.rowcount:
                created.append({"event_time": latest_time, "event_type": event_type, "direction": direction})
                created_ids.append(int(cursor.lastrowid))

    # Freeze execution-cost assumptions at observation creation time. The
    # simulator is separate from the outcome labeler and never sends orders.
    if created_ids:
        from app.analysis.paper_execution import snapshot_execution_for_observation
        for observation_id in created_ids:
            snapshot_execution_for_observation(observation_id)

    return {
        "status": "OK",
        "latest_closed_candle_time": latest_time,
        "candidate_events_on_latest_candle": len(latest_events),
        "observations_created": len(created),
        "created": created,
        "message": "Only confirmed SMC structure events on the latest closed candle are recorded. No probabilities, trade recommendations or orders are generated.",
    }


def advance_open_observations(
    symbol: str,
    interval: str,
    raw_candles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Advance waiting/open observations using only newly available closed OHLC bars."""
    candles = _normalise_candles(raw_candles)
    if not candles:
        return {"advanced": 0, "settled": 0, "waiting_for_entry": 0}
    init_paper_db()
    time_to_index = {int(row["time"]): index for index, row in enumerate(candles)}
    advanced = settled = waiting = 0
    now = _now()
    with db_connection() as conn:
        pending = conn.execute(
            "SELECT * FROM paper_observations WHERE symbol=? AND interval=? AND status IN ('WAITING_FOR_ENTRY','OPEN') ORDER BY event_time",
            (symbol.upper(), interval),
        ).fetchall()
        for raw_record in pending:
            record = dict(raw_record)
            signal_index = time_to_index.get(int(record["event_time"]))
            if signal_index is None:
                if int(record["event_time"]) < int(candles[0]["time"]):
                    conn.execute(
                        "UPDATE paper_observations SET status='DATA_WINDOW_MISSING', updated_at=? WHERE id=?",
                        (now, record["id"]),
                    )
                    advanced += 1
                else:
                    waiting += 1
                continue
            entry_index = signal_index + 1
            if len(candles) <= entry_index:
                waiting += 1
                continue

            direction = 1 if record["direction"] == "LONG" else -1
            entry_price = float(candles[entry_index]["open"])
            stop_distance = float(record["atr_at_signal"]) * float(record["stop_multiple"])
            stop_price = entry_price - direction * stop_distance
            target_price = entry_price + direction * stop_distance * float(record["reward_risk"])
            if entry_price <= 0 or stop_price <= 0 or target_price <= 0:
                conn.execute(
                    "UPDATE paper_observations SET status='INVALID_ENTRY', updated_at=? WHERE id=?",
                    (now, record["id"]),
                )
                advanced += 1
                continue

            last_available = min(len(candles) - 1, entry_index + int(record["horizon_bars"]) - 1)
            outcome = None
            exit_index = None
            exit_price = None
            for candle_index in range(entry_index, last_available + 1):
                bar = candles[candle_index]
                if direction > 0:
                    stop_hit = float(bar["low"]) <= stop_price
                    target_hit = float(bar["high"]) >= target_price
                else:
                    stop_hit = float(bar["high"]) >= stop_price
                    target_hit = float(bar["low"]) <= target_price
                # Conservative OHLC assumption: stop wins when both thresholds hit in one bar.
                if stop_hit:
                    outcome, exit_index, exit_price = "STOP", candle_index, stop_price
                    break
                if target_hit:
                    outcome, exit_index, exit_price = "TARGET", candle_index, target_price
                    break

            horizon_complete = len(candles) - 1 >= entry_index + int(record["horizon_bars"]) - 1
            if outcome is None and horizon_complete:
                outcome = "TIMEOUT"
                exit_index = last_available
                exit_price = float(candles[last_available]["close"])

            if outcome is None:
                conn.execute("""
                    UPDATE paper_observations SET status='OPEN', entry_time=?, entry_price=?,
                        stop_price=?, target_price=?, updated_at=? WHERE id=?
                """, (
                    int(candles[entry_index]["time"]), entry_price, stop_price, target_price,
                    now, record["id"],
                ))
                waiting += 1
            else:
                conn.execute("""
                    UPDATE paper_observations SET status='SETTLED', entry_time=?, entry_price=?,
                        stop_price=?, target_price=?, exit_time=?, exit_price=?, outcome=?,
                        outcome_label=?, updated_at=? WHERE id=?
                """, (
                    int(candles[entry_index]["time"]), entry_price, stop_price, target_price,
                    int(candles[int(exit_index)]["time"]), float(exit_price), outcome,
                    1 if outcome == "TARGET" else 0, now, record["id"],
                ))
                settled += 1
            advanced += 1

    return {"advanced": advanced, "settled": settled, "waiting_or_open": waiting}


def list_observations(symbol: str | None = None, interval: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    init_paper_db()
    clauses, params = [], []
    if symbol:
        clauses.append("symbol=?")
        params.append(symbol.upper())
    if interval:
        clauses.append("interval=?")
        params.append(interval)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM paper_observations{where} ORDER BY event_time DESC, id DESC LIMIT ?",
            (*params, max(1, min(int(limit), 500))),
        ).fetchall()
    return [_public_row(row) for row in rows]


def observation_summary(symbol: str | None = None, interval: str | None = None) -> dict[str, Any]:
    init_paper_db()
    clauses, params = [], []
    if symbol:
        clauses.append("symbol=?")
        params.append(symbol.upper())
    if interval:
        clauses.append("interval=?")
        params.append(interval)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_connection() as conn:
        rows = conn.execute(
            f"SELECT status, outcome, COUNT(*) AS count FROM paper_observations{where} GROUP BY status, outcome",
            tuple(params),
        ).fetchall()
    by_status: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    total = 0
    for row in rows:
        count = int(row["count"])
        total += count
        by_status[str(row["status"])] = by_status.get(str(row["status"]), 0) + count
        if row["outcome"]:
            by_outcome[str(row["outcome"])] = by_outcome.get(str(row["outcome"]), 0) + count
    return {
        "schema_version": PAPER_SCHEMA_VERSION,
        "total_observations": total,
        "by_status": by_status,
        "settled_outcomes": by_outcome,
        "probabilities_recorded": False,
        "orders_submitted": False,
        "notice": "Prospective structural-event observation only. No probabilities, investment advice, broker orders or fills are recorded.",
    }



def save_recorder_run(run: dict[str, Any]) -> int:
    """Persist one scheduler/manual collection cycle for audit and health reporting."""
    init_paper_db()
    with db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO paper_recorder_runs (
                trigger, started_at, finished_at, status, pairs_total, pairs_processed,
                observations_created, observations_advanced, observations_settled,
                errors_json, results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(run.get("trigger", "UNKNOWN")), str(run["started_at"]), str(run["finished_at"]),
            str(run.get("status", "UNKNOWN")), int(run.get("pairs_total", 0)),
            int(run.get("pairs_processed", 0)), int(run.get("observations_created", 0)),
            int(run.get("observations_advanced", 0)), int(run.get("observations_settled", 0)),
            json.dumps(run.get("errors", []), separators=(",", ":")),
            json.dumps(run.get("results", []), separators=(",", ":")),
        ))
        return int(cursor.lastrowid)


def list_recorder_runs(limit: int = 20) -> list[dict[str, Any]]:
    init_paper_db()
    with db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM paper_recorder_runs ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        for source, target in (("errors_json", "errors"), ("results_json", "results")):
            try:
                item[target] = json.loads(item.pop(source))
            except (TypeError, ValueError):
                item[target] = []
        output.append(item)
    return output


def latest_recorder_run() -> dict[str, Any] | None:
    rows = list_recorder_runs(1)
    return rows[0] if rows else None
