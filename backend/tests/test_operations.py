from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_detailed_health_diagnostics_shape():
    response = client.get("/api/v1/health/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "0.18.0"
    assert payload["status"] in {"ok", "degraded", "error"}
    assert {"database", "binance_websocket", "market_data", "disk"}.issubset(payload["checks"])
    assert "telegram_bot_token" not in str(payload)


def test_write_api_key_gate():
    original = settings.api_access_key
    settings.api_access_key = "test-secret"
    try:
        response = client.post("/api/v1/market/research/paper/observe")
        assert response.status_code == 401
        assert response.json()["detail"].startswith("Valid X-API-Key")
    finally:
        settings.api_access_key = original
