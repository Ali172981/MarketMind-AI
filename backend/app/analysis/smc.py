"""Deterministic, explainable Smart Money Concepts primitives.

Signals are descriptive chart annotations, not trade recommendations. Only closed
candles are analysed by default to avoid repainting from an unfinished candle.
"""
from __future__ import annotations

from typing import Any


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) < 2:
        return None
    ranges = []
    for i, c in enumerate(candles):
        prev_close = candles[i - 1]["close"] if i else c["close"]
        ranges.append(max(c["high"] - c["low"], abs(c["high"] - prev_close), abs(c["low"] - prev_close)))
    sample = ranges[-period:]
    return sum(sample) / len(sample) if sample else None


def _pivot_points(candles: list[dict[str, Any]], left: int, right: int) -> tuple[list[dict], list[dict]]:
    highs: list[dict] = []
    lows: list[dict] = []
    for i in range(left, len(candles) - right):
        window = candles[i-left:i+right+1]
        c = candles[i]
        # Strict on at least one side, deterministic on ties.
        if c["high"] == max(x["high"] for x in window) and sum(x["high"] == c["high"] for x in window) == 1:
            highs.append({"index": i, "confirmed_at_index": i + right, "time": c.get("time"), "price": c["high"]})
        if c["low"] == min(x["low"] for x in window) and sum(x["low"] == c["low"] for x in window) == 1:
            lows.append({"index": i, "confirmed_at_index": i + right, "time": c.get("time"), "price": c["low"]})
    return highs, lows


def _structure_events(candles: list[dict], highs: list[dict], lows: list[dict]) -> tuple[list[dict], str]:
    events: list[dict] = []
    broken_highs: set[int] = set()
    broken_lows: set[int] = set()
    trend = "RANGE"
    pivots = sorted([(p["confirmed_at_index"], "HIGH", p) for p in highs] + [(p["confirmed_at_index"], "LOW", p) for p in lows])
    high_by_idx = {p["index"]: p for p in highs}
    low_by_idx = {p["index"]: p for p in lows}
    # Walk forward. A pivot is only available after its right-side confirmation.
    active_highs: list[dict] = []
    active_lows: list[dict] = []
    pivot_cursor = 0
    for i, candle in enumerate(candles):
        while pivot_cursor < len(pivots) and pivots[pivot_cursor][0] <= i:
            _, kind, pivot = pivots[pivot_cursor]
            (active_highs if kind == "HIGH" else active_lows).append(pivot)
            pivot_cursor += 1
        candidates = [p for p in active_highs if p["index"] not in broken_highs and candle["close"] > p["price"]]
        if candidates:
            pivot = max(candidates, key=lambda p: p["index"])
            label = "BULLISH_BOS" if trend == "BULLISH" else "BULLISH_CHOCH" if trend == "BEARISH" else "BULLISH_STRUCTURE_BREAK"
            events.append({"type": label, "direction": "BULLISH", "time": candle.get("time"), "price": candle["close"], "level": pivot["price"], "level_time": pivot.get("time"), "explanation": f"Closed above confirmed swing high {pivot['price']:.8g}."})
            broken_highs.add(pivot["index"])
            trend = "BULLISH"
        candidates = [p for p in active_lows if p["index"] not in broken_lows and candle["close"] < p["price"]]
        if candidates:
            pivot = max(candidates, key=lambda p: p["index"])
            label = "BEARISH_BOS" if trend == "BEARISH" else "BEARISH_CHOCH" if trend == "BULLISH" else "BEARISH_STRUCTURE_BREAK"
            events.append({"type": label, "direction": "BEARISH", "time": candle.get("time"), "price": candle["close"], "level": pivot["price"], "level_time": pivot.get("time"), "explanation": f"Closed below confirmed swing low {pivot['price']:.8g}."})
            broken_lows.add(pivot["index"])
            trend = "BEARISH"
    return events, trend


def _liquidity(candles: list[dict], highs: list[dict], lows: list[dict], atr: float | None) -> tuple[list[dict], list[dict]]:
    tolerance = max((atr or 0) * 0.12, (candles[-1]["close"] if candles else 0) * 0.0005)
    pools: list[dict] = []
    sweeps: list[dict] = []
    for kind, points in (("BUY_SIDE", highs), ("SELL_SIDE", lows)):
        for i, p in enumerate(points):
            for q in points[i+1:]:
                if q["index"] - p["index"] > 120:
                    break
                if abs(p["price"] - q["price"]) <= tolerance:
                    level = (p["price"] + q["price"]) / 2
                    pools.append({"type": kind, "level": level, "touches": 2, "first_time": p.get("time"), "last_time": q.get("time"), "status": "RESTING_LIQUIDITY"})
                    for candle in candles[q["index"]+1:]:
                        swept = candle["high"] > level + tolerance if kind == "BUY_SIDE" else candle["low"] < level - tolerance
                        returned = candle["close"] < level if kind == "BUY_SIDE" else candle["close"] > level
                        if swept and returned:
                            sweeps.append({"type": f"{kind}_SWEEP", "level": level, "time": candle.get("time"), "close": candle["close"], "explanation": "Wick traded beyond a clustered swing level and the candle closed back inside."})
                            break
                    break
    # Deduplicate nearby levels, keeping the most recently formed pool.
    unique: list[dict] = []
    for pool in sorted(pools, key=lambda x: x.get("last_time") or 0):
        if not any(x["type"] == pool["type"] and abs(x["level"] - pool["level"]) <= tolerance for x in unique):
            unique.append(pool)
    return unique[-20:], sweeps[-20:]


def _fvg(candles: list[dict]) -> list[dict]:
    zones: list[dict] = []
    for i in range(2, len(candles)):
        a, middle, c = candles[i-2], candles[i-1], candles[i]
        if a["high"] < c["low"]:
            zones.append({"type": "BULLISH_FVG", "lower": a["high"], "upper": c["low"], "formed_time": c.get("time"), "status": "OPEN", "midpoint": (a["high"] + c["low"]) / 2})
        elif a["low"] > c["high"]:
            zones.append({"type": "BEARISH_FVG", "lower": c["high"], "upper": a["low"], "formed_time": c.get("time"), "status": "OPEN", "midpoint": (c["high"] + a["low"]) / 2})
    # Mark whether later price action has fully crossed the gap.
    for zone in zones:
        later = [x for x in candles if (x.get("time") or 0) > (zone.get("formed_time") or 0)]
        if zone["type"] == "BULLISH_FVG" and any(x["low"] <= zone["lower"] for x in later):
            zone["status"] = "MITIGATED"
        if zone["type"] == "BEARISH_FVG" and any(x["high"] >= zone["upper"] for x in later):
            zone["status"] = "MITIGATED"
    return zones[-30:]


def _order_blocks(candles: list[dict], events: list[dict]) -> list[dict]:
    blocks: list[dict] = []
    time_to_index = {c.get("time"): i for i, c in enumerate(candles)}
    for event in events:
        idx = time_to_index.get(event.get("time"))
        if idx is None:
            continue
        bullish = event["direction"] == "BULLISH"
        for j in range(idx-1, max(-1, idx-11), -1):
            c = candles[j]
            is_opposite = c["close"] < c["open"] if bullish else c["close"] > c["open"]
            if is_opposite:
                blocks.append({"type": "BULLISH_ORDER_BLOCK" if bullish else "BEARISH_ORDER_BLOCK", "lower": c["low"], "upper": c["high"], "formed_time": c.get("time"), "break_time": event.get("time"), "status": "UNMITIGATED_CANDIDATE", "validation": "Last opposite-colour candle before a confirmed structure break; requires subsequent reaction/backtest validation."})
                break
    return blocks[-20:]


def analyze_smc(raw_candles: list[dict[str, Any]], left: int = 3, right: int = 3) -> dict[str, Any]:
    candles = [c for c in raw_candles if c.get("is_closed", True)]
    if len(candles) < max(20, left + right + 5):
        return {"status": "INSUFFICIENT_DATA", "candles_analyzed": len(candles), "minimum_required": max(20, left + right + 5), "message": "More closed candles are needed for stable swing and structure analysis."}
    highs, lows = _pivot_points(candles, left, right)
    events, trend = _structure_events(candles, highs, lows)
    atr = _atr(candles)
    pools, sweeps = _liquidity(candles, highs, lows, atr)
    gaps = _fvg(candles)
    blocks = _order_blocks(candles, events)
    latest = candles[-1]
    latest_event = events[-1] if events else None
    return {
        "status": "OK",
        "method": "Deterministic SMC rules v1",
        "candles_analyzed": len(candles),
        "latest_closed_candle_time": latest.get("time"),
        "last_close": latest["close"],
        "atr_14": atr,
        "structure": {"trend": trend, "swing_highs": highs[-12:], "swing_lows": lows[-12:], "events": events[-20:], "latest_event": latest_event},
        "liquidity": {"pools": pools, "sweeps": sweeps, "latest_sweep": sweeps[-1] if sweeps else None},
        "fair_value_gaps": gaps,
        "order_blocks": blocks,
        "disclaimer": "Educational chart analysis, not a trade signal. BOS/CHoCH labels use confirmed pivots and candle closes; order blocks are candidate zones, not proof of institutional orders. Historical performance and forward testing are required before use.",
    }
