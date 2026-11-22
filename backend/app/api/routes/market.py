from fastapi import APIRouter, HTTPException, Query
from app.market_data.demo_provider import get_quotes
from app.market_data.binance_provider import get_live_quotes, get_feed_status
from app.market_data.xaus_provider import get_metals_quotes, get_metals_status
from app.market_data.alltick_provider import get_quotes as get_alltick_quotes, get_status as get_alltick_status
from app.market_data.alltick_websocket import get_quotes as get_alltick_ws_quotes, get_orderbooks as get_alltick_orderbooks, get_status as get_alltick_ws_status
from app.core.config import settings

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/prices")
async def prices(symbol: str | None = Query(default=None, description="Optional symbol, e.g. BTCUSDT or XAUUSD")):
    mode = settings.data_mode.lower()
    if mode == "binance":
        quotes = get_live_quotes() + get_metals_quotes()
        present = {q["symbol"] for q in quotes}
        for sym, label in (("XAUUSD", "XAUS"), ("XAGUSD", "XAUS")):
            if sym not in present:
                quotes.append({"symbol": sym, "price": 0, "change_percent_24h": None, "source": label + " (not connected)", "data_status": "UNAVAILABLE", "timestamp": None})
        live_crypto = get_live_quotes()
        live_symbols = {q["symbol"] for q in live_crypto}
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            if sym not in live_symbols:
                quotes.append({"symbol": sym, "price": 0, "change_percent_24h": None, "source": "Binance Spot WebSocket (connecting)", "data_status": "CONNECTING", "timestamp": None})
        statuses = {"binance": get_feed_status(), "metals": get_metals_status()}
        notice = "Crypto uses Binance Spot streams. Gold and silver use free XAUS indicative spot quotes (about 60-second upstream cache)."
    elif mode == "alltick":
        ws_status = get_alltick_ws_status()
        ws_quotes = get_alltick_ws_quotes()
        quotes = ws_quotes if ws_status.get("enabled") else get_alltick_quotes()
        present = {q["symbol"] for q in quotes}
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "XAGUSD"):
            if sym not in present:
                quotes.append({"symbol": sym, "price": 0, "change_percent_24h": None, "source": "AllTick (not yet available)", "data_status": "CONNECTING" if get_alltick_status()["configured"] else "CONFIGURATION_REQUIRED", "timestamp": None})
        statuses = {"alltick_rest": get_alltick_status(), "alltick_websocket": ws_status}
        notice = "AllTick WebSocket trade ticks when enabled; otherwise REST latest-trade quotes. Gold maps to GOLD and silver to Silver. Verify product entitlements and timestamps against your account."
    else:
        quotes = [q.model_dump() for q in get_quotes()]
        statuses = {"binance": {"status": "DISABLED"}, "metals": get_metals_status()}
        notice = "Demo quotes are illustrative and must not be treated as live market data."

    if symbol:
        quotes = [q for q in quotes if q["symbol"].upper() == symbol.upper()]
        if not quotes:
            raise HTTPException(status_code=404, detail=f"No quote available for symbol: {symbol}")
    live_count = sum(1 for q in quotes if q.get("data_status") == "LIVE")
    if live_count:
        status = "LIVE_PARTIAL"
    elif mode == "demo":
        status = "DEMO"
    elif mode == "alltick" and not get_alltick_status()["configured"]:
        status = "CONFIGURATION_REQUIRED"
    else:
        status = "CONNECTING"
    return {"data_status": status, "notice": notice, "feeds": statuses, "items": quotes}


@router.get("/stream")
async def stream_status():
    """Provider stream health and optional order-book snapshots."""
    from app.market_data.alltick_websocket import get_status as ws_status, get_orderbooks
    return {"stream": ws_status(), "orderbooks": get_orderbooks()}


@router.get("/data-quality")
async def data_quality():
    """Cross-provider price validation summary; comparisons are diagnostic only."""
    from app.market_data.data_quality import quality_summary
    from app.core.config import settings as cfg
    return {
        "enabled": cfg.data_quality_enabled,
        "tick_storage_enabled": cfg.tick_storage_enabled,
        "summary": quality_summary(),
    }


@router.get("/data-quality/comparisons")
async def data_quality_comparisons(limit: int = Query(default=100, ge=1, le=500)):
    from app.market_data.data_quality import recent_comparisons
    return {"items": recent_comparisons(limit)}


@router.get("/data-quality/observations")
async def data_quality_observations(
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    from app.market_data.data_quality import recent_observations
    return {"items": recent_observations(symbol, limit)}


@router.get("/microstructure/{symbol}")
async def market_microstructure(symbol: str):
    """Latest stored AllTick depth snapshot metrics for one instrument."""
    from app.market_data.microstructure import latest_orderbook, analyze_orderbook
    book = latest_orderbook(symbol.upper())
    if not book:
        raise HTTPException(status_code=404, detail="No stored order-book snapshot. Enable AllTick depth subscription and tick storage first.")
    return analyze_orderbook(book)


@router.get("/microstructure/{symbol}/history")
async def market_microstructure_history(symbol: str, limit: int = Query(default=100, ge=1, le=500)):
    from app.market_data.microstructure import orderbook_history
    return {"items": orderbook_history(symbol.upper(), limit)}


@router.get("/microstructure/{symbol}/estimate")
async def market_microstructure_estimate(
    symbol: str,
    side: str = Query(..., pattern="^(buy|sell)$"),
    quantity: float = Query(..., gt=0),
    max_age_seconds: float = Query(default=30, gt=0, le=300),
):
    """Estimate a visible-depth sweep; this is not an execution or guaranteed fill."""
    from app.market_data.microstructure import latest_orderbook, estimate_sweep
    book = latest_orderbook(symbol.upper())
    if not book:
        raise HTTPException(status_code=404, detail="No stored order-book snapshot. Enable AllTick depth subscription and tick storage first.")
    return estimate_sweep(book, side, quantity, max_age_seconds)
