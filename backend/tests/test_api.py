from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_assets():
    response = client.get("/api/v1/assets")
    assert response.status_code == 200
    symbols = [item["symbol"] for item in response.json()["items"]]
    assert "BTCUSDT" in symbols
    assert "XAUUSD" in symbols
    assert "XAGUSD" in symbols


def test_prices_are_labelled_demo():
    response = client.get("/api/v1/market/prices")
    assert response.status_code == 200
    assert response.json()["data_status"] == "DEMO"


def test_unknown_symbol_returns_404():
    response = client.get("/api/v1/market/prices?symbol=NOTREAL")
    assert response.status_code == 404


def test_alltick_stream_status_endpoint_is_read_only():
    response = client.get("/api/v1/market/stream")
    assert response.status_code == 200
    payload = response.json()
    assert "stream" in payload
    assert "orderbooks" in payload
    assert payload["stream"]["provider"] == "AllTick WebSocket"


def test_cross_provider_data_quality_endpoints():
    response = client.get("/api/v1/market/data-quality")
    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "status_counts" in payload["summary"]
    assert client.get("/api/v1/market/data-quality/comparisons?limit=10").status_code == 200
    assert client.get("/api/v1/market/data-quality/observations?symbol=BTCUSDT&limit=10").status_code == 200
