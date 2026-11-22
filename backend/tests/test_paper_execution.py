from app.analysis import paper_execution as execution
from app.analysis import paper_observations as paper
from app.market_data import candle_store


def candle(i, open_=100.0, high=100.2, low=99.8, close=100.0):
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


def make_observation(monkeypatch, tmp_path, *, delay=0, horizon=2, rejection=0.0):
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "paper-execution.db")
    monkeypatch.setattr(execution.settings, "paper_exec_fee_bps_per_side", 10.0)
    monkeypatch.setattr(execution.settings, "paper_exec_full_spread_bps", 4.0)
    monkeypatch.setattr(execution.settings, "paper_exec_slippage_bps_per_side", 2.0)
    monkeypatch.setattr(execution.settings, "paper_exec_entry_delay_bars", delay)
    monkeypatch.setattr(execution.settings, "paper_exec_position_notional_quote", 1000.0)
    monkeypatch.setattr(execution.settings, "paper_exec_entry_rejection_rate_pct", rejection)
    monkeypatch.setattr(execution.settings, "paper_exec_rejection_seed", "test-seed")
    rows = [candle(i) for i in range(100)]
    configure_latest_event(monkeypatch, rows)
    result = paper.record_latest_structure_observations(
        "BTCUSDT", "1h", rows, stop_multiple=0.5, reward_risk=1.0,
        horizon_bars=horizon, data_source="Binance Spot (unit test)",
    )
    assert result["observations_created"] == 1
    return rows


def test_target_execution_deducts_spread_slippage_and_fees(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path)
    future = rows + [candle(100, open_=100.0, high=101.5, low=99.5, close=101.0)]
    result = execution.advance_paper_executions("BTCUSDT", "1h", future)
    items = execution.list_execution_simulations("BTCUSDT", "1h")
    trade = items[0]

    assert result["settled"] == 1
    assert trade["status"] == "SETTLED"
    assert trade["exit_reason"] == "TARGET"
    assert trade["entry_reference_price"] == 100.0
    assert trade["exit_reference_price"] == 101.0
    assert trade["entry_fill_price"] > trade["entry_reference_price"]
    assert trade["exit_fill_price"] < trade["exit_reference_price"]
    assert trade["gross_pnl_quote"] > trade["net_pnl_quote"] > 0
    assert trade["spread_cost_quote"] > 0
    assert trade["slippage_cost_quote"] > 0
    assert trade["fee_cost_quote"] > 0
    assert trade["assumptions"]["fee_bps_per_side"] == 10.0
    assert trade["position_notional_quote"] == 1000.0


def test_stop_gap_uses_worse_opening_price(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path, horizon=2)
    future = rows + [
        candle(100, open_=100.0, high=100.2, low=99.5, close=100.0),
        candle(101, open_=97.0, high=98.0, low=96.0, close=97.5),
    ]
    execution.advance_paper_executions("BTCUSDT", "1h", future)
    trade = execution.list_execution_simulations("BTCUSDT", "1h")[0]
    assert trade["exit_reason"] == "STOP"
    assert trade["exit_reference_price"] == 97.0
    assert trade["exit_fill_price"] < 97.0
    assert trade["net_pnl_quote"] < -30.0


def test_stop_wins_when_both_stop_and_target_touch_same_bar(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path)
    future = rows + [candle(100, open_=100.0, high=102.0, low=98.0, close=100.0)]
    execution.advance_paper_executions("BTCUSDT", "1h", future)
    trade = execution.list_execution_simulations("BTCUSDT", "1h")[0]
    assert trade["exit_reason"] == "STOP"


def test_entry_delay_skips_configured_number_of_additional_bars(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path, delay=1, horizon=1)
    future = rows + [
        candle(100, open_=100.0, high=102.0, low=99.5, close=101.0),
        candle(101, open_=102.0, high=103.0, low=101.5, close=102.5),
    ]
    execution.advance_paper_executions("BTCUSDT", "1h", future)
    trade = execution.list_execution_simulations("BTCUSDT", "1h")[0]
    assert trade["entry_reference_time"] == future[101]["time"]
    assert trade["entry_reference_price"] == 102.0


def test_timeout_is_settled_and_cost_adjusted(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path, horizon=2)
    future = rows + [
        candle(100, open_=100.0, high=100.2, low=99.5, close=100.0),
        candle(101, open_=100.0, high=100.2, low=99.5, close=100.1),
    ]
    execution.advance_paper_executions("BTCUSDT", "1h", future)
    trade = execution.list_execution_simulations("BTCUSDT", "1h")[0]
    assert trade["status"] == "SETTLED"
    assert trade["exit_reason"] == "TIMEOUT"
    assert trade["exit_reference_price"] == 100.1
    assert trade["net_pnl_quote"] < trade["gross_pnl_quote"]


def test_performance_summary_discloses_costs_and_scope(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path)
    future = rows + [candle(100, open_=100.0, high=101.5, low=99.5, close=101.0)]
    execution.advance_paper_executions("BTCUSDT", "1h", future)
    summary = execution.execution_summary("BTCUSDT", "1h")
    assert summary["overall"]["trades"] == 1
    assert summary["overall"]["total_cost_quote"] > 0
    assert summary["by_status"]["SETTLED"] == 1
    assert "Short results are synthetic" in summary["notice"]
    assert summary["orders_submitted"] is False


def test_deterministic_entry_rejection_stress_can_exclude_entry(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path, rejection=100.0)
    future = rows + [candle(100, open_=100.0, high=101.5, low=99.5, close=101.0)]
    execution.advance_paper_executions("BTCUSDT", "1h", future)
    trade = execution.list_execution_simulations("BTCUSDT", "1h")[0]
    assert trade["status"] == "ENTRY_REJECTED"
    assert trade["net_pnl_quote"] is None


def test_entry_rejection_stress_is_repeatable_for_same_id_and_seed(monkeypatch, tmp_path):
    rows = make_observation(monkeypatch, tmp_path)
    assumptions = execution.execution_assumptions()
    assumptions["entry_rejection_rate_pct"] = 50.0
    first = execution._entry_rejected(9876, assumptions)
    second = execution._entry_rejected(9876, assumptions)
    assert first is second


def test_demo_sample_observations_are_blocked_from_execution(monkeypatch, tmp_path):
    monkeypatch.setattr(candle_store, "DB_PATH", tmp_path / "paper-demo-block.db")
    rows = [candle(i) for i in range(100)]
    configure_latest_event(monkeypatch, rows)
    result = paper.record_latest_structure_observations(
        "BTCUSDT", "1h", rows, data_source="Demo sample feed",
    )
    assert result["observations_created"] == 1
    execution_result = execution.advance_paper_executions("BTCUSDT", "1h", rows)
    trade = execution.list_execution_simulations("BTCUSDT", "1h")[0]
    assert trade["status"] == "BLOCKED_NON_BINANCE"
    assert execution_result["settled"] == 0
