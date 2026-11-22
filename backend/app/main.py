import asyncio
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import health, assets, market, news, websocket, macro, candles, smc, backtest, research, paper, strategy
from app.market_data.binance_provider import run_binance_feed
from app.market_data.xaus_provider import run_metals_feed
from app.market_data.fred_provider import run_fred_refresh
from app.market_data.candle_provider import run_candle_stream
from app.market_data.alltick_provider import run_quote_feed as run_alltick_quote_feed
from app.market_data.alltick_websocket import run_stream as run_alltick_websocket
from app.market_data.data_quality import run_data_quality_monitor
from app.market_data.candle_store import init_db
from app.workers.paper_recorder import run_paper_recorder, recorder_config
from app.core.notifications import monitor_loop
from app.market_data.news_intelligence import news_worker

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.app_env.lower() == "production" and not settings.api_access_key:
        raise RuntimeError("API_ACCESS_KEY is required when APP_ENV=production")
    tasks: list[asyncio.Task] = [asyncio.create_task(monitor_loop())]
    if settings.news_enabled:
        tasks.append(asyncio.create_task(news_worker(settings.news_poll_seconds)))
    if settings.data_mode.lower() == "binance":
        tasks.append(asyncio.create_task(run_binance_feed()))
        tasks.append(asyncio.create_task(run_metals_feed()))
        tasks.append(asyncio.create_task(run_candle_stream()))
    elif settings.data_mode.lower() == "alltick":
        # Independent reference feeds remain isolated from AllTick primary data.
        tasks.append(asyncio.create_task(run_binance_feed()))
        tasks.append(asyncio.create_task(run_metals_feed()))
        if settings.alltick_ws_enabled:
            tasks.append(asyncio.create_task(run_alltick_websocket()))
        else:
            tasks.append(asyncio.create_task(run_alltick_quote_feed()))
        if settings.data_quality_enabled:
            tasks.append(asyncio.create_task(run_data_quality_monitor()))
    else:
        tasks.append(asyncio.create_task(run_metals_feed()))
    tasks.append(asyncio.create_task(run_fred_refresh()))
    if recorder_config()["enabled"]:
        tasks.append(asyncio.create_task(run_paper_recorder()))
    app.state.feed_tasks = tasks
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        app.state.feed_tasks = []

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    description=(
        "MarketMind AI research-first market intelligence API. "
        "Market feeds are independently labelled by provider and freshness; AllTick is an optional REST/WebSocket provider requiring a user token; cross-provider comparisons are diagnostic only and provider histories remain separate; news is sourced from public RSS feeds and heuristically tagged. "
        "Backtests, walk-forward diagnostics, prospective paper observations and cost-aware OHLC execution and portfolio-capital scenarios are research-only; no trading orders are submitted."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lightweight single-process write protection. For multi-worker deployments,
# enforce rate limits at the reverse proxy as documented in deploy/.
_write_hits: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def protect_write_requests(request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(prefix := settings.api_v1_prefix):
        if settings.api_access_key and request.headers.get("x-api-key", "") != settings.api_access_key:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=401, content={"detail": "Valid X-API-Key header required for write operations"})
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = _write_hits[client_ip]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= max(1, settings.write_rate_limit_per_minute):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=429, content={"detail": "Write request rate limit exceeded"}, headers={"Retry-After": "60"})
        hits.append(now)
    return await call_next(request)

prefix = settings.api_v1_prefix
app.include_router(health.router, prefix=prefix)
app.include_router(assets.router, prefix=prefix)
app.include_router(market.router, prefix=prefix)
app.include_router(news.router, prefix=prefix)
app.include_router(websocket.router, prefix=prefix)
app.include_router(macro.router, prefix=prefix)
app.include_router(candles.router, prefix=prefix)
app.include_router(smc.router, prefix=prefix)
app.include_router(backtest.router, prefix=prefix)
app.include_router(research.router, prefix=prefix)
app.include_router(paper.router, prefix=prefix)
app.include_router(strategy.router, prefix=prefix)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "status": "running",
        "data_mode": settings.data_mode,
        "version": "1.0.0",
        "notice": "Market data mode is controlled by DATA_MODE (demo, binance, or alltick). News is public RSS data with heuristic-only event tags. Strict research mode suppresses historical probabilities unless every declared validation gate passes; the optional scheduled paper recorder stores prospective observations and deterministic cost-aware OHLC execution and portfolio-capital scenarios only; probabilities and live trading remain disabled.",
        "docs": "/docs",
    }
