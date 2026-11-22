"""Paginated public Binance Spot historical kline backfill."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.market_data.candle_provider import REST_URL, SYMBOLS, INTERVALS, _from_rest
from app.market_data.candle_store import get_candles, upsert_candles

MAX_BACKFILL_CANDLES = 20_000
PAGE_SIZE = 1_000


async def backfill_history(symbol: str, interval: str, limit: int) -> dict[str, Any]:
    symbol = symbol.upper()
    if symbol not in SYMBOLS:
        raise ValueError(f"Unsupported symbol: {symbol}")
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval: {interval}")
    if limit < 1 or limit > MAX_BACKFILL_CANDLES:
        raise ValueError(f"limit must be between 1 and {MAX_BACKFILL_CANDLES}")

    remaining = limit
    end_time: int | None = None
    pages = 0
    rows_by_open: dict[int, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "MarketMindAI/0.7 public-market-data"}) as client:
        while remaining > 0:
            page_limit = min(PAGE_SIZE, remaining)
            params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": page_limit}
            if end_time is not None:
                params["endTime"] = end_time
            response = await client.get(REST_URL, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or not payload:
                break
            page = [_from_rest(symbol, interval, item) for item in payload]
            page.sort(key=lambda row: row["open_time"])
            new_rows = [row for row in page if row["open_time"] not in rows_by_open]
            if not new_rows:
                break
            for row in new_rows:
                rows_by_open[row["open_time"]] = row
            pages += 1
            remaining = limit - len(rows_by_open)
            oldest = min(row["open_time"] for row in page)
            next_end = oldest - 1
            if end_time is not None and next_end >= end_time:
                break
            end_time = next_end
            if len(page) < page_limit:
                break
            if remaining > 0:
                await asyncio.sleep(0.12)

    rows = sorted(rows_by_open.values(), key=lambda row: row["open_time"])[-limit:]
    upsert_candles(rows)
    stored = get_candles(symbol, interval, limit)
    return {
        "symbol": symbol,
        "interval": interval,
        "requested_candles": limit,
        "fetched_candles": len(rows),
        "stored_candles": len(stored),
        "pages_requested": pages,
        "oldest_open_time": rows[0]["open_time"] if rows else None,
        "newest_open_time": rows[-1]["open_time"] if rows else None,
        "source": "Binance Spot public REST klines",
        "api_key_required": False,
        "data_status": "HISTORICAL" if rows else "UNAVAILABLE",
        "notice": "Public exchange spot candles; historical data quality and availability are exchange-dependent. This service does not provide broker-specific CFD prices.",
    }
