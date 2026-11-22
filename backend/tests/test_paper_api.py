from fastapi.testclient import TestClient
from app.main import app
import app.api.routes.paper as paper_route

client = TestClient(app)


def test_paper_observe_route_records_without_probabilities(monkeypatch):
    async def fake_get_ohlcv(symbol, interval, limit):
        return {"items": [], "data_status": "HISTORICAL", "source": "test", "count": 0}

    monkeypatch.setattr(paper_route, "get_ohlcv", fake_get_ohlcv)
    monkeypatch.setattr(paper_route, "advance_open_observations", lambda *args: {"advanced": 0, "settled": 0})
    monkeypatch.setattr(paper_route, "advance_paper_executions", lambda *args: {"created": 0, "opened": 0, "settled": 0, "waiting": 0, "data_window_missing": 0})
    monkeypatch.setattr(paper_route, "record_latest_structure_observations", lambda *args, **kwargs: {
        "status": "INSUFFICIENT_DATA", "observations_created": 0,
    })
    monkeypatch.setattr(paper_route, "observation_summary", lambda *args: {
        "total_observations": 0, "probabilities_recorded": False, "orders_submitted": False,
    })
    response = client.post("/api/v1/market/research/paper/observe?symbol=BTCUSDT&interval=1h")
    assert response.status_code == 200
    body = response.json()
    assert body["probabilities_recorded"] is False
    assert body["orders_submitted"] is False
    assert body["recording"]["observations_created"] == 0


def test_paper_observation_api_validates_symbol():
    response = client.get("/api/v1/market/research/paper/observations?symbol=INVALID")
    assert response.status_code == 400


def test_paper_observation_routes_are_registered():
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/market/research/paper/observe" in paths
    assert "/api/v1/market/research/paper/observations" in paths
    assert "/api/v1/market/research/paper/summary" in paths


def test_paper_automation_status_is_read_only_and_discloses_safeguards():
    response = client.get("/api/v1/market/research/paper/automation/status")
    assert response.status_code == 200
    body = response.json()
    assert "configuration" in body
    assert "runtime" in body
    assert body["probabilities_recorded"] is False
    assert body["orders_submitted"] is False


def test_paper_automation_run_history_route_is_registered():
    response = client.get("/api/v1/market/research/paper/automation/runs?limit=5")
    assert response.status_code == 200
    assert isinstance(response.json()["items"], list)
    assert response.json()["orders_submitted"] is False
    summary = client.get("/api/v1/market/research/paper/executions/summary?symbol=BTCUSDT&interval=1h")
    assert summary.status_code == 200
    assert summary.json()["orders_submitted"] is False
    ledger = client.get("/api/v1/market/research/paper/executions?symbol=BTCUSDT&interval=1h")
    assert ledger.status_code == 200
    assert isinstance(ledger.json()["items"], list)


def test_paper_execution_routes_are_registered_and_read_only():
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/market/research/paper/executions" in paths
    assert "/api/v1/market/research/paper/executions/summary" in paths
    assert "/api/v1/market/research/paper/executions/assumptions" in paths
    response = client.get("/api/v1/market/research/paper/executions/assumptions")
    assert response.status_code == 200
    assert response.json()["orders_submitted"] is False
    summary = client.get("/api/v1/market/research/paper/executions/summary?symbol=BTCUSDT&interval=1h")
    assert summary.status_code == 200
    assert summary.json()["orders_submitted"] is False
    ledger = client.get("/api/v1/market/research/paper/executions?symbol=BTCUSDT&interval=1h")
    assert ledger.status_code == 200
    assert isinstance(ledger.json()["items"], list)


def test_portfolio_summary_route_is_registered_and_read_only():
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/market/research/paper/portfolio/summary" in paths
    response = client.get("/api/v1/market/research/paper/portfolio/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["orders_submitted"] is False
    assert body["probabilities_recorded"] is False
    assert body["live_trading_eligible"] is False
    assert "equity_curve" in body
