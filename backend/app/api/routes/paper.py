from fastapi import APIRouter, HTTPException, Query

from app.analysis.paper_portfolio import portfolio_summary
from app.analysis.paper_execution import (
    advance_paper_executions,
    execution_summary,
    execution_assumptions,
    list_execution_simulations,
)
from app.analysis.paper_observations import (
    advance_open_observations,
    list_observations,
    observation_summary,
    record_latest_structure_observations,
    latest_recorder_run,
    list_recorder_runs,
)
from app.workers.paper_recorder import recorder_config, runtime_status
from app.market_data.candle_provider import INTERVALS, SYMBOLS, get_ohlcv
from app.core.config import settings

router = APIRouter(prefix="/market/research/paper", tags=["prospective-paper-observations"])


def _validate_filters(symbol: str | None, interval: str | None) -> tuple[str | None, str | None]:
    symbol = symbol.upper() if symbol else None
    if symbol and symbol not in SYMBOLS:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(SYMBOLS))}")
    if interval and interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"Unsupported interval. Choose from: {', '.join(sorted(INTERVALS))}")
    return symbol, interval


@router.post("/observe")
async def collect_observation(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=2000, ge=100, le=5000),
):
    if settings.data_mode.lower() == "alltick":
        raise HTTPException(status_code=409, detail="Prospective paper observation capture and execution remain Binance-source-only; switch DATA_MODE=binance before collecting.")
    symbol = symbol.upper()
    if symbol not in SYMBOLS:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol. Choose from: {', '.join(sorted(SYMBOLS))}")
    if interval not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"Unsupported interval. Choose from: {', '.join(sorted(INTERVALS))}")
    try:
        payload = await get_ohlcv(symbol, interval, limit)
        candles = payload.get("items", [])
        advanced = advance_open_observations(symbol, interval, candles)
        recorded = record_latest_structure_observations(
            symbol, interval, candles, data_source=str(payload.get("source", "unknown")),
        )
        execution = advance_paper_executions(symbol, interval, candles)
        return {
            "symbol": symbol,
            "interval": interval,
            "data_status": payload.get("data_status"),
            "source": payload.get("source"),
            "fetched_at": payload.get("fetched_at"),
            "stored_candles": payload.get("count", len(candles)),
            "recording": recorded,
            "advancement": advanced,
            "execution": execution,
            "summary": observation_summary(symbol, interval),
            "probabilities_recorded": False,
            "orders_submitted": False,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Paper observation capture unavailable: {str(exc)[:180]}") from exc


@router.get("/observations")
async def get_observations(
    symbol: str | None = Query(default=None),
    interval: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    symbol, interval = _validate_filters(symbol, interval)
    return {
        "items": list_observations(symbol, interval, limit),
        "summary": observation_summary(symbol, interval),
        "probabilities_recorded": False,
        "orders_submitted": False,
    }


@router.get("/summary")
async def get_observation_summary(
    symbol: str | None = Query(default=None),
    interval: str | None = Query(default=None),
):
    symbol, interval = _validate_filters(symbol, interval)
    return observation_summary(symbol, interval)


@router.get("/automation/status")
async def get_automation_status():
    config = recorder_config()
    return {
        "configuration": config,
        "runtime": runtime_status(),
        "latest_run": latest_recorder_run(),
        "probabilities_recorded": False,
        "orders_submitted": False,
        "notice": "The optional scheduler only observes public closed candles and records hypothetical outcomes. It does not generate forecasts, broker fills or orders.",
    }


@router.get("/automation/runs")
async def get_automation_runs(limit: int = Query(default=20, ge=1, le=100)):
    return {
        "items": list_recorder_runs(limit),
        "probabilities_recorded": False,
        "orders_submitted": False,
    }


@router.get("/executions")
async def get_execution_simulations(
    symbol: str | None = Query(default=None),
    interval: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    symbol, interval = _validate_filters(symbol, interval)
    return {
        "items": list_execution_simulations(symbol, interval, limit),
        "summary": execution_summary(symbol, interval),
        "orders_submitted": False,
    }


@router.get("/executions/summary")
async def get_execution_summary(
    symbol: str | None = Query(default=None),
    interval: str | None = Query(default=None),
):
    symbol, interval = _validate_filters(symbol, interval)
    return execution_summary(symbol, interval)


@router.get("/executions/assumptions")
async def get_execution_assumptions():
    return {
        "assumptions": execution_assumptions(),
        "notice": "These are fixed simulation assumptions, not observed exchange bid/ask, account fee tier, or live market impact.",
        "orders_submitted": False,
    }


@router.get("/portfolio/summary")
async def get_portfolio_summary(
    symbol: str | None = Query(default=None),
    interval: str | None = Query(default=None),
):
    symbol, interval = _validate_filters(symbol, interval)
    try:
        return portfolio_summary(symbol, interval)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid portfolio configuration: {exc}") from exc
