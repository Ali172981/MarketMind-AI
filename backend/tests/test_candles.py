from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_candles_rejects_unknown_symbol_before_network():
    response = client.get("/api/v1/market/candles?symbol=FAKEUSDT&interval=1h")
    assert response.status_code == 400


def test_candles_rejects_unsupported_interval_before_network():
    response = client.get("/api/v1/market/candles?symbol=BTCUSDT&interval=7m")
    assert response.status_code == 400


def test_candle_status_endpoint():
    response = client.get("/api/v1/market/candles/status")
    assert response.status_code == 200
    assert response.json()["provider"] == "Binance Spot Kline WebSocket"


def test_candle_store_upserts_and_returns_chronological_rows(tmp_path, monkeypatch):
    from app.market_data import candle_store

    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "candles.db")
    rows = [
        {"symbol": "BTCUSDT", "interval": "1h", "open_time": 2000, "close_time": 5599,
         "open": 2.0, "high": 3.0, "low": 1.5, "close": 2.5, "volume": 10.0,
         "quote_volume": 20.0, "trades": 4, "taker_buy_base": 5.0, "is_closed": 1,
         "source": "test"},
        {"symbol": "BTCUSDT", "interval": "1h", "open_time": 1000, "close_time": 4599,
         "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 8.0,
         "quote_volume": 12.0, "trades": 3, "taker_buy_base": 4.0, "is_closed": 1,
         "source": "test"},
    ]
    candle_store.upsert_candles(rows)
    candles = candle_store.get_candles("BTCUSDT", "1h", 10)
    assert [item["time"] for item in candles] == [1, 2]
    assert candles[0]["close"] == 1.5
    assert candles[0]["is_closed"] is True


def test_rest_kline_normalization():
    from app.market_data.candle_provider import _from_rest

    normalized = _from_rest("BTCUSDT", "1h", [1000, "10", "12", "9", "11", "4", 9999999999999, "44", 7, "2", "22", "0"])
    assert normalized["symbol"] == "BTCUSDT"
    assert normalized["interval"] == "1h"
    assert normalized["open"] == 10.0
    assert normalized["close"] == 11.0
    assert normalized["trades"] == 7


def test_smc_rejects_unknown_symbol_before_network():
    response = client.get("/api/v1/market/smc?symbol=FAKEUSDT&interval=1h")
    assert response.status_code == 400
