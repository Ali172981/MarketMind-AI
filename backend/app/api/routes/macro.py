from fastapi import APIRouter
from app.market_data.fred_provider import get_macro_snapshot

router = APIRouter(prefix="/macro", tags=["macro"])


@router.get("/overview")
async def macro_overview():
    return get_macro_snapshot()
