import asyncio
from datetime import datetime, timezone

from app.market_data import alltick_provider as provider


def test_alltick_symbol_and_interval_maps_match_documented_products():
    assert provider.SYMBOL_CODES["BTCUSDT"] == "BTCUSDT"
    assert provider.SYMBOL_CODES["XAUUSD"] == "GOLD"
    assert provider.SYMBOL_CODES["XAGUSD"] == "Silver"
    assert provider.INTERVAL_TYPES["15m"] == 3
    assert provider.INTERVAL_TYPES["1h"] == 5
    assert provider.INTERVAL_TYPES["1d"] == 8


def test_check_payload_rejects_provider_errors():
    import pytest
    with pytest.raises(RuntimeError, match="AllTick API error"):
        provider._check_payload({"ret": 401, "msg": "bad token"})


def test_fetch_quotes_normalizes_ticks(monkeypatch):
    monkeypatch.setattr(provider.settings, "alltick_api_key", "test-token")
    monkeypatch.setattr(provider, "_request_slot", lambda: asyncio.sleep(0))

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "ret": 200,
                "msg": "ok",
                "data": {"tick_list": [
                    {"code": "BTCUSDT", "tick_time": "1795255200000", "price": "90000.5"},
                    {"code": "GOLD", "tick_time": "1795255200000", "price": "4100.25"},
                    {"code": "Silver", "tick_time": "1795255200000", "price": "52.5"},
                ]},
            }

    class Client:
        async def post(self, *args, **kwargs):
            return Response()

    items = asyncio.run(provider.fetch_quotes_once(Client()))
    indexed = {item["symbol"]: item for item in items}
    assert indexed["BTCUSDT"]["price"] == 90000.5
    assert indexed["XAUUSD"]["provider_symbol"] == "GOLD"
    assert indexed["XAGUSD"]["provider_symbol"] == "Silver"
    assert indexed["BTCUSDT"]["data_status"] == "LIVE"
    assert indexed["BTCUSDT"]["change_percent_24h"] is None


def test_alltick_status_discloses_missing_token(monkeypatch):
    monkeypatch.setattr(provider.settings, "alltick_api_key", "")
    status = provider.get_status()
    assert status["configured"] is False
    assert status["status"] == "CONFIGURATION_REQUIRED"
    assert status["poll_seconds"] >= 90


def test_alltick_kline_response_is_normalized_and_source_tagged(monkeypatch):
    monkeypatch.setattr(provider.settings, "alltick_api_key", "test-token")
    monkeypatch.setattr(provider, "_request_slot", lambda: asyncio.sleep(0))
    stored = []
    monkeypatch.setattr(provider, "read_candles", lambda *args, **kwargs: [])
    monkeypatch.setattr(provider, "upsert_candles", lambda rows: stored.extend(rows))
    monkeypatch.setattr(provider, "read_candles", lambda *args, **kwargs: stored)

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "ret": 200, "msg": "ok",
                "data": {"code": "BTCUSDT", "kline_type": 5, "kline_list": [{
                    "timestamp": "1700000000", "open_price": "35000",
                    "close_price": "35100", "high_price": "35200",
                    "low_price": "34900", "volume": "12.5", "turnover": "438750",
                }]},
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, *args, **kwargs):
            assert "/kline/" in args[0]
            assert kwargs["headers"]["X-API-Key"] == "test-token"
            return Response()

    monkeypatch.setattr(provider.httpx, "AsyncClient", Client)
    payload = asyncio.run(provider.get_ohlcv("BTCUSDT", "1h", 100))
    assert payload["source"] == "AllTick REST K-line"
    assert payload["count"] == 1
    assert stored[0]["open_time"] == 1_700_000_000_000
    assert stored[0]["close_time"] == 1_700_000_000_000 + 3_600_000 - 1
    assert stored[0]["source"] == "AllTick REST K-line"
    assert stored[0]["trades"] == 0


def test_candle_store_keeps_provider_history_separate(tmp_path, monkeypatch):
    from app.market_data import candle_store
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "provider-test.sqlite")
    common = {
        "symbol": "BTCUSDT", "interval": "1h", "open_time": 1_700_000_000_000,
        "close_time": 1_700_003_599_999, "open": 1.0, "high": 2.0,
        "low": 0.5, "volume": 10.0, "quote_volume": 10.0,
        "trades": 1, "taker_buy_base": 1.0, "is_closed": True,
    }
    candle_store.upsert_candles([{**common, "close": 1.5, "source": "Binance Spot REST"}])
    candle_store.upsert_candles([{**common, "close": 1.8, "source": "AllTick REST K-line"}])
    binance = candle_store.get_candles("BTCUSDT", "1h", 10, source="Binance")
    alltick = candle_store.get_candles("BTCUSDT", "1h", 10, source="AllTick")
    assert binance[0]["close"] == 1.5
    assert alltick[0]["close"] == 1.8
    assert "binance" in binance[0]["source"].lower()
    assert "alltick" in alltick[0]["source"].lower()


def test_binance_candle_provider_dispatches_to_alltick_when_selected(monkeypatch):
    from app.market_data import candle_provider
    monkeypatch.setattr(provider.settings, "data_mode", "alltick")

    async def fake_alltick(symbol, interval, limit):
        return {"symbol": symbol, "interval": interval, "source": "AllTick REST K-line", "count": 0, "items": []}

    monkeypatch.setattr(provider, "get_ohlcv", fake_alltick)
    result = asyncio.run(candle_provider.get_ohlcv("XAUUSD", "1h", 250))
    assert result["symbol"] == "XAUUSD"
    assert result["source"] == "AllTick REST K-line"
