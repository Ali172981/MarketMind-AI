from app.analysis.paper_portfolio import simulate_portfolio


def config(**overrides):
    values = {
        "initial_capital_quote": 10_000.0,
        "risk_per_trade_pct": 1.0,
        "max_open_risk_pct": 3.0,
        "max_gross_exposure_pct": 100.0,
        "max_position_exposure_pct": 25.0,
        "max_concurrent_positions": 3,
    }
    values.update(overrides)
    return values


def trade(trade_id, entry, exit_, pnl_pct, *, status="SETTLED", symbol="BTCUSDT", stop=99.0):
    row = {
        "id": trade_id,
        "symbol": symbol,
        "interval": "1h",
        "direction": "LONG",
        "status": status,
        "entry_reference_time": entry,
        "entry_reference_price": 100.0,
        "stop_price": stop,
        "data_source": "Binance Spot",
    }
    if status == "SETTLED":
        row.update({"exit_time": exit_, "net_return_pct": pnl_pct})
    return row


def test_single_trade_is_risk_sized_and_net_return_scales_to_portfolio():
    result = simulate_portfolio([trade(1, 100, 200, 10.0)], config())
    assert result["accepted_settled_trades"] == 1
    assert result["ending_realized_equity_quote"] == 10_250.0
    assert result["net_realized_pnl_quote"] == 250.0
    assert result["max_realized_drawdown_quote"] == 0.0
    assert result["orders_submitted"] is False


def test_overlapping_position_limit_rejects_second_trade():
    rows = [trade(1, 100, 300, 10.0), trade(2, 200, 250, 20.0, symbol="ETHUSDT")]
    result = simulate_portfolio(rows, config(max_concurrent_positions=1))
    assert result["accepted_settled_trades"] == 1
    assert result["rejected_by_reason"]["MAX_CONCURRENT_POSITIONS"] == 1


def test_same_timestamp_entries_share_gross_exposure_pro_rata():
    rows = [trade(1, 100, 200, 10.0), trade(2, 100, 200, 10.0, symbol="ETHUSDT")]
    result = simulate_portfolio(rows, config(max_gross_exposure_pct=10.0))
    accepted = [item for item in result["trades"] if item["status"] == "SETTLED"]
    assert len(accepted) == 2
    assert all(item["allocated_notional_quote"] == 500.0 for item in accepted)
    assert result["peak_gross_exposure_pct_of_equity"] == 10.0


def test_open_risk_cap_is_shared_pro_rata_between_simultaneous_entries():
    rows = [trade(1, 100, 200, 10.0, stop=95.0), trade(2, 100, 200, 10.0, symbol="ETHUSDT", stop=95.0)]
    result = simulate_portfolio(rows, config(
        max_open_risk_pct=1.5,
    ))
    accepted = [item for item in result["trades"] if item["status"] == "SETTLED"]
    assert len(accepted) == 2
    assert all(item["allocated_risk_quote"] == 75.0 for item in accepted)
    assert result["peak_open_stop_risk_pct_of_equity"] == 1.5


def test_open_position_reserves_capacity_and_is_not_counted_as_realized_trade():
    rows = [trade(1, 100, None, 0.0, status="OPEN"), trade(2, 200, 300, 10.0, symbol="ETHUSDT")]
    result = simulate_portfolio(rows, config(max_concurrent_positions=1))
    assert result["accepted_open_positions"] == 1
    assert result["current_open_positions"] == 1
    assert result["accepted_settled_trades"] == 0
    assert result["rejected_by_reason"]["MAX_CONCURRENT_POSITIONS"] == 1


def test_same_timestamp_exit_does_not_free_capacity_before_new_entry():
    rows = [trade(1, 100, 200, 0.0), trade(2, 200, 300, 10.0, symbol="ETHUSDT")]
    result = simulate_portfolio(rows, config(max_concurrent_positions=1))
    assert result["accepted_settled_trades"] == 1
    assert result["rejected_by_reason"]["MAX_CONCURRENT_POSITIONS"] == 1


def test_realized_equity_drawdown_uses_compounded_risk_sized_allocations():
    rows = [trade(1, 100, 200, 10.0), trade(2, 300, 400, -20.0)]
    result = simulate_portfolio(rows, config())
    assert result["ending_realized_equity_quote"] == 9737.5
    assert result["max_realized_drawdown_quote"] == 512.5
    assert round(result["max_realized_drawdown_pct"], 4) == 5.0


def test_invalid_execution_is_excluded_not_silently_counted():
    result = simulate_portfolio([{"id": 1, "status": "SETTLED"}], config())
    assert result["accepted_settled_trades"] == 0
    assert result["excluded_by_status_or_data"]["INVALID_OR_INCOMPLETE_EXECUTION"] == 1


def test_nonsettled_blocked_execution_status_is_disclosed():
    result = simulate_portfolio([{"id": 1, "status": "BLOCKED_NON_BINANCE"}], config())
    assert result["input_settled_or_open_trades"] == 0
    assert result["excluded_by_status_or_data"]["BLOCKED_NON_BINANCE"] == 1


def test_non_binance_settled_execution_is_excluded_from_portfolio():
    row = trade(1, 100, 200, 10.0)
    row["data_source"] = "Demo sample feed"
    result = simulate_portfolio([row], config())
    assert result["accepted_settled_trades"] == 0
    assert result["excluded_by_status_or_data"]["NON_BINANCE_SOURCE"] == 1
