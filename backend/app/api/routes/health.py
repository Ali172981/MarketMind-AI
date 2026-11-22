from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.config import settings
from app.core.operations import diagnostics

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "marketmind-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_mode": settings.data_mode,
    }


@router.get("/health/diagnostics")
async def health_diagnostics():
    """Detailed operational checks; does not expose credentials or environment values."""
    return diagnostics()
