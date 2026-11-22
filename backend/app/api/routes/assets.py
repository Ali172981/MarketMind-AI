from fastapi import APIRouter
from app.market_data.demo_provider import get_assets

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("")
async def list_assets():
    return {"items": [asset.model_dump() for asset in get_assets()], "count": len(get_assets())}
