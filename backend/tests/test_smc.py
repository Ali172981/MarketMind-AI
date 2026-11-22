from app.analysis.smc import _fvg, _pivot_points, analyze_smc


def candle(i, o, h, l, c, closed=True):
    return {"time": i * 60, "open": o, "high": h, "low": l, "close": c,
            "volume": 10.0, "is_closed": closed}


def test_insufficient_closed_candles_are_reported():
    rows = [candle(i, 10, 11, 9, 10) for i in range(10)]
    result = analyze_smc(rows)
    assert result["status"] == "INSUFFICIENT_DATA"


def test_unclosed_candles_are_excluded_from_analysis():
    rows = [candle(i, 10 + i * .01, 11 + i * .01, 9 + i * .01, 10.5 + i * .01) for i in range(30)]
    rows[-1]["is_closed"] = False
    result = analyze_smc(rows)
    assert result["status"] == "OK"
    assert result["candles_analyzed"] == 29
    assert result["latest_closed_candle_time"] == rows[-2]["time"]


def test_fvg_detects_three_candle_imbalance():
    rows = [
        candle(0, 10, 11, 9, 10),
        candle(1, 12, 14, 12, 13),
        candle(2, 13, 15, 12, 14),
    ]
    zones = _fvg(rows)
    assert zones
    assert zones[0]["type"] == "BULLISH_FVG"
    assert zones[0]["lower"] == 11
    assert zones[0]["upper"] == 12


def test_pivot_is_confirmed_after_right_hand_bars():
    rows = [
        candle(0, 9, 10, 8, 9),
        candle(1, 10, 12, 9, 11),
        candle(2, 11, 15, 10, 12),
        candle(3, 12, 13, 10, 11),
        candle(4, 11, 12, 9, 10),
        candle(5, 10, 11, 9, 10),
    ]
    highs, _ = _pivot_points(rows, left=2, right=2)
    pivot = next(p for p in highs if p["index"] == 2)
    assert pivot["confirmed_at_index"] == 4


def test_analysis_returns_expected_sections():
    rows = []
    for i in range(80):
        center = 100 + (i % 12) * 0.8 + (i // 12) * 0.2
        rows.append(candle(i, center, center + 1.1, center - 1.0, center + (0.25 if i % 2 else -0.2)))
    result = analyze_smc(rows)
    assert result["status"] == "OK"
    assert "structure" in result
    assert "liquidity" in result
    assert "fair_value_gaps" in result
    assert "order_blocks" in result
    assert "disclaimer" in result


def test_smc_api_returns_analysis_from_candle_provider(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    import app.api.routes.smc as smc_route

    rows = [candle(i, 100 + i * .1, 101 + i * .1, 99 + i * .1, 100.5 + i * .1) for i in range(80)]

    async def fake_get_ohlcv(symbol, interval, limit):
        return {"items": rows, "data_status": "HISTORICAL", "source": "test fixture"}

    monkeypatch.setattr(smc_route, "get_ohlcv", fake_get_ohlcv)
    # Lifespan market pollers are unrelated to this route unit test; avoid
    # starting external-provider background tasks for an in-memory fixture.
    client = TestClient(app)
    response = client.get("/api/v1/market/smc?symbol=BTCUSDT&interval=1h&limit=80")
    assert response.status_code == 200
    body = response.json()
    assert body["analysis"]["status"] == "OK"
    assert body["source"] == "test fixture"
