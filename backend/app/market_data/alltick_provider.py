"""AllTick REST market-data adapter.

Uses the documented AllTick forex/crypto/metals endpoint. This adapter is opt-in,
keeps credentials server-side, enforces conservative free-tier request pacing,
and labels all returned observations with their provider and timestamps.
AllTick WebSocket quote streaming is intentionally not enabled in this milestone;
K-line history is fetched through REST.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.market_data.candle_store import get_candles as read_candles, upsert_candles

logger = logging.getLogger(__name__)

BASE_URL = "https://quote.alltick.co/quote-b-api/v1"
QUOTE_URL = f"{BASE_URL}/quote"
KLINE_URL = f"{BASE_URL}/kline/"
SYMBOL_CODES = {
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
    "SOLUSDT": "SOLUSDT",
    "XAUUSD": "GOLD",
    "XAGUSD": "Silver",
}
INTERVAL_TYPES = {"1m": 1, "5m": 2, "15m": 3, "30m": 4, "1h": 5, "2h": 6, "4h": 7, "1d": 8}
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "1d": 86_400_000}
_quotes: dict[str, dict[str, Any]] = {}
_status = "DISABLED"
_last_message_at: str | None = None
_last_error: str | None = None
_last_request_at = 0.0
_request_lock = asyncio.Lock()
_daily_count = 0
_daily_date = datetime.now(timezone.utc).date()
_last_candle_fetch: dict[tuple[str, str], float] = {}


def configured() -> bool:
    return bool(settings.alltick_api_key.strip())


def get_quotes() -> list[dict[str, Any]]:
    return [dict(item) for item in _quotes.values()]


def get_status() -> dict[str, Any]:
    return {
        "provider": "AllTick REST",
        "status": _status if configured() else "CONFIGURATION_REQUIRED",
        "configured": configured(),
        "last_message_at": _last_message_at,
        "last_error": _last_error,
        "symbols": list(SYMBOL_CODES),
        "poll_seconds": max(90, settings.alltick_poll_seconds),
        "daily_requests_used_by_this_process": _daily_count,
        "daily_request_limit_assumption": 1000,
        "notice": "REST polling, not a WebSocket stream. Free-tier pacing is conservatively set to at least 90 seconds to stay below 1,000 daily requests before manual history queries.",
    }


async def _request_slot() -> None:
    """Enforce one request per 10 seconds and a conservative 1,000/day cap."""
    global _last_request_at, _daily_count, _daily_date
    async with _request_lock:
        today = datetime.now(timezone.utc).date()
        if today != _daily_date:
            _daily_date = today
            _daily_count = 0
        if _daily_count >= 1000:
            raise RuntimeError("AllTick local daily request budget (1,000) reached")
        wait = 10.0 - (time.monotonic() - _last_request_at)
        if _last_request_at and wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()
        _daily_count += 1


def _headers() -> dict[str, str]:
    if not configured():
        raise RuntimeError("ALLTICK_API_KEY is not configured")
    return {"X-API-Key": settings.alltick_api_key.strip(), "Content-Type": "application/json", "User-Agent": "MarketMindAI/0.16"}


def _check_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("AllTick returned a non-object response")
    if int(payload.get("ret", -1)) != 200:
        raise RuntimeError(f"AllTick API error {payload.get('ret')}: {str(payload.get('msg', 'unknown'))[:160]}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("AllTick response is missing data object")
    return data


async def fetch_quotes_once(client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    global _last_message_at, _last_error, _status
    if not configured():
        _status = "CONFIGURATION_REQUIRED"
        return []
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=15.0)
    assert client is not None
    try:
        await _request_slot()
        body = {
            "trace": f"marketmind-{int(time.time() * 1000)}",
            "data": {"symbol_list": [{"code": code} for code in SYMBOL_CODES.values()]},
        }
        response = await client.post(QUOTE_URL, headers=_headers(), json=body)
        response.raise_for_status()
        data = _check_payload(response.json())
        tick_list = data.get("tick_list", [])
        now = datetime.now(timezone.utc).isoformat()
        by_code = {str(item.get("code")): item for item in tick_list if isinstance(item, dict)}
        normalized: list[dict[str, Any]] = []
        for symbol, code in SYMBOL_CODES.items():
            tick = by_code.get(code)
            if not tick or tick.get("price") in (None, ""):
                continue
            raw_ts = tick.get("tick_time")
            try:
                stamp = datetime.fromtimestamp(int(raw_ts) / 1000, tz=timezone.utc).isoformat() if raw_ts else now
            except (ValueError, TypeError, OSError):
                stamp = now
            item = {
                "symbol": symbol,
                "provider_symbol": code,
                "price": float(tick["price"]),
                "change_percent_24h": None,
                "source": "AllTick REST latest trade quote",
                "data_status": "LIVE",
                "timestamp": stamp,
                "received_at": now,
            }
            _quotes[symbol] = item
            normalized.append(item)
        _last_message_at = now
        _last_error = None
        _status = "CONNECTED" if normalized else "CONNECTED_NO_QUOTES"
        return normalized
    except Exception as exc:
        _last_error = str(exc)[:240]
        _status = "ERROR"
        raise
    finally:
        if own:
            await client.aclose()


async def run_quote_feed() -> None:
    global _status, _last_error
    if not configured():
        _status = "CONFIGURATION_REQUIRED"
        return
    while True:
        try:
            _status = "CONNECTING"
            await fetch_quotes_once()
        except asyncio.CancelledError:
            _status = "STOPPED"
            raise
        except Exception as exc:
            logger.warning("AllTick quote refresh failed: %s", exc)
            _last_error = str(exc)[:240]
        await asyncio.sleep(max(90, settings.alltick_poll_seconds))


async def get_ohlcv(symbol: str, interval: str, limit: int = 300) -> dict[str, Any]:
    symbol = symbol.upper()
    if not configured():
        raise RuntimeError("ALLTICK_API_KEY is not configured")
    if symbol not in SYMBOL_CODES:
        raise ValueError(f"Unsupported AllTick symbol: {symbol}")
    if interval not in INTERVAL_TYPES:
        raise ValueError(f"Unsupported AllTick interval: {interval}")
    limit = min(max(int(limit), 1), 500)
    cached = read_candles(symbol, interval, limit, source="AllTick")
    key = (symbol, interval)
    last_fetch = _last_candle_fetch.get(key, 0.0)
    if not cached or time.monotonic() - last_fetch >= 10:
        await _request_slot()
        trace = f"marketmind-{int(time.time() * 1000)}"
        query = {
            "trace": trace,
            "data": {
                "code": SYMBOL_CODES[symbol],
                "kline_type": INTERVAL_TYPES[interval],
                "kline_timestamp_end": 0,
                "query_kline_num": limit,
                "adjust_type": 0,
            },
        }
        url = KLINE_URL + quote(json.dumps(query, separators=(",", ":")), safe="")
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url, headers=_headers())
            response.raise_for_status()
            data = _check_payload(response.json())
        rows = []
        now_ms = int(time.time() * 1000)
        duration = INTERVAL_MS[interval]
        for item in data.get("kline_list", []):
            open_ms = int(item["timestamp"]) * 1000
            close_ms = open_ms + duration - 1
            rows.append({
                "symbol": symbol, "interval": interval,
                "open_time": open_ms, "close_time": close_ms,
                "open": float(item["open_price"]), "high": float(item["high_price"]),
                "low": float(item["low_price"]), "close": float(item["close_price"]),
                "volume": float(item.get("volume") or 0),
                "quote_volume": float(item.get("turnover") or 0),
                "trades": 0, "taker_buy_base": 0.0,
                "is_closed": close_ms < now_ms, "source": "AllTick REST K-line",
            })
        rows.sort(key=lambda row: row["open_time"])
        if rows:
            upsert_candles(rows)
        _last_candle_fetch[key] = time.monotonic()
        cached = read_candles(symbol, interval, limit, source="AllTick")
    return {
        "symbol": symbol, "interval": interval,
        "source": "AllTick REST K-line",
        "data_status": "HISTORICAL" if cached else "UNAVAILABLE",
        "last_live_update": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(cached), "items": cached,
        "provider_symbol": SYMBOL_CODES[symbol],
        "notice": "AllTick K-line history via REST. This is provider-supplied market data, not an exchange-specific or broker-specific executable price. The newest candle is marked closed only after its computed interval end.",
        "provider_limitations": "AllTick documents a maximum of 500 K-lines per request. This adapter does not claim WebSocket K-line support.",
    }
