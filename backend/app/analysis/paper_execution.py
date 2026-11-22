"""Cost-aware OHLC paper-execution scenarios for prospective SMC observations.

This is a deterministic research simulator, not a broker emulator. It applies
configurable spread, slippage and taker-fee assumptions to public closed OHLC
bars; it never connects to an exchange account or submits orders.
"""
from __future__ import annotations

import json
import math
import hashlib
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.market_data.candle_store import db_connection, init_db
from app.analysis.research import _normalise_candles

EXECUTION_SCHEMA_VERSION = "mm-paper-execution-1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def execution_assumptions() -> dict[str, Any]:
    """Return validated, explicit simulation assumptions (not venue quotes)."""
    fields = {
        "fee_bps_per_side": float(settings.paper_exec_fee_bps_per_side),
        "full_spread_bps": float(settings.paper_exec_full_spread_bps),
        "slippage_bps_per_side": float(settings.paper_exec_slippage_bps_per_side),
        "entry_delay_bars": int(settings.paper_exec_entry_delay_bars),
        "position_notional_quote": float(settings.paper_exec_position_notional_quote),
        "entry_rejection_rate_pct": float(settings.paper_exec_entry_rejection_rate_pct),
        "rejection_seed": str(settings.paper_exec_rejection_seed),
    }
    numeric_fields = [value for value in fields.values() if isinstance(value, (int, float)) and not isinstance(value, bool)]
    if not all(math.isfinite(float(value)) for value in numeric_fields):
        raise ValueError("Paper execution assumptions must be finite numbers.")
    if not 0 <= fields["fee_bps_per_side"] <= 500:
        raise ValueError("PAPER_EXEC_FEE_BPS_PER_SIDE must be between 0 and 500.")
    if not 0 <= fields["full_spread_bps"] <= 1000:
        raise ValueError("PAPER_EXEC_FULL_SPREAD_BPS must be between 0 and 1000.")
    if not 0 <= fields["slippage_bps_per_side"] <= 1000:
        raise ValueError("PAPER_EXEC_SLIPPAGE_BPS_PER_SIDE must be between 0 and 1000.")
    if not 0 <= fields["entry_delay_bars"] <= 100:
        raise ValueError("PAPER_EXEC_ENTRY_DELAY_BARS must be between 0 and 100.")
    if not 1 <= fields["position_notional_quote"] <= 100_000_000:
        raise ValueError("PAPER_EXEC_POSITION_NOTIONAL_QUOTE must be between 1 and 100,000,000.")
    if not 0 <= fields["entry_rejection_rate_pct"] <= 100:
        raise ValueError("PAPER_EXEC_ENTRY_REJECTION_RATE_PCT must be between 0 and 100.")
    if not fields["rejection_seed"].strip():
        raise ValueError("PAPER_EXEC_REJECTION_SEED must not be empty.")
    return {
        **fields,
        "target_fill_policy": "TOUCH_ASSUMED_FILLED_AT_TARGET",
        "stop_fill_policy": "GAP_AWARE_STOP_WITH_ADVERSE_SPREAD_AND_SLIPPAGE",
        "fee_policy": "TAKER_FEE_BOTH_SIDES",
        "entry_policy": "NEXT_ELIGIBLE_CANDLE_OPEN_AFTER_CONFIGURED_BAR_DELAY",
        "execution_scope": "DIRECTIONAL_SYNTHETIC_EXPOSURE",
        "entry_rejection_model": "DETERMINISTIC_HASH_STRESS_SCENARIO_NOT_EMPIRICAL",
        "model_version": EXECUTION_SCHEMA_VERSION,
    }


def init_execution_db() -> None:
    init_db()
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_execution_simulations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id INTEGER NOT NULL UNIQUE,
                schema_version TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'WAITING_FOR_ENTRY',
                assumption_source TEXT NOT NULL DEFAULT 'PROSPECTIVE_SNAPSHOT',
                assumptions_json TEXT NOT NULL,
                execution_scope TEXT NOT NULL,
                entry_reference_time INTEGER,
                entry_reference_price REAL,
                entry_fill_price REAL,
                stop_price REAL,
                target_price REAL,
                quantity REAL,
                exit_time INTEGER,
                exit_reference_price REAL,
                exit_fill_price REAL,
                exit_reason TEXT,
                gross_pnl_quote REAL,
                spread_cost_quote REAL,
                slippage_cost_quote REAL,
                fee_cost_quote REAL,
                total_cost_quote REAL,
                net_pnl_quote REAL,
                gross_return_pct REAL,
                net_return_pct REAL,
                realized_r REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_exec_status ON paper_execution_simulations(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_exec_observation ON paper_execution_simulations(observation_id)")


def snapshot_execution_for_observation(
    observation_id: int,
    *,
    assumption_source: str = "PROSPECTIVE_SNAPSHOT",
) -> None:
    """Freeze the current simulation assumptions against one observation."""
    init_execution_db()
    assumptions = execution_assumptions()
    now = _now()
    with db_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO paper_execution_simulations (
                observation_id, schema_version, status, assumption_source,
                assumptions_json, execution_scope, created_at, updated_at
            ) VALUES (?, ?, 'WAITING_FOR_ENTRY', ?, ?, ?, ?, ?)
        """, (
            int(observation_id), EXECUTION_SCHEMA_VERSION, assumption_source,
            json.dumps(assumptions, sort_keys=True, separators=(",", ":")),
            assumptions["execution_scope"], now, now,
        ))


def _fill_price(reference_price: float, side: int, assumptions: dict[str, Any]) -> float:
    half_spread_bps = float(assumptions["full_spread_bps"]) / 2.0
    slippage_bps = float(assumptions["slippage_bps_per_side"])
    adverse_bps = (half_spread_bps + slippage_bps) / 10_000.0
    return reference_price * (1.0 + int(side) * adverse_bps)


def _calculate_trade_result(
    *,
    direction: int,
    entry_reference: float,
    entry_fill: float,
    exit_reference: float,
    exit_fill: float,
    stop_price: float,
    assumptions: dict[str, Any],
) -> dict[str, float]:
    notional = float(assumptions["position_notional_quote"])
    quantity = notional / entry_reference
    gross = quantity * direction * (exit_reference - entry_reference)
    half_spread = float(assumptions["full_spread_bps"]) / 2.0 / 10_000.0
    slip = float(assumptions["slippage_bps_per_side"]) / 10_000.0
    spread_cost = quantity * (entry_reference + exit_reference) * half_spread
    slippage_cost = quantity * (entry_reference + exit_reference) * slip
    fee_rate = float(assumptions["fee_bps_per_side"]) / 10_000.0
    fee_cost = quantity * (entry_fill + exit_fill) * fee_rate
    total_cost = spread_cost + slippage_cost + fee_cost
    net = gross - total_cost
    risk_quote = quantity * abs(entry_reference - stop_price)
    return {
        "quantity": quantity,
        "gross_pnl_quote": gross,
        "spread_cost_quote": spread_cost,
        "slippage_cost_quote": slippage_cost,
        "fee_cost_quote": fee_cost,
        "total_cost_quote": total_cost,
        "net_pnl_quote": net,
        "gross_return_pct": gross / notional * 100.0,
        "net_return_pct": net / notional * 100.0,
        "realized_r": net / risk_quote if risk_quote > 0 else 0.0,
    }


def _entry_rejected(observation_id: int, assumptions: dict[str, Any]) -> bool:
    """Deterministic entry-rejection stress scenario; not an empirical estimate."""
    rate = float(assumptions.get("entry_rejection_rate_pct", 0.0))
    if rate <= 0:
        return False
    if rate >= 100:
        return True
    token = f"{assumptions.get('rejection_seed', 'marketmind-paper-v1')}|{observation_id}".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(token).digest()[:8], "big") / float(2**64)
    return value < rate / 100.0


def advance_paper_executions(
    symbol: str,
    interval: str,
    raw_candles: list[dict[str, Any]],
) -> dict[str, int]:
    """Simulate entries/exits from closed OHLC bars using frozen cost assumptions."""
    candles = _normalise_candles(raw_candles)
    init_execution_db()
    if not candles:
        return {"created": 0, "opened": 0, "settled": 0, "waiting": 0, "data_window_missing": 0}

    current_assumptions = execution_assumptions()
    created = opened = settled = waiting = missing = 0
    now = _now()
    times = {int(item["time"]): index for index, item in enumerate(candles)}
    with db_connection() as conn:
        # Legacy v0.10 observations predate execution snapshots. They are labelled
        # explicitly so reports do not imply contemporaneous assumptions.
        missing_snapshots = conn.execute("""
            SELECT p.id FROM paper_observations p
            LEFT JOIN paper_execution_simulations e ON e.observation_id=p.id
            WHERE p.symbol=? AND p.interval=? AND e.id IS NULL
        """, (symbol.upper(), interval)).fetchall()
        for row in missing_snapshots:
            conn.execute("""
                INSERT OR IGNORE INTO paper_execution_simulations (
                    observation_id, schema_version, status, assumption_source,
                    assumptions_json, execution_scope, created_at, updated_at
                ) VALUES (?, ?, 'WAITING_FOR_ENTRY', 'MIGRATED_DEFAULT', ?, ?, ?, ?)
            """, (
                int(row["id"]), EXECUTION_SCHEMA_VERSION,
                json.dumps(current_assumptions, sort_keys=True, separators=(",", ":")),
                current_assumptions["execution_scope"], now, now,
            ))
            created += 1

        pending = conn.execute("""
            SELECT p.id AS observation_id, p.symbol, p.interval, p.event_time,
                   p.direction, p.atr_at_signal, p.stop_multiple, p.reward_risk,
                   p.horizon_bars, p.data_source, e.id AS execution_id, e.status AS execution_status,
                   e.assumptions_json
            FROM paper_observations p
            JOIN paper_execution_simulations e ON e.observation_id=p.id
            WHERE p.symbol=? AND p.interval=?
              AND e.status IN ('WAITING_FOR_ENTRY','OPEN')
            ORDER BY p.event_time, p.id
        """, (symbol.upper(), interval)).fetchall()

        for raw in pending:
            record = dict(raw)
            if "binance" not in str(record.get("data_source", "")).lower():
                conn.execute("UPDATE paper_execution_simulations SET status='BLOCKED_NON_BINANCE', updated_at=? WHERE id=?", (now, record["execution_id"]))
                continue
            signal_index = times.get(int(record["event_time"]))
            if signal_index is None:
                if int(record["event_time"]) < int(candles[0]["time"]):
                    conn.execute("UPDATE paper_execution_simulations SET status='DATA_WINDOW_MISSING', updated_at=? WHERE id=?", (now, record["execution_id"]))
                    missing += 1
                else:
                    waiting += 1
                continue

            try:
                assumptions = json.loads(record["assumptions_json"])
            except (TypeError, ValueError) as exc:
                conn.execute("UPDATE paper_execution_simulations SET status='INVALID_ASSUMPTIONS', updated_at=? WHERE id=?", (now, record["execution_id"]))
                continue

            delay_bars = int(assumptions["entry_delay_bars"])
            entry_index = signal_index + 1 + delay_bars
            if len(candles) <= entry_index:
                waiting += 1
                continue

            if _entry_rejected(int(record["observation_id"]), assumptions):
                conn.execute("UPDATE paper_execution_simulations SET status='ENTRY_REJECTED', updated_at=? WHERE id=?", (now, record["execution_id"]))
                continue

            direction = 1 if record["direction"] == "LONG" else -1
            entry_reference = float(candles[entry_index]["open"])
            if not math.isfinite(entry_reference) or entry_reference <= 0:
                conn.execute("UPDATE paper_execution_simulations SET status='INVALID_ENTRY', updated_at=? WHERE id=?", (now, record["execution_id"]))
                continue
            stop_distance = float(record["atr_at_signal"]) * float(record["stop_multiple"])
            stop_price = entry_reference - direction * stop_distance
            target_price = entry_reference + direction * stop_distance * float(record["reward_risk"])
            if stop_price <= 0 or target_price <= 0 or not all(math.isfinite(v) for v in (stop_price, target_price)):
                conn.execute("UPDATE paper_execution_simulations SET status='INVALID_ENTRY', updated_at=? WHERE id=?", (now, record["execution_id"]))
                continue

            entry_fill = _fill_price(entry_reference, direction, assumptions)
            quantity = float(assumptions["position_notional_quote"]) / entry_reference
            last_available = min(len(candles) - 1, entry_index + int(record["horizon_bars"]) - 1)
            exit_reason: str | None = None
            exit_index: int | None = None
            exit_reference: float | None = None

            for candle_index in range(entry_index, last_available + 1):
                bar = candles[candle_index]
                bar_open, bar_high, bar_low = float(bar["open"]), float(bar["high"]), float(bar["low"])
                if direction > 0:
                    stop_hit = bar_low <= stop_price
                    target_hit = bar_high >= target_price
                else:
                    stop_hit = bar_high >= stop_price
                    target_hit = bar_low <= target_price

                # If both barriers occur in one OHLC bar, assume the stop happens first.
                if stop_hit:
                    exit_reason, exit_index = "STOP", candle_index
                    # A gap through a stop is filled at the worse opening price, not
                    # the stop trigger. Additional spread and slippage are then applied.
                    exit_reference = min(stop_price, bar_open) if direction > 0 else max(stop_price, bar_open)
                    break
                if target_hit:
                    exit_reason, exit_index = "TARGET", candle_index
                    # OHLC touch does not prove queue execution. We assume a fill at
                    # target with no price improvement, then charge adverse costs.
                    exit_reference = target_price
                    break

            horizon_bars = int(record["horizon_bars"])
            horizon_end_index = entry_index + horizon_bars - 1
            horizon_complete = len(candles) - 1 >= horizon_end_index
            if exit_reason is None and horizon_complete:
                exit_reason, exit_index = "TIMEOUT", horizon_end_index
                exit_reference = float(candles[horizon_end_index]["close"])

            common_values = (
                int(candles[entry_index]["time"]), entry_reference, entry_fill,
                stop_price, target_price, quantity,
            )
            if exit_reason is None:
                conn.execute("""
                    UPDATE paper_execution_simulations SET status='OPEN',
                        entry_reference_time=?, entry_reference_price=?, entry_fill_price=?,
                        stop_price=?, target_price=?, quantity=?, updated_at=? WHERE id=?
                """, (*common_values, now, record["execution_id"]))
                opened += 1
                continue

            if exit_reference is None or exit_reference <= 0 or not math.isfinite(exit_reference):
                conn.execute("UPDATE paper_execution_simulations SET status='INVALID_EXIT', updated_at=? WHERE id=?", (now, record["execution_id"]))
                continue
            exit_side = -direction
            exit_fill = _fill_price(exit_reference, exit_side, assumptions)
            results = _calculate_trade_result(
                direction=direction,
                entry_reference=entry_reference,
                entry_fill=entry_fill,
                exit_reference=exit_reference,
                exit_fill=exit_fill,
                stop_price=stop_price,
                assumptions=assumptions,
            )
            conn.execute("""
                UPDATE paper_execution_simulations SET status='SETTLED',
                    entry_reference_time=?, entry_reference_price=?, entry_fill_price=?,
                    stop_price=?, target_price=?, quantity=?, exit_time=?,
                    exit_reference_price=?, exit_fill_price=?, exit_reason=?,
                    gross_pnl_quote=?, spread_cost_quote=?, slippage_cost_quote=?,
                    fee_cost_quote=?, total_cost_quote=?, net_pnl_quote=?,
                    gross_return_pct=?, net_return_pct=?, realized_r=?, updated_at=?
                WHERE id=?
            """, (
                *common_values, int(candles[int(exit_index)]["time"]), exit_reference,
                exit_fill, exit_reason, results["gross_pnl_quote"],
                results["spread_cost_quote"], results["slippage_cost_quote"],
                results["fee_cost_quote"], results["total_cost_quote"],
                results["net_pnl_quote"], results["gross_return_pct"],
                results["net_return_pct"], results["realized_r"], now,
                record["execution_id"],
            ))
            settled += 1

    return {"created": created, "opened": opened, "settled": settled, "waiting": waiting, "data_window_missing": missing}


def _public_execution(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        item["assumptions"] = json.loads(item.pop("assumptions_json"))
    except (TypeError, ValueError):
        item["assumptions"] = {}
    return item


def list_execution_simulations(
    symbol: str | None = None,
    interval: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    init_execution_db()
    clauses: list[str] = []
    params: list[Any] = []
    if symbol:
        clauses.append("p.symbol=?")
        params.append(symbol.upper())
    if interval:
        clauses.append("p.interval=?")
        params.append(interval)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_connection() as conn:
        rows = conn.execute(f"""
            SELECT e.*, p.symbol, p.interval, p.event_time, p.event_type,
                   p.direction, p.data_source, p.outcome AS barrier_outcome
            FROM paper_execution_simulations e
            JOIN paper_observations p ON p.id=e.observation_id
            {where}
            ORDER BY p.event_time DESC, e.id DESC LIMIT ?
        """, (*params, max(1, min(int(limit), 500)))).fetchall()
    output = []
    for row in rows:
        item = _public_execution(row)
        item["position_notional_quote"] = float(item.get("assumptions", {}).get("position_notional_quote", 0.0))
        output.append(item)
    return output


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    if not count:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate_pct": None,
            "profit_factor": None, "gross_pnl_quote": 0.0, "total_cost_quote": 0.0,
            "net_pnl_quote": 0.0, "average_net_return_pct": None,
            "aggregate_net_return_pct": None, "average_realized_r": None,
            "sequential_trade_drawdown_quote": 0.0,
        }
    pnls = [float(row["net_pnl_quote"] or 0.0) for row in rows]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross = sum(float(row["gross_pnl_quote"] or 0.0) for row in rows)
    costs = sum(float(row["total_cost_quote"] or 0.0) for row in rows)
    net = sum(pnls)
    denominator = sum(float(row.get("position_notional_quote") or 0.0) for row in rows)
    # This is a chronological trade-sequence drawdown on equal independent trade
    # notionals, not an account-equity drawdown with overlapping exposure/netting.
    cumulative = peak = max_drawdown = 0.0
    for value in sorted(rows, key=lambda row: (int(row.get("exit_time") or 0), int(row.get("id") or 0))):
        cumulative += float(value.get("net_pnl_quote") or 0.0)
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": count - len(wins) - len(losses),
        "win_rate_pct": len(wins) / count * 100.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "gross_pnl_quote": gross,
        "spread_cost_quote": sum(float(row["spread_cost_quote"] or 0.0) for row in rows),
        "slippage_cost_quote": sum(float(row["slippage_cost_quote"] or 0.0) for row in rows),
        "fee_cost_quote": sum(float(row["fee_cost_quote"] or 0.0) for row in rows),
        "total_cost_quote": costs,
        "net_pnl_quote": net,
        "average_net_return_pct": sum(float(row["net_return_pct"] or 0.0) for row in rows) / count,
        "aggregate_net_return_pct": net / denominator * 100.0 if denominator > 0 else None,
        "average_realized_r": sum(float(row["realized_r"] or 0.0) for row in rows) / count,
        "sequential_trade_drawdown_quote": max_drawdown,
    }


def execution_summary(symbol: str | None = None, interval: str | None = None) -> dict[str, Any]:
    init_execution_db()
    clauses: list[str] = []
    params: list[Any] = []
    if symbol:
        clauses.append("p.symbol=?")
        params.append(symbol.upper())
    if interval:
        clauses.append("p.interval=?")
        params.append(interval)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_connection() as conn:
        rows = conn.execute(f"""
            SELECT e.*, p.symbol, p.interval, p.direction
            FROM paper_execution_simulations e
            JOIN paper_observations p ON p.id=e.observation_id
            {where}
            ORDER BY e.exit_time, e.id
        """, tuple(params)).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        try:
            assumptions = json.loads(item.get("assumptions_json") or "{}")
        except (TypeError, ValueError):
            assumptions = {}
        item["position_notional_quote"] = float(assumptions.get("position_notional_quote", 0.0))
    settled = [item for item in items if item["status"] == "SETTLED"]
    by_status: dict[str, int] = {}
    assumption_sources: dict[str, int] = {}
    for item in items:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
        source = str(item.get("assumption_source", "UNKNOWN"))
        assumption_sources[source] = assumption_sources.get(source, 0) + 1
    long_stats = _stats([item for item in settled if item["direction"] == "LONG"])
    short_stats = _stats([item for item in settled if item["direction"] == "SHORT"])
    current = execution_assumptions()
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "total_simulations": len(items),
        "by_status": by_status,
        "assumption_sources": assumption_sources,
        "overall": _stats(settled),
        "by_direction": {"LONG": long_stats, "SHORT": short_stats},
        "current_default_assumptions": current,
        "historical_assumptions_are_snapshotted_per_trade": True,
        "notice": (
            "Cost-aware OHLC simulation only. Configured spread/slippage are fixed assumptions, not observed bid/ask or order-book impact. "
            "A target touch is assumed filled at the target; OHLC cannot establish queue execution or partial fills. "
            "Short results are synthetic directional exposures: borrow, margin, liquidation and perpetual funding costs are not modelled. "
            "Sequential trade drawdown is not portfolio drawdown. No broker fills or orders are created."
        ),
        "probabilities_recorded": False,
        "orders_submitted": False,
    }
