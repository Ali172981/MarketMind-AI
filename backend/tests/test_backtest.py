from app.analysis import backtest as bt


def make_rows(n=100):
    rows = []
    for i in range(n):
        base = 100.0
        rows.append({
            "time": i * 60, "open": base, "high": base + 1.0,
            "low": base - 1.0, "close": base + (0.1 if i % 2 else -0.1),
            "volume": 10.0, "is_closed": True,
        })
    return rows


def test_backtest_enters_next_open_and_takes_target(monkeypatch):
    rows = make_rows()
    # Force a known confirmed bullish structure break at candle 70.
    monkeypatch.setattr(bt, "_pivot_points", lambda candles, left, right: ([], []))
    monkeypatch.setattr(bt, "_structure_events", lambda candles, highs, lows: ([{
        "type": "BULLISH_BOS", "direction": "BULLISH", "time": rows[70]["time"],
    }], "BULLISH"))
    rows[71]["open"] = 100.0
    rows[72]["high"] = 110.0
    rows[72]["low"] = 99.0
    result = bt.run_smc_backtest(rows, atr_stop_multiple=1.0, reward_risk=1.0,
                                 fee_bps=0.0, slippage_bps=0.0, max_holding_bars=5)
    assert result["status"] == "OK"
    assert result["metrics"]["trades"] == 1
    trade = result["trades"][0]
    assert trade["entry_time"] == rows[71]["time"]
    assert trade["exit_reason"] == "TARGET"
    assert trade["net_pnl"] > 0


def test_backtest_stop_wins_if_stop_and_target_hit_same_bar(monkeypatch):
    rows = make_rows()
    monkeypatch.setattr(bt, "_pivot_points", lambda candles, left, right: ([], []))
    monkeypatch.setattr(bt, "_structure_events", lambda candles, highs, lows: ([{
        "type": "BULLISH_BOS", "direction": "BULLISH", "time": rows[70]["time"],
    }], "BULLISH"))
    rows[71]["open"] = 100.0
    rows[72]["high"] = 110.0
    rows[72]["low"] = 90.0
    result = bt.run_smc_backtest(rows, atr_stop_multiple=1.0, reward_risk=1.0,
                                 fee_bps=0.0, slippage_bps=0.0, max_holding_bars=5)
    assert result["trades"][0]["exit_reason"] == "STOP"
    assert result["trades"][0]["net_pnl"] < 0


def test_unclosed_candles_are_excluded():
    rows = make_rows()
    rows[-1]["is_closed"] = False
    monkeypatch = None
    result = bt.run_smc_backtest(rows)
    assert result["candles_analyzed"] == 99


def test_insufficient_history_returns_clear_status():
    result = bt.run_smc_backtest(make_rows(20))
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["metrics"] is None


def test_backtest_api_returns_simulation(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    import app.api.routes.backtest as route

    rows = make_rows(120)
    async def fake_get_ohlcv(symbol, interval, limit):
        return {"items": rows, "data_status": "HISTORICAL", "source": "test fixture", "fetched_at": "now"}

    monkeypatch.setattr(route, "get_ohlcv", fake_get_ohlcv)
    monkeypatch.setattr(route, "run_smc_backtest", lambda candles, **kwargs: {
        "status": "OK", "metrics": {"trades": 0}, "trades": [],
    })
    with TestClient(app) as client:
        response = client.get("/api/v1/market/backtest/smc?symbol=BTCUSDT&interval=1h&limit=120")
    assert response.status_code == 200
    assert response.json()["backtest"]["status"] == "OK"


def test_backtest_rejects_unsupported_market():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        response = client.get("/api/v1/market/backtest/smc?symbol=XAUUSD&interval=1h")
    assert response.status_code == 400
