from app.analysis import paper_observations as paper
from app.market_data import candle_store


def candle(i, open_=100.0, high=100.5, low=99.5, close=100.0):
    return {
        "time": i * 3600, "open": open_, "high": high, "low": low,
        "close": close, "volume": 10.0, "is_closed": True,
    }


def configure_latest_event(monkeypatch, rows):
    event = {
        "type": "BULLISH_BOS", "direction": "BULLISH",
        "time": rows[-1]["time"], "level": 99.0,
    }
    monkeypatch.setattr(paper, "_pivot_points", lambda *args: ([], []))
    monkeypatch.setattr(paper, "_structure_events", lambda *args: ([event], "BULLISH"))
    monkeypatch.setattr(paper, "_feature_vector", lambda *args: [0.1, 0.2, 0.3, 1.0, 0.0])
    monkeypatch.setattr(paper, "_atr", lambda *args: 2.0)
    monkeypatch.setattr(paper, "_causal_volatility_regimes", lambda candles, **kwargs: ["LOW_VOL"] * len(candles))
    monkeypatch.setattr(paper, "_market_regime", lambda *args: "RANGE")


def setup_db(monkeypatch, tmp_path):
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "paper-test.db")


def create_one_observation(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    rows = [candle(i) for i in range(100)]
    configure_latest_event(monkeypatch, rows)
    result = paper.record_latest_structure_observations(
        "BTCUSDT", "1h", rows, stop_multiple=0.5, reward_risk=1.0, horizon_bars=2,
        data_source="unit test",
    )
    assert result["observations_created"] == 1
    return rows


def test_record_latest_event_is_idempotent_and_contains_no_probability(monkeypatch, tmp_path):
    rows = [candle(i) for i in range(100)]
    setup_db(monkeypatch, tmp_path)
    configure_latest_event(monkeypatch, rows)
    first = paper.record_latest_structure_observations("BTCUSDT", "1h", rows, data_source="test")
    second = paper.record_latest_structure_observations("BTCUSDT", "1h", rows, data_source="test")
    items = paper.list_observations("BTCUSDT", "1h")
    assert first["observations_created"] == 1
    assert second["observations_created"] == 0
    assert len(items) == 1
    assert items[0]["status"] == "WAITING_FOR_ENTRY"
    assert "probability" not in items[0]
    assert paper.observation_summary("BTCUSDT", "1h")["probabilities_recorded"] is False


def test_next_candle_target_touch_settles_observation(monkeypatch, tmp_path):
    rows = create_one_observation(monkeypatch, tmp_path)
    future = rows + [candle(100, open_=100.0, high=101.5, low=99.5, close=101.0)]
    result = paper.advance_open_observations("BTCUSDT", "1h", future)
    item = paper.list_observations("BTCUSDT", "1h")[0]
    assert result["settled"] == 1
    assert item["status"] == "SETTLED"
    assert item["outcome"] == "TARGET"
    assert item["outcome_label"] == 1
    assert item["entry_time"] == future[100]["time"]


def test_same_bar_stop_and_target_is_conservatively_stop_first(monkeypatch, tmp_path):
    rows = create_one_observation(monkeypatch, tmp_path)
    future = rows + [candle(100, open_=100.0, high=102.0, low=98.0, close=100.0)]
    paper.advance_open_observations("BTCUSDT", "1h", future)
    item = paper.list_observations("BTCUSDT", "1h")[0]
    assert item["outcome"] == "STOP"
    assert item["outcome_label"] == 0


def test_horizon_without_threshold_touch_is_timeout(monkeypatch, tmp_path):
    rows = create_one_observation(monkeypatch, tmp_path)
    future = rows + [candle(100), candle(101), candle(102)]
    paper.advance_open_observations("BTCUSDT", "1h", future)
    item = paper.list_observations("BTCUSDT", "1h")[0]
    assert item["status"] == "SETTLED"
    assert item["outcome"] == "TIMEOUT"
    assert item["outcome_label"] == 0
