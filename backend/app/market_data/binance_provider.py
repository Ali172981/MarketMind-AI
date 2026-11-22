"""Public Binance Spot market-data adapter (market data only; no trading keys)."""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import websockets

logger = logging.getLogger(__name__)

STREAM_URL = (
    "wss://stream.binance.com:9443/stream?streams="
    "btcusdt@ticker/ethusdt@ticker/solusdt@ticker"
)
SYMBOLS = {
    "BTCUSDT": "Bitcoin",
    "ETHUSDT": "Ethereum",
    "SOLUSDT": "Solana",
}

_live_quotes: dict[str, dict[str, Any]] = {}
_connection_state = "STARTING"
_last_message_at: str | None = None


def get_live_quotes() -> list[dict[str, Any]]:
    """Return latest quotes; empty until Binance sends the first update."""
    return [dict(q) for q in _live_quotes.values()]


def get_feed_status() -> dict[str, Any]:
    return {
        "provider": "Binance Spot WebSocket",
        "status": _connection_state,
        "last_message_at": _last_message_at,
        "symbols": list(SYMBOLS),
    }


async def run_binance_feed() -> None:
    """Connect, consume 24h ticker updates, and reconnect after interruptions."""
    global _connection_state, _last_message_at
    while True:
        try:
            _connection_state = "CONNECTING"
            async with websockets.connect(
                STREAM_URL,
                ping_interval=20,
                ping_timeout=60,
                close_timeout=10,
                max_queue=1000,
            ) as socket:
                _connection_state = "CONNECTED"
                logger.info("Connected to Binance public market stream")
                async for raw_message in socket:
                    message = json.loads(raw_message)
                    event = message.get("data", message)
                    symbol = event.get("s")
                    if symbol not in SYMBOLS:
                        continue
                    now = datetime.now(timezone.utc).isoformat()
                    _live_quotes[symbol] = {
                        "symbol": symbol,
                        "price": float(event["c"]),
                        "change_percent_24h": float(event["P"]),
                        "source": "Binance Spot WebSocket",
                        "data_status": "LIVE",
                        "timestamp": now,
                    }
                    _last_message_at = now
        except asyncio.CancelledError:
            _connection_state = "STOPPED"
            raise
        except Exception as exc:  # reconnect on network/provider interruptions
            _connection_state = "RECONNECTING"
            logger.warning("Binance feed interrupted: %s", exc)
            await asyncio.sleep(5)
