"""AllTick streaming adapter based on the uploaded provider protocol docs.

One connection carries exactly one subscription (trade ticks OR order book).
The provider requires an application heartbeat every 10 seconds and closes
connections after 30 seconds without one. This worker uses 10-second heartbeats,
bounded reconnect backoff, strict JSON parsing and timestamp/sequence checks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import websockets

from app.core.config import settings
from app.market_data.alltick_provider import SYMBOL_CODES, configured
from app.market_data.data_quality import record_observation

logger = logging.getLogger(__name__)
WS_URL = "wss://quote.alltick.co/quote-b-ws-api"
_quotes: dict[str, dict[str, Any]] = {}
_orderbooks: dict[str, dict[str, Any]] = {}
_state: dict[str, Any] = {
    "status": "DISABLED", "connected": False, "connected_at": None,
    "last_message_at": None, "last_tick_at": None, "last_error": None,
    "reconnect_count": 0, "messages_received": 0, "invalid_messages": 0,
    "out_of_order_messages": 0, "subscription": "trade", "symbols": [],
    "subscription_acknowledged": False, "subscription_ack_at": None,
    "stale_after_seconds": 45,
}
_last_seq: dict[str, int] = {}


def _symbols() -> list[str]:
    requested = [x.strip().upper() for x in settings.alltick_ws_symbols.split(",") if x.strip()]
    return [x for x in requested if x in SYMBOL_CODES]


def _provider_timestamp(raw: Any) -> str | None:
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
        # AllTick docs describe tick_time as milliseconds for pushes, but some
        # examples use a 10-digit seconds value. Normalize both forms.
        seconds = value / 1000 if value >= 100_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def get_quotes() -> list[dict[str, Any]]:
    return [dict(v) for v in _quotes.values()]


def get_orderbooks() -> list[dict[str, Any]]:
    return [dict(v) for v in _orderbooks.values()]


def get_status() -> dict[str, Any]:
    configured_ws = bool(settings.alltick_ws_enabled and configured())
    result = dict(_state)
    result.update({
        "provider": "AllTick WebSocket",
        "enabled": bool(settings.alltick_ws_enabled),
        "configured": configured(),
        "status": _state["status"] if configured_ws else ("DISABLED" if not settings.alltick_ws_enabled else "CONFIGURATION_REQUIRED"),
        "subscription": settings.alltick_ws_subscription.lower(),
        "symbols": _symbols(),
        "heartbeat_seconds": max(5, min(10, settings.alltick_ws_heartbeat_seconds)),
        "stale_after_seconds": max(15, settings.alltick_ws_stale_seconds),
        "connection_limit_notice": "AllTick connection entitlements vary by plan; only one MarketMind stream is opened.",
        "data_notice": "Streaming trades or order book only. AllTick documentation states K-line push is not supported; historical candles remain REST sourced.",
    })
    now = time.time()
    last = _state.get("last_tick_epoch")
    result["feed_freshness"] = "UNKNOWN" if last is None else ("FRESH" if now - last <= max(15, settings.alltick_ws_stale_seconds) else "STALE")
    result.pop("last_tick_epoch", None)
    return result


def _build_subscription(symbols: list[str], subscription: str, seq: int) -> dict[str, Any]:
    if subscription == "trade":
        return {"cmd_id": 22004, "seq_id": seq, "trace": f"marketmind-{seq}", "data": {"symbol_list": [{"code": SYMBOL_CODES[s]} for s in symbols]}}
    if subscription == "depth":
        return {"cmd_id": 22002, "seq_id": seq, "trace": f"marketmind-{seq}", "data": {"symbol_list": [{"code": SYMBOL_CODES[s], "depth_level": 5 if s in {"BTCUSDT", "ETHUSDT", "SOLUSDT"} else 1} for s in symbols]}}
    raise ValueError("ALLTICK_WS_SUBSCRIPTION must be trade or depth")


def process_message(message: str | bytes) -> dict[str, Any] | None:
    """Validate and normalize one provider push; safe for deterministic tests."""
    try:
        payload = json.loads(message)
        if not isinstance(payload, dict):
            raise ValueError("message is not a JSON object")
        cmd = int(payload.get("cmd_id", -1))
        if "ret" in payload and int(payload.get("ret", 200)) != 200:
            raise RuntimeError(f"AllTick WebSocket error {payload.get('ret')}: {str(payload.get('msg', 'unknown'))[:120]}")
        data = payload.get("data")
        if cmd in {22003, 22005} and int(payload.get("ret", 200)) == 200:
            _state["subscription_acknowledged"] = True
            _state["subscription_ack_at"] = datetime.now(timezone.utc).isoformat()
            return None
        if not isinstance(data, dict):
            if "ret" in payload and int(payload.get("ret", 200)) != 200:
                raise RuntimeError(f"AllTick WebSocket error {payload.get('ret')}: {str(payload.get('msg', 'unknown'))[:120]}")
            return None
        code = str(data.get("code", ""))
        symbol = next((s for s, provider_code in SYMBOL_CODES.items() if provider_code == code), None)
        if symbol is None:
            return None
        received = datetime.now(timezone.utc).isoformat()
        stamp = _provider_timestamp(data.get("tick_time"))
        if cmd == 22998:
            price = float(data.get("price"))
            if price <= 0:
                raise ValueError("non-positive trade price")
            seq = int(data.get("seq", 0) or 0)
            if seq and seq <= _last_seq.get(symbol, -1):
                _state["out_of_order_messages"] += 1
                return None
            if seq:
                _last_seq[symbol] = seq
            item = {
                "symbol": symbol, "provider_symbol": code, "price": price,
                "volume": float(data.get("volume") or 0),
                "turnover": float(data.get("turnover") or 0),
                "trade_direction": int(data.get("trade_direction") or 0),
                "sequence": seq or None, "timestamp": stamp,
                "received_at": received, "source": "AllTick WebSocket trade tick",
                "data_status": "LIVE" if stamp else "LIVE_TIMESTAMP_UNAVAILABLE",
            }
            _quotes[symbol] = item
            if settings.tick_storage_enabled:
                record_observation("AllTick WebSocket", item, "trade", settings.tick_storage_min_interval_seconds)
        elif cmd == 22999:
            def levels(key: str) -> list[dict[str, float]]:
                output = []
                for level in data.get(key, []) or []:
                    price = float(level.get("price") or 0)
                    volume = float(level.get("volume") or 0)
                    if price > 0:
                        output.append({"price": price, "volume": volume})
                return output
            bids, asks = levels("bids"), levels("asks")
            best_bid = bids[0]["price"] if bids else None
            best_ask = asks[0]["price"] if asks else None
            spread = best_ask - best_bid if best_bid is not None and best_ask is not None else None
            mid = (best_ask + best_bid) / 2 if spread is not None else None
            item = {
                "symbol": symbol, "provider_symbol": code, "bids": bids,
                "asks": asks, "best_bid": best_bid, "best_ask": best_ask,
                "spread": spread,
                "spread_bps": (spread / mid * 10000) if spread is not None and mid else None,
                "price": mid,
                "timestamp": stamp, "received_at": received,
                "source": "AllTick WebSocket order book",
                "data_status": "LIVE" if stamp else "LIVE_TIMESTAMP_UNAVAILABLE",
            }
            _orderbooks[symbol] = item
            if settings.tick_storage_enabled and mid is not None:
                record_observation("AllTick WebSocket", item, "orderbook_mid", max(5.0, settings.tick_storage_min_interval_seconds * 5))
        else:
            return None
        _state["messages_received"] += 1
        _state["last_message_at"] = received
        if stamp:
            _state["last_tick_at"] = stamp
            try:
                _state["last_tick_epoch"] = datetime.fromisoformat(stamp).timestamp()
            except ValueError:
                pass
        _state["invalid_messages"] = int(_state.get("invalid_messages", 0))
        _state["last_error"] = None
        return dict(item)
    except Exception as exc:
        _state["invalid_messages"] += 1
        _state["last_error"] = str(exc)[:240]
        logger.warning("Rejected AllTick WebSocket message: %s", exc)
        return None


async def _heartbeat_loop(ws: Any) -> None:
    seq = 1
    while True:
        await asyncio.sleep(max(5, min(10, settings.alltick_ws_heartbeat_seconds)))
        await ws.send(json.dumps({"cmd_id": 22000, "seq_id": seq, "trace": f"marketmind-heartbeat-{seq}", "data": {}}))
        seq += 1


async def run_stream() -> None:
    if not settings.alltick_ws_enabled:
        _state["status"] = "DISABLED"
        return
    if not configured():
        _state["status"] = "CONFIGURATION_REQUIRED"
        return
    symbols = _symbols()
    if not symbols:
        _state["status"] = "NO_VALID_SYMBOLS"
        return
    subscription = settings.alltick_ws_subscription.strip().lower()
    if subscription not in {"trade", "depth"}:
        _state["status"] = "CONFIGURATION_ERROR"
        _state["last_error"] = "ALLTICK_WS_SUBSCRIPTION must be trade or depth"
        return
    if len(symbols) > 5:
        _state["status"] = "CONFIGURATION_ERROR"
        _state["last_error"] = "Free-tier documented subscription limit is five products per connection; reduce ALLTICK_WS_SYMBOLS or verify plan entitlement"
        return
    _state["subscription"] = subscription
    _state["symbols"] = symbols
    _state["subscription_acknowledged"] = False
    _state["subscription_ack_at"] = None
    backoff = 2
    while True:
        heartbeat_task = None
        connection_started = None
        try:
            _state["status"] = "CONNECTING"
            uri = WS_URL + "?" + urlencode({"token": settings.alltick_api_key.strip()})
            async with websockets.connect(uri, ping_interval=None, open_timeout=15, close_timeout=5, max_size=2**20) as ws:
                _state["connected"] = True
                connection_started = time.monotonic()
                _state["status"] = "SUBSCRIBING"
                _state["connected_at"] = datetime.now(timezone.utc).isoformat()
                _state["last_error"] = None
                seq = int(time.time())
                await ws.send(json.dumps(_build_subscription(symbols, subscription, seq)))
                heartbeat_task = asyncio.create_task(_heartbeat_loop(ws))
                _state["status"] = "CONNECTED"
                while True:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=25)
                    except asyncio.TimeoutError:
                        _state["status"] = "STALE"
                        raise RuntimeError("No AllTick WebSocket message received for 25 seconds")
                    try:
                        decoded = json.loads(message)
                    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                        decoded = None
                    if isinstance(decoded, dict) and "ret" in decoded and int(decoded.get("ret", 200)) != 200:
                        process_message(message)
                        raise RuntimeError(f"AllTick subscription/stream error {decoded.get('ret')}: {str(decoded.get('msg', 'unknown'))[:120]}")
                    process_message(message)
        except asyncio.CancelledError:
            _state["status"] = "STOPPED"
            raise
        except Exception as exc:
            error_text = str(exc)
            if settings.alltick_api_key:
                error_text = error_text.replace(settings.alltick_api_key, "[REDACTED]")
            _state["last_error"] = error_text[:240]
            if connection_started is not None and time.monotonic() - connection_started >= 60:
                backoff = 2
            _state["status"] = "RECONNECTING"
            _state["reconnect_count"] += 1
            logger.warning("AllTick WebSocket disconnected; retry in %ss: %s", backoff, exc)
        finally:
            _state["connected"] = False
            if heartbeat_task:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
        await asyncio.sleep(backoff)
        backoff = min(max(2, settings.alltick_ws_reconnect_max_seconds), backoff * 2)
