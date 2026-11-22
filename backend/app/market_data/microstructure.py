"""Descriptive order-book microstructure and depth-based execution estimates.

Estimates walk the latest stored snapshot only. They are not fills, forecasts,
or substitutes for venue-specific matching-engine simulation.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.market_data import candle_store


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def analyze_orderbook(book: dict[str, Any]) -> dict[str, Any]:
    bids = sorted(
        [{"price": float(x["price"]), "quantity": float(x["volume"])} for x in book.get("bids", []) if _number(x.get("price")) and _number(x.get("volume"))],
        key=lambda x: x["price"], reverse=True,
    )
    asks = sorted(
        [{"price": float(x["price"]), "quantity": float(x["volume"])} for x in book.get("asks", []) if _number(x.get("price")) and _number(x.get("volume"))],
        key=lambda x: x["price"],
    )
    if not bids or not asks:
        return {"status": "INSUFFICIENT_DEPTH", "symbol": book.get("symbol"), "bid_levels": len(bids), "ask_levels": len(asks)}
    bid, ask = bids[0]["price"], asks[0]["price"]
    if ask <= bid:
        return {"status": "CROSSED_OR_INVALID_BOOK", "symbol": book.get("symbol"), "best_bid": bid, "best_ask": ask}
    mid = (bid + ask) / 2
    bid_qty = sum(x["quantity"] for x in bids[:5])
    ask_qty = sum(x["quantity"] for x in asks[:5])
    total_qty = bid_qty + ask_qty
    imbalance = (bid_qty - ask_qty) / total_qty if total_qty else None
    microprice = ((ask * bid_qty) + (bid * ask_qty)) / total_qty if total_qty else None

    def depth_within(levels: list[dict[str, float]], threshold_bps: float, is_bid: bool) -> dict[str, float]:
        bound = mid * (1 - threshold_bps / 10000) if is_bid else mid * (1 + threshold_bps / 10000)
        selected = [x for x in levels if (x["price"] >= bound if is_bid else x["price"] <= bound)]
        return {"quantity": sum(x["quantity"] for x in selected), "notional": sum(x["price"] * x["quantity"] for x in selected)}

    return {
        "status": "OK", "symbol": book.get("symbol"), "provider": book.get("provider", "AllTick WebSocket"),
        "provider_timestamp": book.get("provider_timestamp"), "received_at": book.get("received_at"),
        "best_bid": bid, "best_ask": ask, "mid_price": mid,
        "spread": ask - bid, "spread_bps": (ask - bid) / mid * 10000,
        "bid_levels": len(bids), "ask_levels": len(asks),
        "top5_bid_quantity": bid_qty, "top5_ask_quantity": ask_qty,
        "top5_bid_notional": sum(x["price"] * x["quantity"] for x in bids[:5]),
        "top5_ask_notional": sum(x["price"] * x["quantity"] for x in asks[:5]),
        "top5_imbalance": imbalance, "microprice": microprice,
        "microprice_vs_mid_bps": ((microprice - mid) / mid * 10000) if microprice is not None else None,
        "depth_10bps": {"bids": depth_within(bids, 10, True), "asks": depth_within(asks, 10, False)},
        "depth_25bps": {"bids": depth_within(bids, 25, True), "asks": depth_within(asks, 25, False)},
        "notice": "Snapshot-derived visible depth only. Hidden liquidity, queue priority, cancellations, venue matching and market impact beyond displayed levels are unknown.",
    }


def estimate_sweep(book: dict[str, Any], side: str, quantity: float, max_age_seconds: float = 30.0) -> dict[str, Any]:
    side = side.lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    analysis = analyze_orderbook(book)
    if analysis.get("status") != "OK":
        return {"status": analysis.get("status", "INSUFFICIENT_DEPTH"), "side": side, "requested_quantity": quantity}
    stamp = book.get("received_at")
    try:
        received = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        age = max(0.0, (datetime.now(timezone.utc) - received.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        age = None
    if age is None or age > max_age_seconds:
        return {"status": "STALE_BOOK", "side": side, "requested_quantity": quantity, "book_age_seconds": age, "max_age_seconds": max_age_seconds}
    levels = book.get("asks", []) if side == "buy" else book.get("bids", [])
    levels = sorted(levels, key=lambda x: float(x["price"]), reverse=(side == "sell"))
    remaining, filled, notional = quantity, 0.0, 0.0
    worst_price = None
    for level in levels:
        price = _number(level.get("price"))
        available = _number(level.get("volume"))
        if price is None or available is None:
            continue
        take = min(remaining, available)
        filled += take
        notional += take * price
        remaining -= take
        worst_price = price
        if remaining <= 1e-12:
            break
    mid = analysis["mid_price"]
    filled_vwap = notional / filled if filled else None
    slippage_bps = ((filled_vwap - mid) / mid * 10000) * (1 if side == "buy" else -1) if filled_vwap else None
    return {
        "status": "FULL_DEPTH_COVERAGE" if remaining <= 1e-12 else "PARTIAL_DEPTH_COVERAGE",
        "symbol": book.get("symbol"), "side": side, "requested_quantity": quantity,
        "filled_visible_quantity": filled, "unfilled_quantity": max(0.0, remaining),
        "visible_fill_ratio": filled / quantity, "estimated_vwap": filled_vwap,
        "worst_visible_price": worst_price, "reference_mid": mid,
        "estimated_slippage_bps_vs_mid": slippage_bps,
        "estimated_slippage_quote": (filled_vwap - mid) * filled * (1 if side == "buy" else -1) if filled_vwap else None,
        "book_age_seconds": age, "levels_available": len(levels),
        "notice": "Deterministic sweep of one stored visible-depth snapshot. Excludes fees, latency during execution, queue position, hidden liquidity, cancellations, market impact and partial-fill dynamics. Not an executable quote or guaranteed fill.",
    }


def latest_orderbook(symbol: str) -> dict[str, Any] | None:
    from app.market_data.data_quality import init_quality_db
    init_quality_db()
    with candle_store.db_connection() as conn:
        row = conn.execute(
            "SELECT provider,symbol,provider_timestamp,received_at,payload_json FROM market_observations WHERE symbol=? AND observation_type='orderbook_mid' ORDER BY id DESC LIMIT 1",
            (symbol.upper(),),
        ).fetchone()
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    payload.update({"provider": row["provider"], "symbol": row["symbol"], "provider_timestamp": row["provider_timestamp"], "received_at": row["received_at"]})
    return payload


def orderbook_history(symbol: str, limit: int = 100) -> list[dict[str, Any]]:
    from app.market_data.data_quality import init_quality_db
    init_quality_db()
    with candle_store.db_connection() as conn:
        rows = conn.execute(
            "SELECT provider,symbol,provider_timestamp,received_at,payload_json FROM market_observations WHERE symbol=? AND observation_type='orderbook_mid' ORDER BY id DESC LIMIT ?",
            (symbol.upper(), min(max(int(limit), 1), 500)),
        ).fetchall()
    output = []
    for row in reversed(rows):
        try:
            payload = json.loads(row["payload_json"])
            payload.update({"provider": row["provider"], "symbol": row["symbol"], "provider_timestamp": row["provider_timestamp"], "received_at": row["received_at"]})
            output.append(analyze_orderbook(payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return output
