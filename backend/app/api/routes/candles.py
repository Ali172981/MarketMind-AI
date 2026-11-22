from fastapi import APIRouter, HTTPException, Query
from app.market_data.candle_provider import INTERVALS as BINANCE_INTERVALS, SYMBOLS as BINANCE_SYMBOLS, get_ohlcv
from app.market_data.candle_history import backfill_history, MAX_BACKFILL_CANDLES
from app.market_data.alltick_provider import get_ohlcv as get_alltick_ohlcv, SYMBOL_CODES as ALLTICK_SYMBOLS, INTERVAL_TYPES as ALLTICK_INTERVALS
from app.core.config import settings

router = APIRouter(prefix="/market", tags=["candles"])


def _allowed():
    if settings.data_mode.lower() == "alltick":
        return set(ALLTICK_SYMBOLS), set(ALLTICK_INTERVALS)
    return set(BINANCE_SYMBOLS), set(BINANCE_INTERVALS)


@router.get("/candles")
async def candles(
    symbol: str = Query(default="BTCUSDT", description="Provider-supported symbol"),
    interval: str = Query(default="1h", description="Supported provider timeframe"),
    limit: int = Query(default=300, ge=1, le=MAX_BACKFILL_CANDLES),
):
    symbol = symbol.upper()
    symbols, intervals = _allowed()
    if symbol not in symbols:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(symbols))}")
    if interval not in intervals:
        raise HTTPException(status_code=400, detail=f"Unsupported interval. Choose from: {', '.join(sorted(intervals))}")
    try:
        if settings.data_mode.lower() == "alltick":
            return await get_alltick_ohlcv(symbol, interval, min(limit, 500))
        return await get_ohlcv(symbol, interval, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Market candle provider unavailable: {str(exc)[:180]}") from exc


@router.get("/candles/status")
async def candle_status():
    if settings.data_mode.lower() == "alltick":
        from app.market_data.alltick_provider import get_status
        return get_status()
    from app.market_data.candle_provider import get_candle_feed_status
    return get_candle_feed_status()


@router.post("/candles/backfill")
async def backfill_candles(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=10_000, ge=100, le=MAX_BACKFILL_CANDLES),
):
    symbol = symbol.upper()
    symbols, intervals = _allowed()
    if symbol not in symbols:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(symbols))}")
    if interval not in intervals:
        raise HTTPException(status_code=400, detail=f"Unsupported interval. Choose from: {', '.join(sorted(intervals))}")
    try:
        if settings.data_mode.lower() == "alltick":
            result = await get_alltick_ohlcv(symbol, interval, min(limit, 500))
            result["requested_candles"] = limit
            result["provider_max_per_request"] = 500
            result["notice"] += " AllTick backfill is limited to one request and 500 candles in this integration."
            return result
        return await backfill_history(symbol, interval, limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Historical backfill unavailable: {str(exc)[:180]}") from exc
