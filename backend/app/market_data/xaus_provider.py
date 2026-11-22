"""Free, keyless XAU/XAG spot polling adapter backed by XAUS public API.

The upstream caches spot responses; poll no faster than once per minute.
This is indicative spot data, not an executable broker quote.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)
SPOT_URL = "https://xaus.com/api/v1/spot?compact=1"
POLL_SECONDS = 60
_quotes: dict[str, dict[str, Any]] = {}
_state = "STARTING"
_last_refresh_at: str | None = None
_last_error: str | None = None


def get_metals_quotes() -> list[dict[str, Any]]:
    return [dict(value) for value in _quotes.values()]


def get_metals_status() -> dict[str, Any]:
    return {
        "provider": "XAUS public spot API",
        "status": _state,
        "last_refresh_at": _last_refresh_at,
        "symbols": ["XAUUSD", "XAGUSD"],
        "poll_interval_seconds": POLL_SECONDS,
        "last_error": _last_error,
        "note": "Free keyless indicative spot quotes; upstream cache is about 60 seconds. Not a broker execution quote.",
        "attribution": "https://xaus.com/about/",
    }


async def refresh_once() -> None:
    global _state, _last_refresh_at, _last_error
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "MarketMindAI/0.3 (market-data; contact: local-install)"}) as client:
        response = await client.get(SPOT_URL)
        response.raise_for_status()
        payload = response.json()

    data_state = payload.get("data_state") or {}
    upstream_status = str(data_state.get("status", "unknown")).lower()
    as_of = data_state.get("as_of") or payload.get("price_as_of") or payload.get("updated_at")
    updated_at = payload.get("updated_at") or as_of
    xau = payload.get("spot_usd_oz")
    xag = payload.get("silver_usd_oz")

    if upstream_status == "unavailable" or xau is None:
        _state = "UNAVAILABLE"
        _last_error = "Upstream reports no real spot price available"
        return

    status = "LIVE" if upstream_status == "fresh" else "STALE"
    now = datetime.now(timezone.utc).isoformat()
    next_quotes: dict[str, dict[str, Any]] = {}
    for symbol, price in (("XAUUSD", xau), ("XAGUSD", xag)):
        if price is None:
            continue
        next_quotes[symbol] = {
            "symbol": symbol,
            "price": float(price),
            "change_percent_24h": None,
            "source": "XAUS public spot API",
            "data_status": status,
            "timestamp": as_of or updated_at or now,
            "received_at": now,
            "age_seconds": data_state.get("age_seconds"),
        }
    if not next_quotes:
        _state = "UNAVAILABLE"
        _last_error = "No XAU/XAG values returned by upstream"
        return
    _quotes.update(next_quotes)
    _last_refresh_at = now
    _state = "CONNECTED" if status == "LIVE" else "STALE"
    _last_error = None


async def run_metals_feed() -> None:
    global _state, _last_error
    while True:
        try:
            await refresh_once()
        except asyncio.CancelledError:
            _state = "STOPPED"
            raise
        except Exception as exc:
            _state = "STALE" if _quotes else "ERROR"
            _last_error = str(exc)[:300]
            logger.warning("XAUS metals refresh failed: %s", exc)
        await asyncio.sleep(POLL_SECONDS)
