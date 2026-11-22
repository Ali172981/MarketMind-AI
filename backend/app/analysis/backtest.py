"""Causal, rule-based SMC backtest utilities.

The engine uses confirmed structure events, enters at the next candle open, applies
ATR stops, fixed-R targets, conservative stop-first handling when stop and target
are both touched in one candle, trading costs, and a maximum holding period.
It is a research simulator, not an execution engine or a profitability guarantee.
"""
from __future__ import annotations

from typing import Any

from app.analysis.smc import _atr, _pivot_points, _structure_events


def _normalise_closed(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [dict(c) for c in candles if c.get("is_closed", True)]
    rows.sort(key=lambda c: c.get("time", 0))
    return rows


def _max_drawdown(equity_curve: list[dict[str, float]]) -> float:
    peak = equity_curve[0]["equity"] if equity_curve else 1.0
    worst = 0.0
    for point in equity_curve:
        peak = max(peak, point["equity"])
        if peak > 0:
            worst = min(worst, (point["equity"] / peak - 1.0) * 100.0)
    return worst


def run_smc_backtest(
    raw_candles: list[dict[str, Any]],
    *,
    pivot_left: int = 3,
    pivot_right: int = 3,
    atr_period: int = 14,
    atr_stop_multiple: float = 1.5,
    reward_risk: float = 2.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 2.0,
    risk_per_trade_pct: float = 1.0,
    max_holding_bars: int = 48,
    starting_equity: float = 10_000.0,
) -> dict[str, Any]:
    candles = _normalise_closed(raw_candles)
    minimum = max(60, pivot_left + pivot_right + atr_period + 10)
    if len(candles) < minimum:
        return {
            "status": "INSUFFICIENT_DATA", "candles_analyzed": len(candles),
            "minimum_required": minimum,
            "message": "More closed historical candles are required for a meaningful backtest.",
            "trades": [], "metrics": None,
        }

    highs, lows = _pivot_points(candles, pivot_left, pivot_right)
    events, _ = _structure_events(candles, highs, lows)
    index_by_time = {c.get("time"): i for i, c in enumerate(candles)}
    events_by_index: list[tuple[int, dict[str, Any]]] = []
    for event in events:
        idx = index_by_time.get(event.get("time"))
        if idx is not None:
            events_by_index.append((idx, event))
    events_by_index.sort(key=lambda item: item[0])

    equity = float(starting_equity)
    equity_curve = [{"trade": 0, "equity": equity}]
    trades: list[dict[str, Any]] = []
    busy_until = -1
    round_trip_cost_rate = (2.0 * (fee_bps + slippage_bps)) / 10_000.0

    for signal_idx, event in events_by_index:
        if signal_idx < busy_until:
            continue
        entry_idx = signal_idx + 1
        if entry_idx >= len(candles):
            continue
        direction = 1 if event.get("direction") == "BULLISH" else -1
        signal_close = float(candles[signal_idx]["close"])
        entry = float(candles[entry_idx]["open"])
        atr = _atr(candles[: signal_idx + 1], atr_period)
        if atr is None or atr <= 0:
            continue
        stop_distance = atr * atr_stop_multiple
        stop = entry - direction * stop_distance
        target = entry + direction * stop_distance * reward_risk
        if entry <= 0 or stop <= 0 or target <= 0:
            continue

        exit_idx = min(len(candles) - 1, entry_idx + max_holding_bars - 1)
        exit_price = float(candles[exit_idx]["close"])
        exit_reason = "MAX_HOLD"
        for j in range(entry_idx, exit_idx + 1):
            bar = candles[j]
            if direction == 1:
                stop_hit = float(bar["low"]) <= stop
                target_hit = float(bar["high"]) >= target
            else:
                stop_hit = float(bar["high"]) >= stop
                target_hit = float(bar["low"]) <= target
            # Conservative assumption: if both are touched within one OHLC bar,
            # assume the stop was hit first because intrabar ordering is unknown.
            if stop_hit:
                exit_idx, exit_price, exit_reason = j, stop, "STOP"
                break
            if target_hit:
                exit_idx, exit_price, exit_reason = j, target, "TARGET"
                break
            if j == len(candles) - 1:
                exit_idx, exit_price, exit_reason = j, float(bar["close"]), "END_OF_DATA"

        risk_fraction = risk_per_trade_pct / 100.0
        risk_amount = equity * risk_fraction
        # Keep simulated gross exposure at or below 1x equity (no leverage).
        quantity = min(risk_amount / stop_distance, equity / entry)
        effective_risk_amount = quantity * stop_distance
        gross_pnl = quantity * direction * (exit_price - entry)
        costs = quantity * (entry + exit_price) * (fee_bps + slippage_bps) / 10_000.0
        net_pnl = gross_pnl - costs
        net_r = net_pnl / effective_risk_amount if effective_risk_amount else 0.0
        equity_before = equity
        equity += net_pnl
        equity_curve.append({"trade": len(trades) + 1, "equity": round(equity, 8)})

        trades.append({
            "trade_number": len(trades) + 1,
            "direction": "LONG" if direction == 1 else "SHORT",
            "signal": event.get("type"),
            "signal_time": event.get("time"),
            "entry_time": candles[entry_idx].get("time"),
            "exit_time": candles[exit_idx].get("time"),
            "entry_price": round(entry, 10), "exit_price": round(exit_price, 10),
            "stop_price": round(stop, 10), "target_price": round(target, 10),
            "exit_reason": exit_reason,
            "quantity": round(quantity, 10), "gross_exposure": round(quantity * entry, 8),
            "effective_risk_pct": round((effective_risk_amount / equity_before * 100.0), 4) if equity_before else 0.0,
            "gross_pnl": round(gross_pnl, 8), "estimated_costs": round(costs, 8),
            "net_pnl": round(net_pnl, 8), "net_r_multiple": round(net_r, 4),
            "equity_before": round(equity_before, 8), "equity_after": round(equity, 8),
            "bars_held": exit_idx - entry_idx + 1,
        })
        busy_until = exit_idx + 1

    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] < 0]
    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    total_pnl = equity - starting_equity
    metrics = {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round((len(wins) / len(trades) * 100.0), 2) if trades else 0.0,
        "net_profit": round(total_pnl, 8),
        "net_return_pct": round((total_pnl / starting_equity * 100.0), 4) if starting_equity else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (None if not gross_profit else "INF"),
        "average_net_r": round(sum(t["net_r_multiple"] for t in trades) / len(trades), 4) if trades else 0.0,
        "max_drawdown_pct": round(_max_drawdown(equity_curve), 4),
        "starting_equity": round(starting_equity, 8),
        "ending_equity": round(equity, 8),
        "estimated_costs_total": round(sum(t["estimated_costs"] for t in trades), 8),
    }
    return {
        "status": "OK", "method": "Confirmed SMC structure-break strategy v1",
        "candles_analyzed": len(candles), "signals_found": len(events),
        "parameters": {
            "pivot_left": pivot_left, "pivot_right": pivot_right,
            "atr_period": atr_period, "atr_stop_multiple": atr_stop_multiple,
            "reward_risk": reward_risk, "fee_bps_per_side": fee_bps,
            "slippage_bps_per_side": slippage_bps,
            "risk_per_trade_pct": risk_per_trade_pct, "maximum_gross_exposure": "1x equity (no leverage)",
            "max_holding_bars": max_holding_bars,
            "same_bar_stop_and_target": "STOP_FIRST",
        },
        "metrics": metrics, "equity_curve": equity_curve, "trades": trades,
        "limitations": [
            "Signals are confirmed structure breaks from the deterministic SMC engine; this is not an optimised strategy.",
            "Entries occur at the next candle open; stops and targets use OHLC bars, not tick-level execution.",
            "If stop and target are both touched in one candle, the simulator assumes the stop occurred first.",
            "Fees and slippage are configurable estimates and may differ from actual venue costs.",
            "No funding, spread variation, market impact, borrow costs, taxes, or exchange outages are modelled.",
            "Gross exposure is capped at 1x simulated equity; short trades remain hypothetical research positions and do not model borrow availability.",
            "A single historical run does not establish future profitability; use out-of-sample and walk-forward testing.",
        ],
        "disclaimer": "Research simulation only. No orders are placed and no profitability is guaranteed.",
    }
