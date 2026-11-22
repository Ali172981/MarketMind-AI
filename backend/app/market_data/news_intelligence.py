"""Public RSS news ingestion and transparent rule-based event tagging.

Only allowlisted public RSS feeds are fetched. Headlines are deduplicated by
normalized title hash; source publication time is preserved separately from
our ingestion time. Classification is heuristic metadata, never a trade signal.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.market_data.candle_store import DB_PATH

FEEDS = (
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "kind": "crypto"},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "kind": "crypto"},
    {"name": "Federal Reserve", "url": "https://www.federalreserve.gov/feeds/press_all.xml", "kind": "macro"},
)

KEYWORDS: dict[str, tuple[str, ...]] = {
    "MONETARY_POLICY": ("federal reserve", "fed rate", "interest rate", "rate cut", "rate hike", "fomc", "monetary policy", "central bank"),
    "INFLATION": ("inflation", "consumer price index", "cpi", "producer price index", "ppi"),
    "EMPLOYMENT": ("employment", "nonfarm payroll", "unemployment", "jobs report", "jobless claims"),
    "REGULATION": ("regulation", "regulator", "sec", "lawsuit", "legal action", "ban", "approval", "etf"),
    "CRYPTO_MARKET": ("bitcoin", "ethereum", "crypto", "cryptocurrency", "digital asset", "blockchain"),
    "GEOPOLITICS": ("war", "sanction", "geopolitical", "military", "conflict", "tariff"),
    "GOLD_MARKET": ("gold", "bullion", "precious metal", "central bank gold"),
    "SILVER_MARKET": ("silver", "industrial metal"),
    "FINANCIAL_STABILITY": ("bank failure", "banking crisis", "liquidity crisis", "default", "debt ceiling", "systemic risk"),
}
ASSET_TERMS = {
    "BTCUSDT": ("bitcoin", "btc", "crypto", "cryptocurrency", "digital asset"),
    "ETHUSDT": ("ethereum", "ether", "eth"),
    "SOLUSDT": ("solana", "sol"),
    "XAUUSD": ("gold", "bullion", "precious metal"),
    "XAGUSD": ("silver", "industrial metal"),
}

_feed_status: dict[str, dict[str, Any]] = {}
_last_refresh: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            return None


def _text(parent: ET.Element, names: tuple[str, ...]) -> str:
    for node in parent.iter():
        tag = node.tag.rsplit("}", 1)[-1].lower()
        if tag in names and node.text:
            return re.sub(r"\s+", " ", node.text).strip()
    return ""


def parse_feed(xml: str, source_name: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml)
    entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    parsed: list[dict[str, Any]] = []
    for entry in entries:
        title = _text(entry, ("title",))
        if not title:
            continue
        link = ""
        for node in entry.iter():
            if node.tag.rsplit("}", 1)[-1].lower() == "link":
                link = node.attrib.get("href") or (node.text or "").strip()
                if link:
                    break
        summary = _text(entry, ("description", "summary", "content"))
        summary = re.sub(r"<[^>]+>", " ", summary)
        summary = re.sub(r"\s+", " ", summary).strip()[:1200]
        published_raw = _text(entry, ("pubdate", "published", "updated", "date"))
        published = _published(published_raw)
        normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        parsed.append({
            "id": digest[:20], "dedupe_hash": digest, "headline": title[:500],
            "summary": summary, "source_name": source_name,
            "source_url": _clean_url(link) if link.startswith(("http://", "https://")) else None,
            "published_at": published, "published_at_raw": published_raw or None,
        })
    return parsed


def _has_term(text: str, term: str) -> bool:
    if len(term) <= 4 and term.isalnum():
        return re.search(rf"\b{re.escape(term)}\b", text) is not None
    return term in text


def classify_event(headline: str, summary: str = "") -> dict[str, Any]:
    text = f"{headline} {summary}".lower()
    matched = [category for category, terms in KEYWORDS.items() if any(_has_term(text, term) for term in terms)]
    assets = [symbol for symbol, terms in ASSET_TERMS.items() if any(_has_term(text, term) for term in terms)]
    if "MONETARY_POLICY" in matched or "INFLATION" in matched or "EMPLOYMENT" in matched:
        assets.extend(["XAUUSD", "XAGUSD", "BTCUSDT"])
    if "GEOPOLITICS" in matched:
        assets.extend(["XAUUSD", "XAGUSD", "BTCUSDT"])
    assets = list(dict.fromkeys(assets))
    # Importance is an editorial heuristic, not an estimate of price direction or magnitude.
    high = {"MONETARY_POLICY", "INFLATION", "REGULATION", "FINANCIAL_STABILITY", "GEOPOLITICS"}
    importance = "HIGH_REVIEW" if high.intersection(matched) else ("REVIEW" if matched else "UNCLASSIFIED")
    return {
        "event_categories": matched or ["UNCLASSIFIED"],
        "assets": assets,
        "importance": importance,
        "directional_bias": "UNASSESSED",
        "classification_method": "KEYWORD_RULES_V1",
    }


def init_news_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("""CREATE TABLE IF NOT EXISTS news_items (
            id TEXT PRIMARY KEY, dedupe_hash TEXT NOT NULL UNIQUE, headline TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL, source_url TEXT,
            published_at TEXT, published_at_raw TEXT, ingested_at TEXT NOT NULL,
            event_categories TEXT NOT NULL, assets TEXT NOT NULL, importance TEXT NOT NULL,
            directional_bias TEXT NOT NULL, classification_method TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at DESC)")


def store_items(items: list[dict[str, Any]]) -> int:
    import json
    init_news_db()
    inserted = 0
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        for item in items:
            tags = classify_event(item["headline"], item.get("summary", ""))
            result = conn.execute("""INSERT OR IGNORE INTO news_items
                (id,dedupe_hash,headline,summary,source_name,source_url,published_at,published_at_raw,ingested_at,event_categories,assets,importance,directional_bias,classification_method)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                item["id"], item["dedupe_hash"], item["headline"], item.get("summary", ""),
                item["source_name"], item.get("source_url"), item.get("published_at"), item.get("published_at_raw"), _now(),
                json.dumps(tags["event_categories"]), json.dumps(tags["assets"]), tags["importance"],
                tags["directional_bias"], tags["classification_method"],
            ))
            inserted += max(0, result.rowcount)
    return inserted


def list_items(limit: int = 50, asset: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
    import json
    init_news_db()
    sql = "SELECT * FROM news_items"
    clauses: list[str] = []
    params: list[Any] = []
    if asset:
        clauses.append("assets LIKE ?")
        params.append(f'%"{asset.upper()}"%')
    if category:
        clauses.append("event_categories LIKE ?")
        params.append(f'%"{category.upper()}"%')
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY COALESCE(published_at, ingested_at) DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        item["event_categories"] = json.loads(item.pop("event_categories"))
        item["assets"] = json.loads(item.pop("assets"))
        item["verification"] = "SOURCE_RSS_UNVERIFIED"
        item["data_status"] = "PUBLIC_RSS"
        output.append(item)
    return output


async def refresh_news(client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    global _last_refresh
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=12.0, follow_redirects=True, headers={"User-Agent": "MarketMindAI/0.15 (+public RSS research client)"})
    assert client is not None
    total = inserted = 0
    try:
        for feed in FEEDS:
            started = time.monotonic()
            try:
                response = await client.get(feed["url"])
                response.raise_for_status()
                items = parse_feed(response.text, feed["name"])
                # Bound per-cycle ingestion; feed order is normally newest-first.
                items = items[:100]
                inserted_feed = store_items(items)
                total += len(items)
                inserted += inserted_feed
                _feed_status[feed["name"]] = {"status": "ok", "items_seen": len(items), "new_items": inserted_feed, "latency_ms": round((time.monotonic()-started)*1000), "checked_at": _now()}
            except Exception as exc:
                _feed_status[feed["name"]] = {"status": "error", "error": str(exc)[:240], "checked_at": _now()}
        _last_refresh = _now()
    finally:
        if own_client:
            await client.aclose()
    return {"status": "ok" if any(v.get("status") == "ok" for v in _feed_status.values()) else "unavailable", "items_seen": total, "new_items": inserted, "feeds": _feed_status, "last_refresh": _last_refresh}


def news_status() -> dict[str, Any]:
    return {"status": "configured" if _feed_status else "not_started", "last_refresh": _last_refresh, "feeds": _feed_status, "classification": "heuristic_only_no_directional_signal"}


async def news_worker(interval_seconds: int = 300) -> None:
    while True:
        await refresh_news()
        await asyncio.sleep(max(60, interval_seconds))


def market_reaction(news_id: str, symbol: str, interval: str = "1h", window_bars: int = 24) -> dict[str, Any]:
    """Descriptive pre/post close-to-close returns around publication time.

    Uses only stored closed candles and never attributes causality to the story.
    """
    allowed_symbols = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "XAGUSD"}
    allowed_intervals = {"15m", "1h", "4h", "1d"}
    if symbol not in allowed_symbols or interval not in allowed_intervals:
        return {"status": "unsupported_instrument_or_interval"}
    init_news_db()
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT published_at FROM news_items WHERE id=?", (news_id,)).fetchone()
    if not row or not row["published_at"]:
        return {"status": "publication_timestamp_unavailable" if row else "news_item_not_found"}
    try:
        published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    except ValueError:
        return {"status": "publication_timestamp_unavailable"}
    seconds = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}[interval]
    event_ms = int(published.timestamp() * 1000)
    start_ms = event_ms - (window_bars + 2) * seconds * 1000
    end_ms = event_ms + (window_bars + 2) * seconds * 1000
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""SELECT open_time, close_time, close, source FROM candles
            WHERE symbol=? AND interval=? AND is_closed=1 AND open_time BETWEEN ? AND ?
            ORDER BY close_time ASC""", (symbol, interval, start_ms, end_ms)).fetchall()
    before = [r for r in rows if int(r["close_time"]) <= event_ms]
    after = [r for r in rows if int(r["close_time"]) > event_ms]
    if len(before) < 2 or len(after) < 2:
        return {"status": "insufficient_candle_history", "symbol": symbol, "interval": interval, "available_before": len(before), "available_after": len(after)}
    pre_slice = before[-min(window_bars + 1, len(before)):]
    post_slice = after[:min(window_bars + 1, len(after))]
    pre_return = (float(pre_slice[-1]["close"]) / float(pre_slice[0]["close"]) - 1) * 100
    post_return = (float(post_slice[-1]["close"]) / float(post_slice[0]["close"]) - 1) * 100
    return {
        "status": "descriptive_only", "news_id": news_id, "symbol": symbol, "interval": interval,
        "published_at": published.astimezone(timezone.utc).isoformat(), "window_bars": window_bars,
        "pre_event_return_pct": round(pre_return, 6), "post_event_return_pct": round(post_return, 6),
        "pre_event_bars": len(pre_slice), "post_event_bars": len(post_slice),
        "candle_sources": sorted({str(r["source"]) for r in rows}),
        "warning": "Temporal association only. This is not causal attribution, event alpha, or a trading signal.",
    }
