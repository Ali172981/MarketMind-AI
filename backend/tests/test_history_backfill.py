import asyncio

from app.market_data import candle_history


def kline(open_time):
    return [open_time, "100", "101", "99", "100.5", "10", open_time + 3599999,
            "1000", 5, "4", "400", "0"]


def test_backfill_paginates_backwards_and_stores_chronologically(monkeypatch, tmp_path):
    from app.market_data import candle_store

    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "candles.db")
    requested = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, params):
            requested.append(params.copy())
            if "endTime" not in params:
                return FakeResponse([kline(5000 + 1000 * i) for i in range(1000)])
            return FakeResponse([kline(3000), kline(4000)])

    monkeypatch.setattr(candle_history.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(candle_history.backfill_history("BTCUSDT", "1h", 1002))
    stored = candle_store.get_candles("BTCUSDT", "1h", 1010)
    assert result["fetched_candles"] == 1002
    assert result["pages_requested"] == 2
    assert len(stored) == 1002
    assert stored[0]["time"] == 3
    assert requested[1]["endTime"] == 4999


def test_backfill_rejects_unsupported_market_and_size():
    async def run_bad():
        try:
            await candle_history.backfill_history("FAKEUSDT", "1h", 500)
        except ValueError as exc:
            assert "Unsupported symbol" in str(exc)
        else:
            raise AssertionError("Expected unsupported-symbol validation")
    asyncio.run(run_bad())
