from datetime import datetime, timezone

from app.market_data import candle_store
from app.market_data import data_quality as dq


def setup_function():
    dq._last_persisted.clear()


def test_compare_quotes_within_crypto_band():
    now = datetime.now(timezone.utc).isoformat()
    result = dq.compare_quotes(
        {"price": 100000, "timestamp": now, "received_at": now},
        {"price": 100100, "timestamp": now, "received_at": now},
        "BTCUSDT", "AllTick", "Binance", 90,
    )
    assert result["status"] == "WITHIN_BAND"
    assert result["deviation_bps"] > 0


def test_compare_quotes_flags_crypto_outlier():
    now = datetime.now(timezone.utc).isoformat()
    result = dq.compare_quotes(
        {"price": 100000, "timestamp": now, "received_at": now},
        {"price": 101000, "timestamp": now, "received_at": now},
        "BTCUSDT", "AllTick", "Binance", 90,
    )
    assert result["status"] == "OUTLIER"


def test_metals_use_wider_comparison_band():
    now = datetime.now(timezone.utc).isoformat()
    result = dq.compare_quotes(
        {"price": 4000, "timestamp": now, "received_at": now},
        {"price": 4020, "timestamp": now, "received_at": now},
        "XAUUSD", "AllTick", "XAUS", 90,
    )
    assert result["status"] == "WITHIN_BAND"


def test_stale_and_missing_quote_classification():
    stale = dq.compare_quotes(
        {"price": 100, "timestamp": "2020-01-01T00:00:00+00:00", "received_at": "2020-01-01T00:00:00+00:00"},
        {"price": 100, "timestamp": "2020-01-01T00:00:00+00:00", "received_at": "2020-01-01T00:00:00+00:00"},
        "BTCUSDT", "AllTick", "Binance", 90,
    )
    missing = dq.compare_quotes(None, None, "BTCUSDT", "AllTick", "Binance")
    assert stale["status"] == "STALE"
    assert missing["status"] == "INSUFFICIENT_DATA"


def test_observation_storage_is_rate_limited_and_queryable(tmp_path, monkeypatch):
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "quality.db")
    item = {"symbol": "BTCUSDT", "price": 123.4, "timestamp": "2026-11-22T10:00:00+00:00", "received_at": "2026-11-22T10:00:01+00:00"}
    assert dq.record_observation("AllTick", item, min_interval=60) is True
    assert dq.record_observation("AllTick", item, min_interval=60) is False
    rows = dq.recent_observations("BTCUSDT", 10)
    assert len(rows) == 1
    assert rows[0]["price"] == 123.4


def test_comparison_persistence_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "quality.db")
    now = datetime.now(timezone.utc).isoformat()
    row = dq.compare_quotes(
        {"price": 100, "timestamp": now, "received_at": now},
        {"price": 100, "timestamp": now, "received_at": now},
        "BTCUSDT", "AllTick", "Binance", 90,
    )
    dq.record_comparison(row)
    result = dq.quality_summary()
    assert result["comparisons_in_window"] == 1
    assert result["latest_by_symbol"]["BTCUSDT"]["status"] == "WITHIN_BAND"
