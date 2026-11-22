from app.analysis.strategy import analyze_strategy


def candles_trending(count=120, step=1.0):
    rows = []
    price = 100.0
    for i in range(count):
        open_price = price
        price += step
        rows.append({
            "time": i * 3600,
            "open": open_price,
            "high": price + 0.4,
            "low": open_price - 0.2,
            "close": price,
            "volume": 100 + (50 if i == count - 1 else 0),
            "is_closed": True,
        })
    return rows


def test_strategy_requires_sufficient_closed_candles():
    result = analyze_strategy("BTCUSDT", [{"interval": "1h", "candles": candles_trending(40)}])
    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["validated_probability"] is None


def test_strategy_scores_are_bounded_and_probability_never_published():
    rows = candles_trending()
    result = analyze_strategy("BTCUSDT", [{"interval": "1h", "candles": rows, "source": "test", "data_status": "HISTORICAL"}])
    assert 0 <= result["long_score"] <= 100
    assert 0 <= result["short_score"] <= 100
    assert result["validated_probability"] is None
    assert result["score_definition"].startswith("Bounded rule-confluence")
    assert result["data_sources"][0]["candles"] == 120


def test_strategy_ignores_unclosed_candles():
    rows = candles_trending()
    rows[-1]["is_closed"] = False
    result = analyze_strategy("BTCUSDT", [{"interval": "1h", "candles": rows}])
    assert result["data_sources"][0]["candles"] == 119


def test_strategy_news_is_context_not_directional_score():
    rows = candles_trending()
    news = [{"headline": "Bitcoin rises", "source_name": "Test RSS", "event_categories": ["CRYPTO_MARKET"], "directional_bias": "BULLISH"}]
    baseline = analyze_strategy("BTCUSDT", [{"interval": "1h", "candles": rows}])
    with_news = analyze_strategy("BTCUSDT", [{"interval": "1h", "candles": rows}], news)
    assert baseline["long_score"] == with_news["long_score"]
    assert baseline["short_score"] == with_news["short_score"]
    assert with_news["news_context"]["relevant_headlines"] == 1


def test_strategy_multi_timeframe_is_descriptive_and_included():
    result = analyze_strategy("BTCUSDT", [
        {"interval": "1h", "candles": candles_trending()},
        {"interval": "4h", "candles": candles_trending(step=0.5)},
    ])
    assert len(result["multi_timeframe"]) == 1
    assert result["multi_timeframe"][0]["interval"] == "4h"
    assert result["validated_probability"] is None
