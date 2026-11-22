from fastapi import APIRouter, Query
from app.market_data.news_intelligence import list_items, market_reaction, news_status, refresh_news

router = APIRouter(prefix="/news", tags=["news intelligence"])


@router.get("")
async def list_news(limit: int = Query(50, ge=1, le=200), asset: str | None = None, category: str | None = None):
    items = list_items(limit=limit, asset=asset, category=category)
    return {
        "data_status": "PUBLIC_RSS" if items else "NO_STORED_NEWS",
        "notice": "Public RSS headlines with source timestamps. Rule-based tags are review aids, not verified event interpretations or trading signals.",
        "items": items,
        "feed_status": news_status(),
    }


@router.get("/status")
async def get_news_status():
    return news_status()


@router.post("/refresh")
async def manual_refresh():
    return await refresh_news()


@router.get("/{news_id}/market-reaction")
async def get_market_reaction(news_id: str, symbol: str = "BTCUSDT", interval: str = "1h", window_bars: int = Query(24, ge=2, le=100)):
    return market_reaction(news_id, symbol.upper(), interval, window_bars)
