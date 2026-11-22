import asyncio
import sqlite3
import asyncio

from app.market_data import news_intelligence as news

RSS = '''<?xml version="1.0"?><rss version="2.0"><channel><item>
<title>Federal Reserve signals interest rate decision as Bitcoin rises</title>
<link>https://example.org/story?utm_source=rss</link>
<description>Policy update and crypto market context.</description>
<pubDate>Sat, 21 Nov 2026 12:30:00 GMT</pubDate>
</item></channel></rss>'''


def test_parse_feed_preserves_source_and_timestamp():
    items = news.parse_feed(RSS, "Test Wire")
    assert len(items) == 1
    assert items[0]["source_name"] == "Test Wire"
    assert items[0]["published_at"].startswith("2026-11-21T12:30:00")
    assert "utm_source" not in items[0]["source_url"]


def test_parse_atom_feed():
    atom = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Gold price outlook</title>
    <link href="https://example.org/gold"/><updated>2026-11-21T10:00:00Z</updated><summary>Gold bullion</summary></entry></feed>'''
    item = news.parse_feed(atom, "Atom Source")[0]
    assert item["headline"] == "Gold price outlook"
    assert item["source_url"] == "https://example.org/gold"
    assert item["published_at"].startswith("2026-11-21T10:00:00")


def test_rule_classifier_is_non_directional():
    result = news.classify_event("Federal Reserve inflation update and Bitcoin ETF news")
    assert "MONETARY_POLICY" in result["event_categories"]
    assert "INFLATION" in result["event_categories"]
    assert "BTCUSDT" in result["assets"]
    assert "XAUUSD" in result["assets"]
    assert result["directional_bias"] == "UNASSESSED"
    assert result["classification_method"] == "KEYWORD_RULES_V1"


def test_store_deduplicates_and_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "DB_PATH", tmp_path / "news.db")
    item = news.parse_feed(RSS, "Test Wire")[0]
    assert news.store_items([item]) == 1
    assert news.store_items([item]) == 0
    rows = news.list_items(asset="BTCUSDT")
    assert len(rows) == 1
    assert rows[0]["verification"] == "SOURCE_RSS_UNVERIFIED"
    assert news.list_items(asset="SOLUSDT") == []


def test_unclassified_event_does_not_invent_assets():
    result = news.classify_event("A local art exhibition opens")
    assert result["event_categories"] == ["UNCLASSIFIED"]
    assert result["assets"] == []
    assert result["importance"] == "UNCLASSIFIED"


def test_market_reaction_is_descriptive_and_uses_closed_candles(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "DB_PATH", tmp_path / "events.db")
    item = news.parse_feed(RSS, "Test Wire")[0]
    news.store_items([item])
    with sqlite3.connect(news.DB_PATH) as conn:
        conn.execute("""CREATE TABLE candles (
            symbol TEXT, interval TEXT, open_time INTEGER, close_time INTEGER,
            close REAL, source TEXT, is_closed INTEGER
        )""")
        base = 1795255200000  # 2026-11-21 10:00 UTC
        for index, close in enumerate([100, 101, 102, 103, 104, 105]):
            conn.execute("INSERT INTO candles VALUES (?,?,?,?,?,?,1)", ("BTCUSDT", "1h", base + index * 3600000, base + index * 3600000 + 3599999, close, "Binance"))
    result = news.market_reaction(item["id"], "BTCUSDT", "1h", 2)
    assert result["status"] == "descriptive_only"
    assert result["pre_event_bars"] == 2
    assert result["post_event_bars"] == 3
    assert "not causal attribution" in result["warning"]


def test_ticker_matching_uses_word_boundaries():
    result = news.classify_event("A method for solving a local problem")
    assert "ETHUSDT" not in result["assets"]
    assert "SOLUSDT" not in result["assets"]


def test_refresh_reports_feed_failure_without_crashing(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(news, "DB_PATH", tmp_path / "refresh.db")
    monkeypatch.setattr(news, "FEEDS", (
        {"name": "Good", "url": "https://good.test/rss", "kind": "crypto"},
        {"name": "Bad", "url": "https://bad.test/rss", "kind": "crypto"},
    ))

    async def handler(request):
        if request.url.host == "bad.test":
            return httpx.Response(503, request=request)
        return httpx.Response(200, text=RSS, request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await news.refresh_news(client)

    result = asyncio.run(run())
    assert result["feeds"]["Good"]["status"] == "ok"
    assert result["feeds"]["Bad"]["status"] == "error"
    assert result["new_items"] == 1
