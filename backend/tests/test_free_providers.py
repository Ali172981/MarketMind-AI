import asyncio
from unittest.mock import AsyncMock

from app.market_data import xaus_provider, fred_provider


def test_xaus_refresh_normalizes_both_metals(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "spot_usd_oz": 2350.5,
                "silver_usd_oz": 28.75,
                "updated_at": "2026-11-21T10:00:00Z",
                "data_state": {"status": "fresh", "as_of": "2026-11-21T09:59:30Z", "age_seconds": 30},
            }
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, *args, **kwargs):
            return FakeResponse()
    monkeypatch.setattr(xaus_provider.httpx, "AsyncClient", FakeClient)
    asyncio.run(xaus_provider.refresh_once())
    quotes = {item["symbol"]: item for item in xaus_provider.get_metals_quotes()}
    assert quotes["XAUUSD"]["price"] == 2350.5
    assert quotes["XAGUSD"]["price"] == 28.75
    assert quotes["XAUUSD"]["data_status"] == "LIVE"


def test_fred_csv_parser_uses_latest_non_missing_observation(monkeypatch):
    class FakeResponse:
        text = "observation_date,DGS2\n2026-11-19,3.90\n2026-11-20,.\n2026-11-21,3.95\n"
        def raise_for_status(self):
            pass
    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResponse()
    result = asyncio.run(fred_provider._fetch_series(FakeClient(), "DGS2", "2026-11-01"))
    assert result["value"] == 3.95
    assert result["observation_date"] == "2026-11-21"
    assert result["data_status"] == "DAILY_OBSERVATION"
