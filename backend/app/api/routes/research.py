from fastapi import APIRouter, HTTPException, Query
from app.core.config import settings
from app.market_data.alltick_provider import SYMBOL_CODES as ALLTICK_SYMBOLS, INTERVAL_TYPES as ALLTICK_INTERVALS

from app.analysis.research import run_calibration_study
from app.market_data.candle_provider import INTERVALS, SYMBOLS, get_ohlcv
from app.market_data.candle_history import MAX_BACKFILL_CANDLES

router = APIRouter(prefix="/market/research", tags=["research-validation"])


def _allowed():
    if settings.data_mode.lower() == "alltick":
        return set(ALLTICK_SYMBOLS), set(ALLTICK_INTERVALS)
    return set(SYMBOLS), set(INTERVALS)


@router.get("/walk-forward")
@router.get("/calibration")
async def calibration_study(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=20_000, ge=500, le=MAX_BACKFILL_CANDLES),
    horizon: int = Query(default=48, ge=5, le=500),
    reward_risk: float = Query(default=2.0, ge=0.5, le=5.0),
    atr_stop: float = Query(default=1.5, ge=0.25, le=5.0),
):
    symbol = symbol.upper()
    symbols, intervals = _allowed()
    if symbol not in symbols:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(symbols))}")
    if interval not in intervals:
        raise HTTPException(status_code=400, detail=f"Unsupported interval. Choose from: {', '.join(sorted(intervals))}")
    try:
        payload = await get_ohlcv(symbol, interval, limit)
        study = run_calibration_study(
            payload.get("items", []), horizon=horizon,
            reward_risk=reward_risk, atr_stop_multiple=atr_stop,
        )
        return {
            "symbol": symbol,
            "interval": interval,
            "data_status": payload.get("data_status"),
            "source": payload.get("source"),
            "fetched_at": payload.get("fetched_at"),
            "stored_candles": payload.get("count", len(payload.get("items", []))),
            "study": study,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Calibration study unavailable: {str(exc)[:180]}") from exc
