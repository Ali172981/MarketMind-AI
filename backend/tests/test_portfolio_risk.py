from datetime import datetime, timezone

from app.analysis.portfolio_risk import _position_mark, correlation_matrix, portfolio_risk_snapshot


def test_correlation_matrix_uses_synchronized_returns_and_minimum_sample_gate():
    times = list(range(40))
    left = {t: 100.0 + t for t in times}
    right = {t: 200.0 + 2 * t for t in times}
    result = correlation_matrix({"BTCUSDT": left, "ETHUSDT": right})
    assert result["paired_return_observations"]["BTCUSDT"]["ETHUSDT"] == 39
    assert result["correlation"]["BTCUSDT"]["ETHUSDT"] > 0.999
    short = correlation_matrix({"BTCUSDT": dict(list(left.items())[:20]), "ETHUSDT": dict(list(right.items())[:20])})
    assert short["correlation"]["BTCUSDT"]["ETHUSDT"] is None


def test_mark_to_market_estimates_exit_costs_and_staleness():
    now_ts = 2_000_000_000
    position = {
        "id": 7, "symbol": "BTCUSDT", "interval": "1h", "direction": "LONG",
        "allocated_notional_quote": 1000.0, "entry_reference_price": 100.0,
        "entry_fill_price": 100.1, "stop_price": 95.0,
        "assumptions": {"fee_bps_per_side": 10.0, "full_spread_bps": 4.0, "slippage_bps_per_side": 2.0},
    }
    candle = {"time": now_ts - 3600, "close": 110.0}
    marked = _position_mark(position, candle, now_ts)
    assert marked["mark_status"] == "MARKED"
    assert marked["estimated_unrealized_pnl_quote"] > 0
    stale = _position_mark(position, {"time": now_ts - 20_000, "close": 110.0}, now_ts)
    assert stale["mark_status"] == "STALE_MARK"


def test_snapshot_requires_all_open_positions_to_have_fresh_marks(monkeypatch):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now_ts = int(now.timestamp())
    candles = []
    for i in range(40):
        candles.append({"time": now_ts - (40 - i) * 3600, "close": 100 + i,
                       "source": "Binance Spot REST", "is_closed": True})
    def fake_get_candles(symbol, interval, limit):
        return candles
    monkeypatch.setattr("app.analysis.portfolio_risk.get_candles", fake_get_candles)
    positions = []
    for idx, symbol in enumerate(("BTCUSDT", "ETHUSDT"), start=1):
        positions.append({
            "id": idx, "symbol": symbol, "interval": "1h", "direction": "LONG",
            "allocated_notional_quote": 1000.0, "entry_reference_price": 100.0,
            "entry_fill_price": 100.1, "stop_price": 95.0,
            "assumptions": {"fee_bps_per_side": 10.0, "full_spread_bps": 4.0, "slippage_bps_per_side": 2.0},
        })
    result = portfolio_risk_snapshot(positions, now=now)
    assert result["status"] == "COMPLETE"
    assert result["open_position_count"] == 2
    assert result["estimated_net_unrealized_pnl_quote"] is not None
    corr = result["correlation_by_interval"]["1h"]["correlation"]["BTCUSDT"]["ETHUSDT"]
    assert corr > 0.999
    assert len(result["stress_scenarios"]) == 9


def test_snapshot_withholds_aggregate_marked_equity_inputs_when_any_mark_is_stale(monkeypatch):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now_ts = int(now.timestamp())
    fresh = [{"time": now_ts - 3600, "close": 110.0, "source": "Binance Spot REST", "is_closed": True}]
    stale = [{"time": now_ts - 50_000, "close": 210.0, "source": "Binance Spot REST", "is_closed": True}]
    def fake_get_candles(symbol, interval, limit):
        return fresh if symbol == "BTCUSDT" else stale
    monkeypatch.setattr("app.analysis.portfolio_risk.get_candles", fake_get_candles)
    base = {
        "interval": "1h", "direction": "LONG", "allocated_notional_quote": 1000.0,
        "entry_reference_price": 100.0, "entry_fill_price": 100.1, "stop_price": 95.0,
        "assumptions": {"fee_bps_per_side": 10.0, "full_spread_bps": 4.0, "slippage_bps_per_side": 2.0},
    }
    result = portfolio_risk_snapshot([
        {**base, "id": 1, "symbol": "BTCUSDT"},
        {**base, "id": 2, "symbol": "ETHUSDT"},
    ], now=now)
    assert result["status"] == "INCOMPLETE_MARKS"
    assert result["stale_mark_count"] == 1
    assert result["estimated_net_unrealized_pnl_quote"] is None
    assert result["stress_scenarios"] == []


def test_market_correlation_includes_tracked_universe_not_only_open_position_assets(monkeypatch):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    now_ts = int(now.timestamp())
    candles = [{"time": now_ts - (40 - i) * 3600, "close": 100 + i,
                "source": "Binance Spot REST", "is_closed": True} for i in range(40)]
    monkeypatch.setattr("app.analysis.portfolio_risk.get_candles", lambda symbol, interval, limit: candles)
    position = {
        "id": 1, "symbol": "BTCUSDT", "interval": "1h", "direction": "LONG",
        "allocated_notional_quote": 1000.0, "entry_reference_price": 100.0,
        "entry_fill_price": 100.1, "stop_price": 95.0,
        "assumptions": {"fee_bps_per_side": 10.0, "full_spread_bps": 4.0, "slippage_bps_per_side": 2.0},
    }
    result = portfolio_risk_snapshot([position], now=now)
    assert result["correlation_by_interval"]["1h"]["symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
