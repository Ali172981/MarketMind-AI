"""Mark-to-market, cross-asset dependence and deterministic stress analytics.

All marks and return histories are derived from closed Binance Spot candles in
MarketMind's local cache. Outputs are research diagnostics, not account equity.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean, stdev
from typing import Any

from app.market_data.candle_provider import INTERVALS, SYMBOLS
from app.market_data.candle_store import get_candles

_INTERVAL_SECONDS = {
    "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
    "4h": 14400, "1d": 86400,
}


def _closed_binance(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for candle in candles:
        try:
            close = float(candle["close"])
            stamp = int(candle["time"])
            source = str(candle.get("source", ""))
            if close > 0 and math.isfinite(close) and candle.get("is_closed") and "binance" in source.lower():
                result.append({**candle, "time": stamp, "close": close})
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return sorted(result, key=lambda item: item["time"])


def correlation_matrix(series_by_symbol: dict[str, dict[int, float]], min_observations: int = 30) -> dict[str, Any]:
    """Pearson correlation of synchronized close-to-close simple returns."""
    symbols = sorted(series_by_symbol)
    returns: dict[str, dict[int, float]] = {}
    for symbol in symbols:
        points = sorted(series_by_symbol[symbol].items())
        returns[symbol] = {
            points[i][0]: points[i][1] / points[i - 1][1] - 1.0
            for i in range(1, len(points))
            if points[i - 1][1] > 0 and points[i][1] > 0
        }
    matrix: dict[str, dict[str, float | None]] = {s: {} for s in symbols}
    pair_counts: dict[str, dict[str, int]] = {s: {} for s in symbols}
    for left in symbols:
        for right in symbols:
            common = sorted(set(returns[left]) & set(returns[right]))
            pair_counts[left][right] = len(common)
            if left == right:
                matrix[left][right] = 1.0 if len(common) >= min_observations else None
                continue
            if len(common) < min_observations:
                matrix[left][right] = None
                continue
            xs = [returns[left][t] for t in common]
            ys = [returns[right][t] for t in common]
            sx, sy = stdev(xs), stdev(ys)
            if sx <= 0 or sy <= 0:
                matrix[left][right] = None
            else:
                mx, my = mean(xs), mean(ys)
                covariance = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (len(xs) - 1)
                matrix[left][right] = max(-1.0, min(1.0, covariance / (sx * sy)))
    return {"symbols": symbols, "correlation": matrix, "paired_return_observations": pair_counts,
            "minimum_observations": min_observations, "method": "Pearson correlation of synchronized closed-candle simple returns"}


def _position_mark(position: dict[str, Any], candle: dict[str, Any] | None, now_ts: int) -> dict[str, Any]:
    symbol, interval = str(position.get("symbol")), str(position.get("interval"))
    base = {"execution_id": position.get("id"), "symbol": symbol, "interval": interval,
            "direction": position.get("direction"), "allocated_notional_quote": position.get("allocated_notional_quote")}
    if candle is None:
        return {**base, "mark_status": "MISSING_MARK", "mark_price": None, "unrealized_pnl_quote": None}
    if int(candle["time"]) > now_ts:
        return {**base, "mark_status": "MISSING_MARK", "mark_price": None,
                "unrealized_pnl_quote": None, "mark_error": "FUTURE_CANDLE_TIMESTAMP"}
    age = max(0, now_ts - int(candle["time"]) - _INTERVAL_SECONDS.get(interval, 3600))
    stale_after = max(2 * _INTERVAL_SECONDS.get(interval, 3600), 1800)
    stale = age > stale_after
    mark = float(candle["close"])
    entry_ref = float(position["entry_reference_price"])
    entry_fill = float(position.get("entry_fill_price") or entry_ref)
    allocation = float(position["allocated_notional_quote"])
    direction = 1 if str(position.get("direction", "LONG")).upper() == "LONG" else -1
    quantity = allocation / entry_ref
    assumptions = position.get("assumptions") or {}
    half_spread = float(assumptions.get("full_spread_bps", 0.0)) / 2.0 / 10000.0
    slip = float(assumptions.get("slippage_bps_per_side", 0.0)) / 10000.0
    fee = float(assumptions.get("fee_bps_per_side", 0.0)) / 10000.0
    exit_fill = mark * (1.0 - direction * (half_spread + slip))
    gross_from_fills = quantity * direction * (exit_fill - entry_fill)
    estimated_fees = quantity * (entry_fill + exit_fill) * fee
    net_unrealized = gross_from_fills - estimated_fees
    stop = float(position["stop_price"])
    remaining_stop_risk = max(0.0, quantity * direction * (entry_fill - stop))
    return {
        **base, "mark_status": "STALE_MARK" if stale else "MARKED",
        "mark_price": mark, "mark_time": int(candle["time"]), "mark_age_seconds": age,
        "stale": stale, "allocated_quantity": quantity,
        "gross_unrealized_pnl_quote": quantity * direction * (mark - entry_ref),
        "estimated_exit_fill_price": exit_fill,
        "estimated_unrealized_pnl_quote": net_unrealized,
        "estimated_exit_fee_and_costs_included": True,
        "remaining_stop_risk_quote": remaining_stop_risk,
    }


def portfolio_risk_snapshot(open_positions: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    candle_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    marks = []
    for position in open_positions:
        symbol, interval = str(position.get("symbol", "")), str(position.get("interval", ""))
        key = (symbol, interval)
        if key not in candle_cache:
            if symbol in SYMBOLS and interval in INTERVALS:
                candle_cache[key] = _closed_binance(get_candles(symbol, interval, 1000))
            else:
                candle_cache[key] = []
        marks.append(_position_mark(position, candle_cache[key][-1] if candle_cache[key] else None, now_ts))

    missing = [m for m in marks if m["mark_status"] == "MISSING_MARK"]
    stale = [m for m in marks if m["mark_status"] == "STALE_MARK"]
    complete = not missing and not stale
    unrealized = sum(float(m.get("estimated_unrealized_pnl_quote") or 0.0) for m in marks if m.get("estimated_unrealized_pnl_quote") is not None)
    gross_unrealized = sum(float(m.get("gross_unrealized_pnl_quote") or 0.0) for m in marks if m.get("gross_unrealized_pnl_quote") is not None)

    correlation_groups: dict[str, Any] = {}
    intervals = sorted({str(p.get("interval")) for p in open_positions if str(p.get("interval")) in INTERVALS}) or ["1h"]
    for interval in intervals:
        # Correlation is a market-risk diagnostic for the tracked universe, not
        # merely a matrix of whichever symbols happen to have open positions.
        symbols = sorted(SYMBOLS)
        if len(symbols) < 2:
            continue
        series: dict[str, dict[int, float]] = {}
        vol: dict[str, Any] = {}
        for symbol in symbols:
            candles = _closed_binance(get_candles(symbol, interval, 1000))
            series[symbol] = {int(c["time"]): float(c["close"]) for c in candles}
            closes = [float(c["close"]) for c in candles]
            rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0]
            vol[symbol] = {
                "return_observations": len(rets),
                "realized_volatility_per_bar_pct": stdev(rets) * 100.0 if len(rets) >= 2 else None,
                "annualized_realized_volatility_pct": stdev(rets) * math.sqrt(365 * 86400 / _INTERVAL_SECONDS[interval]) * 100.0 if len(rets) >= 2 else None,
                "method": "sample standard deviation of simple close-to-close returns; annualized assuming continuous crypto trading",
            }
        correlation_groups[interval] = {**correlation_matrix(series), "realized_volatility": vol}

    shocks = [-0.10, -0.05, -0.03, -0.01, 0.01, 0.03, 0.05, 0.10]
    scenarios = []
    marked_positions = [m for m in marks if m.get("mark_price") is not None]
    for shock in shocks:
        pnl = 0.0
        for item in marked_positions:
            direction = 1 if item.get("direction") == "LONG" else -1
            notional_at_mark = float(item.get("allocated_quantity") or 0.0) * float(item["mark_price"])
            pnl += notional_at_mark * direction * shock
        scenarios.append({"scenario": f"PARALLEL_{shock * 100:+.0f}PCT", "underlying_price_shock_pct": shock * 100.0,
                          "estimated_incremental_pnl_quote": pnl,
                          "interpretation": "Linear instantaneous shock to every open underlying; excludes gap, nonlinear, funding, margin and liquidation effects."})
    adverse = sum(
        float(m.get("allocated_quantity") or 0.0) * float(m.get("mark_price") or 0.0)
        * (1 if m.get("direction") == "SHORT" else -1) * 0.02
        for m in marked_positions
    )
    scenarios.append({"scenario": "ADVERSE_TO_EACH_POSITION_2PCT", "underlying_price_shock_pct": None,
                      "estimated_incremental_pnl_quote": adverse,
                      "interpretation": "Each position is shocked 2% against its own direction; deliberately conservative but not a coherent market-wide move."})

    return {
        "as_of": now.isoformat(), "status": "COMPLETE" if complete else "INCOMPLETE_MARKS",
        "open_position_count": len(open_positions), "marked_position_count": sum(1 for m in marks if m["mark_status"] == "MARKED"),
        "missing_mark_count": len(missing), "stale_mark_count": len(stale),
        "gross_unrealized_pnl_quote": gross_unrealized if complete else None,
        "estimated_net_unrealized_pnl_quote": unrealized if complete else None,
        "positions": marks, "correlation_by_interval": correlation_groups,
        "stress_scenarios": scenarios if complete and len(marked_positions) == len(open_positions) else [],
        "methodology": {
            "marks": "Latest cached closed Binance Spot candle close; no mark from forming, stale or non-Binance candles is accepted as a complete portfolio mark.",
            "unrealized_pnl": "Allocated portfolio quantity; entry fill and estimated adverse exit spread/slippage plus taker fee on both sides using each execution's frozen assumptions.",
            "correlation": "Pearson correlation of synchronized closed-candle simple returns, grouped by timeframe; at least 30 paired returns required.",
            "volatility": "Sample standard deviation of close-to-close simple returns; annualization assumes 24/7 crypto trading.",
            "stress": "Instantaneous linear shocks on current marked notional; not a historical replay or liquidation model.",
        },
        "notice": "Research estimates only. Binance Spot candle closes are proxies, not executable bid/ask marks. Correlation is historical and unstable; stress scenarios omit nonlinear effects, margin, liquidation, funding, borrow and market impact. No account data or orders are used.",
        "live_trading_eligible": False,
    }
