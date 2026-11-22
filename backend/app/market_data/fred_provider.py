"""Keyless public CSV download of selected FRED chart series.

FRED's documented JSON API requires an API key. This adapter uses the public
fredgraph.csv chart-download endpoint; it is convenient but not a versioned
API contract, so failures are surfaced and source timestamps are preserved.
"""
import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)
CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = {
    "DGS2": {"label": "US 2-Year Treasury Yield", "unit": "%", "kind": "treasury_yield"},
    "DGS10": {"label": "US 10-Year Treasury Yield", "unit": "%", "kind": "treasury_yield"},
    "DTWEXBGS": {"label": "US Dollar Broad Index (proxy, not ICE DXY)", "unit": "index", "kind": "usd_proxy"},
}
_snapshot: dict[str, dict[str, Any]] = {}
_state = "STARTING"
_last_refresh_at: str | None = None
_last_error: str | None = None


def get_macro_snapshot() -> dict[str, Any]:
    return {
        "provider": "FRED public CSV download",
        "status": _state,
        "last_refresh_at": _last_refresh_at,
        "frequency": "Daily observations; not an intraday tick feed",
        "items": [dict(value) for value in _snapshot.values()],
        "last_error": _last_error,
        "note": "DTWEXBGS is a broad trade-weighted USD index proxy, not ICE DXY. Missing observations are not filled or fabricated.",
    }


async def _fetch_series(client: httpx.AsyncClient, series_id: str, start_date: str) -> dict[str, Any] | None:
    response = await client.get(CSV_URL, params={"id": series_id, "cosd": start_date})
    response.raise_for_status()
    text = response.text
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    value_column = series_id
    for row in reversed(rows):
        raw = (row.get(value_column) or "").strip()
        if raw and raw not in (".", "NA", "N/A"):
            meta = SERIES[series_id]
            return {
                "symbol": series_id,
                "name": meta["label"],
                "value": float(raw),
                "unit": meta["unit"],
                "kind": meta["kind"],
                "observation_date": row.get("observation_date"),
                "source": "Federal Reserve Bank of St. Louis (FRED)",
                "data_status": "DAILY_OBSERVATION",
            }
    return None


async def refresh_once() -> None:
    global _state, _last_refresh_at, _last_error
    start_date = (datetime.now(timezone.utc).date() - timedelta(days=30)).isoformat()
    results: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "MarketMindAI/0.3 (public-macro-data)"}) as client:
        for series_id in SERIES:
            try:
                item = await _fetch_series(client, series_id, start_date)
                if item:
                    results[series_id] = item
            except Exception as exc:
                logger.warning("FRED CSV refresh failed for %s: %s", series_id, exc)
    if results:
        _snapshot.update(results)
        _last_refresh_at = datetime.now(timezone.utc).isoformat()
        _state = "CONNECTED" if len(results) == len(SERIES) else "PARTIAL"
        _last_error = None if len(results) == len(SERIES) else "One or more series could not be refreshed"
    elif _snapshot:
        _state = "STALE"
        _last_error = "Refresh failed; showing last successfully observed values"
    else:
        _state = "ERROR"
        _last_error = "No macro observations could be retrieved"


async def run_fred_refresh() -> None:
    global _state
    while True:
        try:
            await refresh_once()
        except asyncio.CancelledError:
            _state = "STOPPED"
            raise
        except Exception as exc:
            _state = "STALE" if _snapshot else "ERROR"
            logger.warning("Macro refresh failed: %s", exc)
        # These series update daily; one-hour polling is sufficient.
        await asyncio.sleep(3600)
