"""Explainable, rule-based strategy hypothesis engine.

This module ranks observable confluence. Its evidence score is not a calibrated
probability, forecast, or instruction to trade. All features use closed candles.
"""
from __future__ import annotations

from typing import Any
from app.analysis.smc import analyze_smc


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes[-period:]]
    losses = [max(-x, 0.0) for x in changes[-period:]]
    avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) < period + 1:
        return None
    ranges = []
    for i, candle in enumerate(candles):
        prev = candles[i - 1]["close"] if i else candle["close"]
        ranges.append(max(candle["high"] - candle["low"], abs(candle["high"] - prev), abs(candle["low"] - prev)))
    return sum(ranges[-period:]) / period


def _volume_ratio(candles: list[dict[str, Any]], period: int = 20) -> float | None:
    if len(candles) < period + 1:
        return None
    baseline = sum(float(x.get("volume", 0) or 0) for x in candles[-period-1:-1]) / period
    current = float(candles[-1].get("volume", 0) or 0)
    return current / baseline if baseline > 0 else None


def _zone_near_price(zones: list[dict], price: float, atr: float | None, wanted: str) -> dict | None:
    if not atr:
        return None
    candidates = [z for z in zones if z.get("type") == wanted and z.get("status") == "OPEN"]
    candidates = [z for z in candidates if float(z["lower"]) - atr * 0.25 <= price <= float(z["upper"]) + atr * 0.25]
    return candidates[-1] if candidates else None


def analyze_strategy(
    symbol: str,
    timeframe_data: list[dict[str, Any]],
    news_items: list[dict[str, Any]] | None = None,
    minimum_score: int = 60,
    minimum_margin: int = 15,
) -> dict[str, Any]:
    """Build a multi-timeframe hypothesis from supplied candles and context."""
    news_items = news_items or []
    valid: list[dict[str, Any]] = []
    for item in timeframe_data:
        candles = [c for c in item.get("candles", []) if c.get("is_closed", True)]
        if len(candles) >= 60:
            valid.append({**item, "candles": candles})
    if not valid:
        return {
            "status": "INSUFFICIENT_DATA", "symbol": symbol,
            "evidence_score": None, "direction": "NEUTRAL",
            "message": "At least 60 closed candles are required on one timeframe.",
            "validated_probability": None,
        }

    # The first supplied timeframe is the execution/analysis focus timeframe.
    focus = valid[0]
    candles = focus["candles"]
    closes = [float(c["close"]) for c in candles]
    price = closes[-1]
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    rsi = _rsi(closes)
    atr = _atr(candles)
    vol_ratio = _volume_ratio(candles)
    smc = analyze_smc(candles)

    long_score = 0
    short_score = 0
    long_evidence: list[dict[str, Any]] = []
    short_evidence: list[dict[str, Any]] = []
    neutral_notes: list[str] = []

    def award(direction: str, points: int, label: str, detail: str) -> None:
        nonlocal long_score, short_score
        target = long_evidence if direction == "LONG" else short_evidence
        if direction == "LONG":
            long_score += points
        else:
            short_score += points
        target.append({"points": points, "factor": label, "detail": detail})

    if ema20 is not None and ema50 is not None:
        if ema20 > ema50 and price > ema20:
            award("LONG", 20, "EMA_TREND", "EMA20 is above EMA50 and the latest close is above EMA20.")
        elif ema20 < ema50 and price < ema20:
            award("SHORT", 20, "EMA_TREND", "EMA20 is below EMA50 and the latest close is below EMA20.")
        else:
            neutral_notes.append("EMA trend is mixed or price is retracing through EMA20.")

    structure = (smc.get("structure") or {}).get("trend")
    if structure == "BULLISH":
        award("LONG", 20, "SMC_STRUCTURE", "Confirmed SMC structure trend is bullish.")
    elif structure == "BEARISH":
        award("SHORT", 20, "SMC_STRUCTURE", "Confirmed SMC structure trend is bearish.")
    else:
        neutral_notes.append("SMC structure is ranging or unresolved.")

    latest_event = (smc.get("structure") or {}).get("latest_event")
    if latest_event:
        # Event recency is measured by its index in the supplied closed-candle set.
        event_time = latest_event.get("time")
        candle_times = [c.get("time") for c in candles]
        try:
            age = len(candles) - 1 - max(i for i, t in enumerate(candle_times) if t == event_time)
        except (ValueError, TypeError):
            age = 999
        if age <= 8:
            award(latest_event["direction"], 10, "RECENT_STRUCTURE_BREAK", f"{latest_event['type']} confirmed {age} candle(s) ago.")

    if rsi is not None:
        if 50 <= rsi <= 68:
            award("LONG", 10, "RSI_MOMENTUM", f"RSI(14) is {rsi:.1f}, consistent with positive but not extreme momentum.")
        elif 32 <= rsi < 50:
            award("SHORT", 10, "RSI_MOMENTUM", f"RSI(14) is {rsi:.1f}, consistent with negative but not extreme momentum.")
        elif rsi > 75 or rsi < 25:
            neutral_notes.append(f"RSI(14) is {rsi:.1f}; extreme momentum is treated as a caution, not directional confirmation.")

    if atr:
        bull_fvg = _zone_near_price(smc.get("fair_value_gaps", []), price, atr, "BULLISH_FVG")
        bear_fvg = _zone_near_price(smc.get("fair_value_gaps", []), price, atr, "BEARISH_FVG")
        if bull_fvg:
            award("LONG", 10, "BULLISH_FVG_LOCATION", "Price is at or near an open bullish fair-value-gap candidate.")
        if bear_fvg:
            award("SHORT", 10, "BEARISH_FVG_LOCATION", "Price is at or near an open bearish fair-value-gap candidate.")
        sweep = (smc.get("liquidity") or {}).get("latest_sweep")
        if sweep:
            sweep_time = sweep.get("time")
            try:
                age = len(candles) - 1 - max(i for i, c in enumerate(candles) if c.get("time") == sweep_time)
            except (ValueError, TypeError):
                age = 999
            if age <= 5:
                direction = "SHORT" if "BUY_SIDE" in sweep.get("type", "") else "LONG"
                award(direction, 10, "RECENT_LIQUIDITY_SWEEP", f"{sweep['type']} detected {age} candle(s) ago; reversal interpretation is a hypothesis.")

    if vol_ratio is not None:
        if vol_ratio >= 1.25:
            direction = "LONG" if closes[-1] > candles[-1]["open"] else "SHORT" if closes[-1] < candles[-1]["open"] else "NEUTRAL"
            if direction != "NEUTRAL":
                award(direction, 5, "RELATIVE_VOLUME", f"Latest volume is {vol_ratio:.2f}x the preceding 20-candle average, with directional candle body.")
        else:
            neutral_notes.append(f"Relative volume is {vol_ratio:.2f}x; no expansion confirmation.")

    mtf: list[dict[str, Any]] = []
    for item in valid[1:]:
        result = analyze_smc(item["candles"])
        trend = (result.get("structure") or {}).get("trend", "UNKNOWN")
        mtf.append({"interval": item["interval"], "trend": trend, "data_status": item.get("data_status", "UNKNOWN")})
        if trend == "BULLISH":
            award("LONG", 5, f"MTF_{item['interval']}", f"{item['interval']} structure is bullish.")
        elif trend == "BEARISH":
            award("SHORT", 5, f"MTF_{item['interval']}", f"{item['interval']} structure is bearish.")

    # Scores are bounded display indices, not probabilities or expected returns.
    long_score = min(100, long_score)
    short_score = min(100, short_score)
    margin = abs(long_score - short_score)
    direction = "LONG" if long_score > short_score else "SHORT" if short_score > long_score else "NEUTRAL"
    top_score = max(long_score, short_score)
    status = "WATCH" if top_score >= minimum_score and margin >= minimum_margin else "NO_CLEAR_SETUP"
    if status == "WATCH" and direction != "NEUTRAL":
        evidence = long_evidence if direction == "LONG" else short_evidence
    else:
        evidence = []

    invalidation = target_1 = target_2 = None
    risk_distance = None
    if status == "WATCH" and atr and direction != "NEUTRAL":
        if direction == "LONG":
            recent_lows = [float(p["price"]) for p in (smc.get("structure") or {}).get("swing_lows", []) if float(p["price"]) < price]
            structural_stop = max(recent_lows) if recent_lows else price - 1.5 * atr
            invalidation = min(structural_stop, price - 0.5 * atr)
            risk_distance = price - invalidation
            target_1, target_2 = price + risk_distance, price + 2 * risk_distance
        else:
            recent_highs = [float(p["price"]) for p in (smc.get("structure") or {}).get("swing_highs", []) if float(p["price"]) > price]
            structural_stop = min(recent_highs) if recent_highs else price + 1.5 * atr
            invalidation = max(structural_stop, price + 0.5 * atr)
            risk_distance = invalidation - price
            target_1, target_2 = price - risk_distance, price - 2 * risk_distance

    return {
        "status": status,
        "symbol": symbol,
        "direction": direction if status == "WATCH" else "NEUTRAL",
        "focus_interval": focus["interval"],
        "evidence_score": top_score,
        "long_score": long_score,
        "short_score": short_score,
        "score_margin": margin,
        "score_definition": "Bounded rule-confluence index from 0 to 100; not a probability, confidence interval, or expected return.",
        "validated_probability": None,
        "price_reference": price,
        "invalidation_reference": invalidation,
        "target_1_reference": target_1,
        "target_2_reference": target_2,
        "risk_distance_reference": risk_distance,
        "indicators": {"ema20": ema20, "ema50": ema50, "rsi14": rsi, "atr14": atr, "relative_volume20": vol_ratio},
        "focus_structure": structure or "UNKNOWN",
        "multi_timeframe": mtf,
        "supporting_evidence": evidence,
        "opposing_evidence": short_evidence if direction == "LONG" else long_evidence if direction == "SHORT" else long_evidence + short_evidence,
        "neutral_notes": neutral_notes,
        "news_context": {
            "relevant_headlines": len(news_items),
            "items": [{"headline": n.get("headline"), "source_name": n.get("source_name"), "published_at": n.get("published_at"), "verification": n.get("verification", "SOURCE_RSS_UNVERIFIED"), "event_categories": n.get("event_categories", [])} for n in news_items[:5]],
            "interpretation": "Headlines are unverified RSS context only; no directional points are awarded from heuristic news tags.",
        },
        "data_sources": [{"interval": x["interval"], "source": x.get("source"), "data_status": x.get("data_status"), "candles": len(x["candles"])} for x in valid],
        "minimum_score": minimum_score,
        "minimum_margin": minimum_margin,
        "disclaimer": "Research hypothesis only. Price references are closed-candle levels, not executable quotes. Stops and targets are structural/ATR scenarios, not orders. No live orders or validated probabilities are produced.",
    }
