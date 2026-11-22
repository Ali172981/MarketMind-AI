from fastapi import APIRouter, HTTPException, Query
from app.core.config import settings
from app.market_data.alltick_provider import SYMBOL_CODES as ALLTICK_SYMBOLS, INTERVAL_TYPES as ALLTICK_INTERVALS

from app.analysis.backtest import run_smc_backtest
from app.market_data.candle_provider import INTERVALS, SYMBOLS, get_ohlcv
from app.market_data.candle_history import MAX_BACKFILL_CANDLES

router = APIRouter(prefix="/market", tags=["backtesting"])


def _allowed():
    if settings.data_mode.lower() == "alltick":
        return set(ALLTICK_SYMBOLS), set(ALLTICK_INTERVALS)
    return set(SYMBOLS), set(INTERVALS)


@router.get("/backtest/smc")
async def smc_backtest(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=1000, ge=100, le=MAX_BACKFILL_CANDLES),
    reward_risk: float = Query(default=2.0, ge=0.5, le=10.0),
    atr_stop: float = Query(default=1.5, ge=0.25, le=10.0),
    fee_bps: float = Query(default=5.0, ge=0.0, le=100.0),
    slippage_bps: float = Query(default=2.0, ge=0.0, le=100.0),
    risk_pct: float = Query(default=1.0, gt=0.0, le=5.0),
    max_holding_bars: int = Query(default=48, ge=1, le=500),
):
    symbol = symbol.upper()
    symbols, intervals = _allowed()
    if symbol not in symbols:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(symbols))}")
    if interval not in intervals:
        raise HTTPException(status_code=400, detail=f"Unsupported interval. Choose from: {', '.join(sorted(intervals))}")
    try:
        payload = await get_ohlcv(symbol, interval, limit)
        result = run_smc_backtest(
            payload.get("items", []), reward_risk=reward_risk,
            atr_stop_multiple=atr_stop, fee_bps=fee_bps,
            slippage_bps=slippage_bps, risk_per_trade_pct=risk_pct,
            max_holding_bars=max_holding_bars,
        )
        return {
            "symbol": symbol, "interval": interval,
            "data_status": payload.get("data_status"),
            "source": payload.get("source"),
            "fetched_at": payload.get("fetched_at"),
            "backtest": result,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Backtest unavailable: {str(exc)[:180]}") from exc
