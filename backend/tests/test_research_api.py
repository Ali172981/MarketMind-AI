from fastapi.testclient import TestClient
from app.main import app
import app.api.routes.research as research_route

client = TestClient(app)


def test_research_api_rejects_unknown_symbol_without_network():
    response = client.get("/api/v1/market/research/calibration?symbol=BAD&interval=1h")
    assert response.status_code == 400


def test_research_api_returns_gate_status(monkeypatch):
    candles = [{"time": i * 3600, "open": 100, "high": 101, "low": 99, "close": 100,
                "volume": 10, "is_closed": True} for i in range(50)]

    async def fake_get_ohlcv(symbol, interval, limit):
        return {"items": candles, "data_status": "HISTORICAL", "source": "unit test", "count": len(candles)}

    monkeypatch.setattr(research_route, "get_ohlcv", fake_get_ohlcv)
    # This route test injects its own candle data and does not need provider
    # pollers or the ASGI lifespan to run.
    test_client = TestClient(app)
    response = test_client.get("/api/v1/market/research/calibration?symbol=BTCUSDT&interval=1h&limit=500")
    assert response.status_code == 200
    body = response.json()
    assert body["study"]["status"] == "INSUFFICIENT_DATA"
    assert body["study"]["probabilities_published"] is False


def test_walk_forward_api_alias_is_registered():
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/market/research/walk-forward" in paths
    assert "/api/v1/market/research/calibration" in paths
