"""Historical REST + live WebSocket OHLCV provider using Binance public data only."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets

from app.market_data.candle_store import get_candles as read_candles, latest_open_time, upsert_candles

logger = logging.getLogger(__name__)
REST_URL = "https://data-api.binance.vision/api/v3/klines"
WS_BASE = "wss://data-stream.binance.vision:443/stream?streams="
SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
INTERVALS = {"15m", "30m", "1h", "2h", "4h", "1d"}
MAX_LIMIT = 1000
REST_COOLDOWN_SECONDS = 15
_last_rest_fetch: dict[tuple[str, str], float] = {}
_live_updates: dict[tuple[str, str], str] = {}
_ws_status = "STARTING"
_ws_last_message: str | None = None


def _from_rest(symbol: str, interval: str, k: list[Any]) -> dict[str, Any]:
    return {
        "symbol": symbol, "interval": interval,
        "open_time": int(k[0]), "close_time": int(k[6]),
        "open": float(k[1]), "high": float(k[2]), "low": float(k[3]),
        "close": float(k[4]), "volume": float(k[5]),
        "quote_volume": float(k[7]), "trades": int(k[8]),
        "taker_buy_base": float(k[9]),
        "is_closed": int(k[6]) < int(time.time() * 1000),
        "source": "Binance Spot REST",
    }


def _from_ws(symbol: str, interval: str, k: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol, "interval": interval,
        "open_time": int(k["t"]), "close_time": int(k["T"]),
        "open": float(k["o"]), "high": float(k["h"]), "low": float(k["l"]),
        "close": float(k["c"]), "volume": float(k["v"]),
        "quote_volume": float(k["q"]), "trades": int(k["n"]),
        "taker_buy_base": float(k["V"]), "is_closed": bool(k["x"]),
        "source": "Binance Spot WebSocket",
    }


async def fetch_history(symbol: str, interval: str, limit: int = 500) -> list[dict[str, Any]]:
    params = {"symbol": symbol, "interval": interval, "limit": min(max(int(limit), 1), MAX_LIMIT)}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "MarketMindAI/0.4 public-market-data"}) as client:
        response = await client.get(REST_URL, params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Unexpected Binance kline response")
    rows = [_from_rest(symbol, interval, item) for item in payload]
    upsert_candles(rows)
    _last_rest_fetch[(symbol, interval)] = time.monotonic()
    return rows


async def get_ohlcv(symbol: str, interval: str, limit: int = 300) -> dict[str, Any]:
    # Provider dispatch is centralized so SMC/backtest/research routes consume
    # the selected provider while candle storage remains source-segregated.
    from app.core.config import settings
    if settings.data_mode.lower() == "alltick":
        from app.market_data.alltick_provider import get_ohlcv as get_alltick_ohlcv
        return await get_alltick_ohlcv(symbol, interval, limit)
    key = (symbol, interval)
    limit = min(max(int(limit), 1), 20_000)
    cached = read_candles(symbol, interval, limit)
    last_fetch = _last_rest_fetch.get(key, 0.0)
    # Larger research requests trigger paginated history backfill. Each Binance
    # request remains within the documented 1,000-kline page maximum.
    if limit > MAX_LIMIT and len(cached) < limit:
        try:
            from app.market_data.candle_history import backfill_history
            await backfill_history(symbol, interval, limit)
            _last_rest_fetch[key] = time.monotonic()
            cached = read_candles(symbol, interval, limit)
        except Exception as exc:
            logger.warning("Binance historical backfill failed for %s %s: %s", symbol, interval, exc)
            if not cached:
                raise
    # Warm the cache on first use, then refresh the latest page at most once per
    # REST cooldown. Live WebSocket updates overwrite the active candle between refreshes.
    elif not cached or time.monotonic() - last_fetch >= REST_COOLDOWN_SECONDS:
        try:
            await fetch_history(symbol, interval, min(max(limit, 1), MAX_LIMIT))
            cached = read_candles(symbol, interval, limit)
        except Exception as exc:
            logger.warning("Binance candle REST refresh failed for %s %s: %s", symbol, interval, exc)
            if not cached:
                raise
    now = datetime.now(timezone.utc).isoformat()
    last_live = _live_updates.get(key)
    live_recent = False
    if last_live:
        try:
            live_recent = (datetime.now(timezone.utc) - datetime.fromisoformat(last_live)).total_seconds() < 60
        except ValueError:
            pass
    return {
        "symbol": symbol,
        "interval": interval,
        "source": "Binance Spot REST + WebSocket",
        "data_status": "LIVE" if live_recent else ("HISTORICAL" if cached else "UNAVAILABLE"),
        "last_live_update": last_live,
        "fetched_at": now,
        "count": len(cached),
        "items": cached,
        "notice": "Exchange spot OHLCV. The newest candle may still be forming until its close; historical candles are not broker-specific CFD prices.",
    }


def get_candle_feed_status() -> dict[str, Any]:
    return {
        "provider": "Binance Spot Kline WebSocket",
        "status": _ws_status,
        "last_message_at": _ws_last_message,
        "symbols": sorted(SYMBOLS),
        "intervals": sorted(INTERVALS),
    }


async def run_candle_stream() -> None:
    global _ws_status, _ws_last_message
    streams = [f"{symbol.lower()}@kline_{interval}" for symbol in sorted(SYMBOLS) for interval in sorted(INTERVALS)]
    url = WS_BASE + "/".join(streams)
    while True:
        try:
            _ws_status = "CONNECTING"
            async with websockets.connect(url, ping_interval=20, ping_timeout=60, close_timeout=10, max_queue=2000) as socket:
                _ws_status = "CONNECTED"
                logger.info("Connected to Binance kline stream (%s streams)", len(streams))
                async for raw in socket:
                    message = json.loads(raw)
                    event = message.get("data", message)
                    if event.get("e") != "kline":
                        continue
                    symbol = event.get("s")
                    kline = event.get("k", {})
                    interval = kline.get("i")
                    if symbol not in SYMBOLS or interval not in INTERVALS:
                        continue
                    row = _from_ws(symbol, interval, kline)
                    upsert_candles([row])
                    stamp = datetime.now(timezone.utc).isoformat()
                    _live_updates[(symbol, interval)] = stamp
                    _ws_last_message = stamp
        except asyncio.CancelledError:
            _ws_status = "STOPPED"
            raise
        except Exception as exc:
            _ws_status = "RECONNECTING"
            logger.warning("Binance kline stream interrupted: %s", exc)
            await asyncio.sleep(5)
