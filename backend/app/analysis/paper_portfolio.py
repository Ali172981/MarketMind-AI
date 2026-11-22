"""Portfolio-level capital, overlap and equity-curve simulation.

This module re-simulates already cost-adjusted paper executions at portfolio
level. It scales each trade's stored net return to a risk-sized allocation,
accounts for overlapping positions and enforces configurable exposure limits.
It is an OHLC research scenario, not margin/broker execution or live trading.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from typing import Any

from app.core.config import settings
from app.market_data.candle_store import db_connection
from app.analysis.paper_execution import init_execution_db

PORTFOLIO_SCHEMA_VERSION = "mm-paper-portfolio-1.0"


def portfolio_configuration() -> dict[str, Any]:
    config: dict[str, Any] = {
        "initial_capital_quote": float(settings.paper_portfolio_initial_capital_quote),
        "risk_per_trade_pct": float(settings.paper_portfolio_risk_per_trade_pct),
        "max_open_risk_pct": float(settings.paper_portfolio_max_open_risk_pct),
        "max_gross_exposure_pct": float(settings.paper_portfolio_max_gross_exposure_pct),
        "max_position_exposure_pct": float(settings.paper_portfolio_max_position_exposure_pct),
        "max_concurrent_positions": int(settings.paper_portfolio_max_concurrent_positions),
    }
    numeric = [v for v in config.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not all(math.isfinite(float(v)) for v in numeric):
        raise ValueError("Portfolio settings must be finite numbers.")
    if not 100 <= config["initial_capital_quote"] <= 1_000_000_000:
        raise ValueError("PAPER_PORTFOLIO_INITIAL_CAPITAL_QUOTE must be between 100 and 1,000,000,000.")
    if not 0.01 <= config["risk_per_trade_pct"] <= 10:
        raise ValueError("PAPER_PORTFOLIO_RISK_PER_TRADE_PCT must be between 0.01 and 10.")
    if not 0.01 <= config["max_open_risk_pct"] <= 100:
        raise ValueError("PAPER_PORTFOLIO_MAX_OPEN_RISK_PCT must be between 0.01 and 100.")
    if not 1 <= config["max_gross_exposure_pct"] <= 100:
        raise ValueError("PAPER_PORTFOLIO_MAX_GROSS_EXPOSURE_PCT must be between 1 and 100 (no leverage in this simulator).")
    if not 1 <= config["max_position_exposure_pct"] <= 100:
        raise ValueError("PAPER_PORTFOLIO_MAX_POSITION_EXPOSURE_PCT must be between 1 and 100.")
    if not 1 <= config["max_concurrent_positions"] <= 100:
        raise ValueError("PAPER_PORTFOLIO_MAX_CONCURRENT_POSITIONS must be between 1 and 100.")
    return config


def _trade_pnl(row: dict[str, Any], allocated_notional: float) -> float:
    return allocated_notional * float(row["net_return_pct"]) / 100.0


def simulate_portfolio(
    trades: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Run an event-time portfolio simulation over settled and currently open trades.

    New entries at a timestamp are evaluated before any exits at that same
    timestamp. That conservative ordering avoids reusing capital from an
    intrabar exit whose exact ordering cannot be inferred from OHLC data.
    Simultaneous candidates use a stable symbol/timeframe/id ordering.
    """
    initial_equity = float(config["initial_capital_quote"])
    equity = initial_equity
    peak_equity = initial_equity
    max_dd_quote = 0.0
    max_dd_pct = 0.0
    rejected: Counter[str] = Counter()
    excluded: Counter[str] = Counter()
    entries_by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    exits_by_time: dict[int, list[int]] = defaultdict(list)

    for raw in trades:
        row = dict(raw)
        status = str(row.get("status", "UNKNOWN"))
        if status not in {"SETTLED", "OPEN"}:
            excluded[status] += 1
            continue
        try:
            entry_time = int(row["entry_reference_time"])
            entry_price = float(row["entry_reference_price"])
            stop_price = float(row["stop_price"])
            if entry_price <= 0 or stop_price <= 0 or not all(math.isfinite(v) for v in (entry_price, stop_price)):
                raise ValueError
            stop_fraction = abs(entry_price - stop_price) / entry_price
            if stop_fraction <= 0 or not math.isfinite(stop_fraction):
                raise ValueError
            exit_time = int(row["exit_time"]) if status == "SETTLED" and row.get("exit_time") is not None else None
            if status == "SETTLED":
                net_return_pct = float(row["net_return_pct"])
                if exit_time is None or exit_time < entry_time or not math.isfinite(net_return_pct):
                    raise ValueError
                row["net_return_pct"] = net_return_pct
        except (KeyError, TypeError, ValueError, OverflowError):
            excluded["INVALID_OR_INCOMPLETE_EXECUTION"] += 1
            continue
        if "binance" not in str(row.get("data_source", "")).lower():
            excluded["NON_BINANCE_SOURCE"] += 1
            continue
        row["_entry_time"] = entry_time
        row["_exit_time"] = exit_time
        row["_stop_fraction"] = stop_fraction
        entries_by_time[entry_time].append(row)
        if exit_time is not None:
            exits_by_time[exit_time].append(int(row.get("id", id(row))))

    timeline = sorted(set(entries_by_time) | set(exits_by_time))
    active: dict[int, dict[str, Any]] = {}
    trade_results: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = [{
        "time": timeline[0] if timeline else None,
        "equity_quote": initial_equity,
        "realized_drawdown_quote": 0.0,
        "realized_drawdown_pct": 0.0,
        "event": "START",
    }]
    peak_concurrent = 0
    peak_exposure_pct = 0.0
    peak_open_risk_pct = 0.0

    def active_exposure() -> float:
        return sum(float(p["allocated_notional_quote"]) for p in active.values())

    def active_risk() -> float:
        return sum(float(p["allocated_risk_quote"]) for p in active.values())

    for timestamp in timeline:
        # Stable ordering makes repeated simulations exactly reproducible.
        candidates = sorted(
            entries_by_time.get(timestamp, []),
            key=lambda r: (str(r.get("symbol", "")), str(r.get("interval", "")), int(r.get("id", 0))),
        )
        proposals: list[tuple[dict[str, Any], float, float]] = []
        available_slots = max(0, int(config["max_concurrent_positions"]) - len(active))
        for row in candidates:
            if len(proposals) >= available_slots:
                rejected["MAX_CONCURRENT_POSITIONS"] += 1
                trade_results.append({
                    "id": row.get("id"), "symbol": row.get("symbol"), "interval": row.get("interval"),
                    "entry_time": timestamp, "status": "REJECTED", "rejection_reason": "MAX_CONCURRENT_POSITIONS",
                    "allocated_notional_quote": 0.0, "net_pnl_quote": None,
                })
                continue
            if equity <= 0:
                rejected["NON_POSITIVE_EQUITY"] += 1
                trade_results.append({
                    "id": row.get("id"), "symbol": row.get("symbol"), "interval": row.get("interval"),
                    "entry_time": timestamp, "status": "REJECTED", "rejection_reason": "NON_POSITIVE_EQUITY",
                    "allocated_notional_quote": 0.0, "net_pnl_quote": None,
                })
                continue
            target_risk = equity * float(config["risk_per_trade_pct"]) / 100.0
            risk_sized_notional = target_risk / float(row["_stop_fraction"])
            position_cap = equity * float(config["max_position_exposure_pct"]) / 100.0
            desired_notional = min(risk_sized_notional, position_cap)
            if desired_notional <= 0 or not math.isfinite(desired_notional):
                rejected["INVALID_POSITION_SIZE"] += 1
                continue
            proposals.append((row, desired_notional, float(row["_stop_fraction"])))

        # Simultaneous entry proposals share residual gross-exposure and open-risk
        # budgets pro rata, rather than granting the first row all available capacity.
        current_exposure = active_exposure()
        current_risk = active_risk()
        remaining_exposure = max(0.0, equity * float(config["max_gross_exposure_pct"]) / 100.0 - current_exposure)
        remaining_risk = max(0.0, equity * float(config["max_open_risk_pct"]) / 100.0 - current_risk)
        proposed_notional = sum(item[1] for item in proposals)
        proposed_risk = sum(item[1] * item[2] for item in proposals)
        factors = [1.0]
        if proposed_notional > 0:
            factors.append(remaining_exposure / proposed_notional)
        if proposed_risk > 0:
            factors.append(remaining_risk / proposed_risk)
        scale = max(0.0, min(factors))

        for row, desired_notional, stop_fraction in proposals:
            allocated = desired_notional * scale
            if allocated <= 1e-8 or not math.isfinite(allocated):
                reason = "NO_EXPOSURE_OR_RISK_CAPACITY"
                rejected[reason] += 1
                trade_results.append({
                    "id": row.get("id"), "symbol": row.get("symbol"), "interval": row.get("interval"),
                    "entry_time": timestamp, "status": "REJECTED", "rejection_reason": reason,
                    "allocated_notional_quote": 0.0, "net_pnl_quote": None,
                })
                continue
            trade_id = int(row.get("id", id(row)))
            allocated_risk = allocated * stop_fraction
            active[trade_id] = {
                "row": row,
                "allocated_notional_quote": allocated,
                "allocated_risk_quote": allocated_risk,
            }
            base_result = {
                "id": row.get("id"), "symbol": row.get("symbol"), "interval": row.get("interval"),
                "direction": row.get("direction"), "entry_time": timestamp, "exit_time": row.get("_exit_time"),
                "status": "OPEN" if row.get("_exit_time") is None else "ACCEPTED",
                "allocated_notional_quote": allocated,
                "allocated_risk_quote": allocated_risk,
                "net_pnl_quote": None,
                "net_return_pct": None,
                "rejection_reason": None,
                "entry_reference_price": float(row["entry_reference_price"]),
                "entry_fill_price": float(row.get("entry_fill_price") or row["entry_reference_price"]),
                "stop_price": float(row["stop_price"]),
                "target_price": float(row.get("target_price") or 0.0),
                "assumptions": row.get("assumptions") or {},
            }
            trade_results.append(base_result)

        gross = active_exposure()
        open_risk = active_risk()
        peak_concurrent = max(peak_concurrent, len(active))
        if equity > 0:
            peak_exposure_pct = max(peak_exposure_pct, gross / equity * 100.0)
            peak_open_risk_pct = max(peak_open_risk_pct, open_risk / equity * 100.0)

        # Exit events are applied after same-timestamp entries (conservative OHLC ordering).
        pnl_this_timestamp = 0.0
        closing_ids = [trade_id for trade_id, position in active.items() if position["row"].get("_exit_time") == timestamp]
        for trade_id in closing_ids:
            position = active.pop(trade_id)
            row = position["row"]
            pnl = _trade_pnl(row, float(position["allocated_notional_quote"]))
            pnl_this_timestamp += pnl
            for result in reversed(trade_results):
                if result.get("id") == row.get("id") and result.get("entry_time") == timestamp and result.get("status") == "ACCEPTED":
                    result["net_pnl_quote"] = pnl
                    result["net_return_pct"] = pnl / float(position["allocated_notional_quote"]) * 100.0
                    result["status"] = "SETTLED"
                    break
                if result.get("id") == row.get("id") and result.get("status") == "ACCEPTED":
                    result["net_pnl_quote"] = pnl
                    result["net_return_pct"] = pnl / float(position["allocated_notional_quote"]) * 100.0
                    result["status"] = "SETTLED"
                    break
        if pnl_this_timestamp:
            equity += pnl_this_timestamp
            peak_equity = max(peak_equity, equity)
            dd_quote = max(0.0, peak_equity - equity)
            dd_pct = dd_quote / peak_equity * 100.0 if peak_equity > 0 else 0.0
            max_dd_quote = max(max_dd_quote, dd_quote)
            max_dd_pct = max(max_dd_pct, dd_pct)
        # Record every event timestamp so the curve also shows unchanged equity
        # while an exposure is open, but its drawdown is realized-only, not mark-to-market.
        equity_curve.append({
            "time": timestamp,
            "equity_quote": equity,
            "realized_drawdown_quote": max(0.0, peak_equity - equity),
            "realized_drawdown_pct": max(0.0, peak_equity - equity) / peak_equity * 100.0 if peak_equity > 0 else 0.0,
            "event": "ENTRY_AND_OR_EXIT",
        })

    # Current open positions remain reserved against exposure/risk and are not included
    # in realized P&L or the realized equity curve.
    accepted_closed_final = [r for r in trade_results if r["status"] == "SETTLED"]
    accepted_open_final = [r for r in trade_results if r["status"] == "OPEN"]
    closed_pnls = [float(r["net_pnl_quote"] or 0.0) for r in accepted_closed_final]
    wins = [p for p in closed_pnls if p > 0]
    losses = [p for p in closed_pnls if p < 0]
    end_exposure = active_exposure()
    end_risk = active_risk()
    net_pnl = equity - initial_equity
    return {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "configuration": config,
        "input_settled_or_open_trades": len([r for r in trades if r.get("status") in {"SETTLED", "OPEN"}]),
        "accepted_settled_trades": len(accepted_closed_final),
        "accepted_open_positions": len(accepted_open_final),
        "rejected_trades": sum(rejected.values()),
        "rejected_by_reason": dict(rejected),
        "excluded_by_status_or_data": dict(excluded),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(closed_pnls) * 100.0 if closed_pnls else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "initial_capital_quote": initial_equity,
        "ending_realized_equity_quote": equity,
        "net_realized_pnl_quote": net_pnl,
        "net_return_on_initial_capital_pct": net_pnl / initial_equity * 100.0,
        "max_realized_drawdown_quote": max_dd_quote,
        "max_realized_drawdown_pct": max_dd_pct,
        "peak_concurrent_positions": peak_concurrent,
        "peak_gross_exposure_pct_of_equity": peak_exposure_pct,
        "peak_open_stop_risk_pct_of_equity": peak_open_risk_pct,
        "current_open_positions": len(active),
        "current_gross_exposure_quote": end_exposure,
        "current_gross_exposure_pct_of_equity": end_exposure / equity * 100.0 if equity > 0 else None,
        "current_open_stop_risk_quote": end_risk,
        "current_open_stop_risk_pct_of_equity": end_risk / equity * 100.0 if equity > 0 else None,
        "equity_curve": equity_curve[-500:],
        "trades": trade_results[-500:],
        "methodology": {
            "position_sizing": "Target risk-sized from current realized equity and entry-to-stop distance; position/exposure/risk caps can reduce actual allocated risk below the target.",
            "overlap_policy": "Entries at a timestamp are admitted before exits at that timestamp; overlapping positions consume concurrent, gross-exposure and open-risk capacity.",
            "simultaneous_allocation": "Simultaneous entries share remaining gross-exposure and open-risk capacity pro rata; max-position slots use stable symbol/timeframe/id ordering.",
            "pnl_scaling": "Stored per-trade net return from the cost-aware OHLC simulator is scaled linearly to the portfolio allocation.",
            "drawdown": "Realized-equity drawdown only. Unrealized mark-to-market drawdown and intrabar equity peaks are not available from this execution ledger.",
        },
        "notice": (
            "Portfolio-level OHLC research scenario, not a broker/account simulator. Risk sizing and overlap limits are hypothetical. "
            "The equity curve includes realized P&L only and excludes unrealized mark-to-market changes. Margin, liquidation, funding, borrow, "
            "correlation netting, partial fills, observed order-book depth and actual venue execution are not modelled. "
            "No probabilities, trade recommendations or orders are generated."
        ),
        "probabilities_recorded": False,
        "orders_submitted": False,
        "live_trading_eligible": False,
    }


def _load_execution_rows(symbol: str | None, interval: str | None) -> list[dict[str, Any]]:
    init_execution_db()
    clauses = ["e.status IN ('SETTLED','OPEN')"]
    params: list[Any] = []
    if symbol:
        clauses.append("p.symbol=?")
        params.append(symbol.upper())
    if interval:
        clauses.append("p.interval=?")
        params.append(interval)
    with db_connection() as conn:
        rows = conn.execute(f"""
            SELECT e.*, p.symbol, p.interval, p.event_time, p.event_type, p.direction,
                   p.data_source, p.market_regime, p.volatility_regime
            FROM paper_execution_simulations e
            JOIN paper_observations p ON p.id=e.observation_id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.entry_reference_time, p.symbol, p.interval, e.id
        """, tuple(params)).fetchall()
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        try:
            assumptions = json.loads(row.pop("assumptions_json") or "{}")
        except (TypeError, ValueError):
            assumptions = {}
        row["assumptions"] = assumptions
        output.append(row)
    return output


def portfolio_summary(symbol: str | None = None, interval: str | None = None) -> dict[str, Any]:
    rows = _load_execution_rows(symbol, interval)
    config = portfolio_configuration()
    result = simulate_portfolio(rows, config)
    result["filters"] = {"symbol": symbol.upper() if symbol else None, "interval": interval}
    result["source_execution_rows"] = len(rows)
    result["assumption_sources"] = dict(Counter(str(r.get("assumption_source", "UNKNOWN")) for r in rows))
    from app.analysis.portfolio_risk import portfolio_risk_snapshot
    open_positions = [trade for trade in result.get("trades", []) if trade.get("status") == "OPEN"]
    risk = portfolio_risk_snapshot(open_positions)
    result["mark_to_market"] = risk
    if risk["status"] == "COMPLETE":
        result["estimated_marked_equity_quote"] = result["ending_realized_equity_quote"] + risk["estimated_net_unrealized_pnl_quote"]
        result["estimated_marked_return_on_initial_capital_pct"] = (result["estimated_marked_equity_quote"] / result["initial_capital_quote"] - 1.0) * 100.0
    else:
        result["estimated_marked_equity_quote"] = None
        result["estimated_marked_return_on_initial_capital_pct"] = None
    return result
