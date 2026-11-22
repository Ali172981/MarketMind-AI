from fastapi import APIRouter, HTTPException, Query
from app.core.config import settings
from app.market_data.alltick_provider import SYMBOL_CODES as ALLTICK_SYMBOLS, INTERVAL_TYPES as ALLTICK_INTERVALS
from app.analysis.smc import analyze_smc
from app.market_data.candle_provider import INTERVALS, SYMBOLS, get_ohlcv

router = APIRouter(prefix="/market", tags=["smart-money-concepts"])


def _allowed():
    if settings.data_mode.lower() == "alltick":
        return set(ALLTICK_SYMBOLS), set(ALLTICK_INTERVALS)
    return set(SYMBOLS), set(INTERVALS)


@router.get("/smc")
async def smc_analysis(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=300, ge=50, le=1000),
):
    symbol = symbol.upper()
    symbols, intervals = _allowed()
    if symbol not in symbols:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(symbols))}")
    if interval not in intervals:
        raise HTTPException(status_code=400, detail=f"Unsupported interval. Choose from: {', '.join(sorted(intervals))}")
    try:
        payload = await get_ohlcv(symbol, interval, limit)
        analysis = analyze_smc(payload.get("items", []))
        return {"symbol": symbol, "interval": interval, "data_status": payload.get("data_status"), "source": payload.get("source"), "analysis": analysis}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMC analysis unavailable: {str(exc)[:180]}") from exc


@router.get("/smc/multi-timeframe")
async def smc_multi_timeframe(
    symbol: str = Query(default="BTCUSDT"),
    intervals: str = Query(default="15m,1h,4h"),
    limit: int = Query(default=300, ge=50, le=1000),
):
    symbol = symbol.upper()
    requested = [item.strip() for item in intervals.split(",") if item.strip()]
    symbols, supported_intervals = _allowed()
    if symbol not in symbols:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(symbols))}")
    if not requested or len(requested) > 6 or any(item not in supported_intervals for item in requested):
        raise HTTPException(status_code=400, detail=f"Choose up to six supported intervals: {', '.join(sorted(supported_intervals))}")
    results = []
    for interval in requested:
        try:
            payload = await get_ohlcv(symbol, interval, limit)
            analysis = analyze_smc(payload.get("items", []))
            results.append({"interval": interval, "data_status": payload.get("data_status"), "analysis": analysis})
        except Exception as exc:
            results.append({"interval": interval, "data_status": "UNAVAILABLE", "error": str(exc)[:180]})
    trends = [item["analysis"].get("structure", {}).get("trend") for item in results if item.get("analysis", {}).get("status") == "OK"]
    bullish = trends.count("BULLISH")
    bearish = trends.count("BEARISH")
    consensus = "BULLISH_ALIGNMENT" if bullish and bullish > bearish else "BEARISH_ALIGNMENT" if bearish and bearish > bullish else "MIXED_OR_INSUFFICIENT"
    return {"symbol": symbol, "intervals": results, "alignment": consensus, "note": "Timeframe alignment is descriptive context, not a probability or trade instruction."}
