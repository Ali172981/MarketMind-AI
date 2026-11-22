import asyncio
import math
import time

import pytest

from app.analysis import paper_observations
from app.market_data import candle_store
from app.workers import paper_recorder


def closed_candles(count=120):
    latest_open = int(time.time() // 3600) * 3600 - 3600
    rows = []
    for i in range(count):
        centre = 100 + 2 * math.sin(i / 5)
        rows.append({
            "time": latest_open - (count - 1 - i) * 3600,
            "open": centre - 0.1,
            "high": centre + 0.8,
            "low": centre - 0.8,
            "close": centre + 0.1,
            "volume": 10 + (i % 7),
            "is_closed": True,
        })
    return rows


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "recorder-test.db")


def test_cycle_processes_binance_closed_candles_and_persists_audit(isolated_db):
    rows = closed_candles()

    async def fetcher(symbol, interval, limit):
        return {"items": rows, "source": "Binance Spot REST + WebSocket", "data_status": "LIVE"}

    result = asyncio.run(paper_recorder.run_recorder_cycle(
        trigger="TEST", symbols=["BTCUSDT"], intervals=["1h"], limit=200, fetcher=fetcher,
    ))

    assert result["status"] == "OK"
    assert result["pairs_processed"] == 1
    assert result["probabilities_recorded"] is False
    assert result["orders_submitted"] is False
    runs = paper_observations.list_recorder_runs(5)
    assert len(runs) == 1
    assert runs[0]["trigger"] == "TEST"
    assert runs[0]["results"][0]["closed_candles"] == 120


def test_cycle_rejects_non_binance_source_and_records_error(isolated_db):
    async def fetcher(symbol, interval, limit):
        return {"items": closed_candles(), "source": "Demo sample feed", "data_status": "DEMO"}

    result = asyncio.run(paper_recorder.run_recorder_cycle(
        trigger="TEST", symbols=["BTCUSDT"], intervals=["1h"], fetcher=fetcher,
    ))
    assert result["status"] == "FAILED"
    assert result["pairs_processed"] == 0
    assert "Non-Binance" in result["errors"][0]["error"]


def test_cycle_rejects_stale_market_candles(isolated_db):
    rows = closed_candles()
    for row in rows:
        row["time"] -= 10 * 3600

    async def fetcher(symbol, interval, limit):
        return {"items": rows, "source": "Binance Spot REST", "data_status": "HISTORICAL"}

    result = asyncio.run(paper_recorder.run_recorder_cycle(
        trigger="TEST", symbols=["BTCUSDT"], intervals=["1h"], fetcher=fetcher,
    ))
    assert result["status"] == "FAILED"
    assert "stale" in result["errors"][0]["error"].lower()


def test_recorder_configuration_refuses_invalid_values(monkeypatch):
    monkeypatch.setattr(paper_recorder.settings, "paper_recorder_enabled", True)
    monkeypatch.setattr(paper_recorder.settings, "data_mode", "binance")
    monkeypatch.setattr(paper_recorder.settings, "paper_recorder_symbols", "BTCUSDT,FAKECOIN")
    monkeypatch.setattr(paper_recorder.settings, "paper_recorder_intervals", "1h")
    config = paper_recorder.recorder_config()
    assert config["enabled"] is False
    assert config["symbols"] == ["BTCUSDT"]
    assert config["invalid_symbols"] == ["FAKECOIN"]
    assert config["blocked_reason"]
