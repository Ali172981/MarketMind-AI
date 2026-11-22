from datetime import datetime, timezone

from app.market_data import candle_store
from app.market_data.data_quality import record_observation
from app.market_data.microstructure import analyze_orderbook, estimate_sweep, latest_orderbook, orderbook_history


def sample_book():
    return {
        "symbol": "BTCUSDT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "bids": [
            {"price": 99990, "volume": 1.0},
            {"price": 99980, "volume": 2.0},
            {"price": 99970, "volume": 3.0},
        ],
        "asks": [
            {"price": 100010, "volume": 1.5},
            {"price": 100020, "volume": 2.5},
            {"price": 100030, "volume": 4.0},
        ],
    }


def test_orderbook_metrics_spread_imbalance_and_microprice():
    result = analyze_orderbook(sample_book())
    assert result["status"] == "OK"
    assert result["spread"] == 20
    assert result["spread_bps"] > 0
    assert result["top5_imbalance"] < 0
    assert result["bid_levels"] == 3
    assert result["ask_levels"] == 3


def test_invalid_and_crossed_books_are_rejected():
    assert analyze_orderbook({"symbol": "BTCUSDT", "bids": [], "asks": []})["status"] == "INSUFFICIENT_DEPTH"
    crossed = {"symbol": "BTCUSDT", "bids": [{"price": 101, "volume": 1}], "asks": [{"price": 100, "volume": 1}]}
    assert analyze_orderbook(crossed)["status"] == "CROSSED_OR_INVALID_BOOK"


def test_buy_sweep_walks_asks_and_reports_partial_depth():
    result = estimate_sweep(sample_book(), "buy", 2.0)
    assert result["status"] == "FULL_DEPTH_COVERAGE"
    assert result["filled_visible_quantity"] == 2.0
    assert result["estimated_vwap"] > result["reference_mid"]
    partial = estimate_sweep(sample_book(), "buy", 100)
    assert partial["status"] == "PARTIAL_DEPTH_COVERAGE"
    assert partial["visible_fill_ratio"] < 1


def test_sell_sweep_walks_bids_and_rejects_invalid_inputs():
    result = estimate_sweep(sample_book(), "sell", 2.0)
    assert result["status"] == "FULL_DEPTH_COVERAGE"
    assert result["estimated_vwap"] < result["reference_mid"]
    try:
        estimate_sweep(sample_book(), "hold", 1)
        assert False, "invalid side should raise"
    except ValueError:
        pass


def test_stale_orderbook_not_used_for_sweep():
    book = sample_book()
    book["received_at"] = "2020-01-01T00:00:00+00:00"
    result = estimate_sweep(book, "buy", 1)
    assert result["status"] == "STALE_BOOK"


def test_depth_snapshot_persistence_and_history(tmp_path, monkeypatch):
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "micro.db")
    book = sample_book()
    book["price"] = 100000
    book["timestamp"] = book["received_at"]
    assert record_observation("AllTick WebSocket", book, "orderbook_mid", 0)
    latest = latest_orderbook("BTCUSDT")
    assert latest is not None
    assert analyze_orderbook(latest)["status"] == "OK"
    history = orderbook_history("BTCUSDT")
    assert len(history) == 1
    assert history[0]["spread"] == 20
