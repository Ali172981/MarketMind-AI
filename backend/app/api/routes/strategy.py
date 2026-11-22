from fastapi import APIRouter, HTTPException, Query
from app.core.config import settings
from app.analysis.strategy import analyze_strategy
from app.market_data.candle_provider import INTERVALS, SYMBOLS, get_ohlcv
from app.market_data.alltick_provider import SYMBOL_CODES as ALLTICK_SYMBOLS, INTERVAL_TYPES as ALLTICK_INTERVALS
from app.market_data.news_intelligence import list_items

router = APIRouter(prefix="/market/strategy", tags=["strategy-intelligence"])


def _allowed():
    if settings.data_mode.lower() == "alltick":
        return set(ALLTICK_SYMBOLS), set(ALLTICK_INTERVALS)
    return set(SYMBOLS), set(INTERVALS)


@router.get("/analyze")
async def strategy_analysis(
    symbol: str = Query(default="BTCUSDT"),
    intervals: str = Query(default="15m,1h,4h"),
    limit: int = Query(default=300, ge=60, le=1000),
):
    symbol = symbol.upper()
    requested = [x.strip() for x in intervals.split(",") if x.strip()]
    symbols, supported = _allowed()
    if symbol not in symbols:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(symbols))}")
    if not requested or len(requested) > 6 or len(set(requested)) != len(requested) or any(x not in supported for x in requested):
        raise HTTPException(status_code=400, detail=f"Choose up to six unique supported intervals: {', '.join(sorted(supported))}")
    timeframe_data = []
    failures = []
    for interval in requested:
        try:
            payload = await get_ohlcv(symbol, interval, limit)
            timeframe_data.append({
                "interval": interval,
                "candles": payload.get("items", []),
                "source": payload.get("source"),
                "data_status": payload.get("data_status", "UNKNOWN"),
                "fetched_at": payload.get("fetched_at"),
            })
        except Exception as exc:
            failures.append({"interval": interval, "error": str(exc)[:160]})
    try:
        news = list_items(limit=10, asset=symbol)
    except Exception:
        news = []
    result = analyze_strategy(symbol, timeframe_data, news)
    result["requested_intervals"] = requested
    result["unavailable_intervals"] = failures
    result["news_data_status"] = "PUBLIC_RSS" if news else "NO_RELEVANT_STORED_NEWS"
    return result
