import asyncio
import json
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.market_data.demo_provider import get_quotes
from app.market_data.binance_provider import get_feed_status
from app.core.config import settings

router = APIRouter(tags=["streaming"])


@router.websocket("/ws/market")
async def market_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            live_mode = settings.data_mode.lower() == "binance"
            payload = {
                "event": "market_snapshot",
                "data_status": "LIVE_PARTIAL" if live_mode else "DEMO",
                "notice": "Crypto quotes are live from Binance Spot; metals are unavailable until a separate provider is configured." if live_mode else "Simulated demo stream; not live market data.",
                "feed": get_feed_status() if live_mode else {"provider": "Demo fixtures", "status": "DEMO"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "items": [q.model_dump() for q in get_quotes()],
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
