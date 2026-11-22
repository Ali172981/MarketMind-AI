from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.market_data.candle_store import DB_PATH
from app.market_data.candle_provider import get_candle_feed_status, latest_open_time, SYMBOLS, INTERVALS
from app.core.config import settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def diagnostics() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        with sqlite3.connect(DB_PATH, timeout=3) as conn:
            conn.execute("SELECT 1").fetchone()
            integrity = conn.execute("PRAGMA quick_check").fetchone()[0]
        checks["database"] = {"status": "ok" if integrity == "ok" else "error", "integrity": integrity, "path": str(DB_PATH), "size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0}
    except Exception as exc:
        checks["database"] = {"status": "error", "error": str(exc)[:200]}

    feed = get_candle_feed_status()
    feed_state = str(feed.get("status", "UNKNOWN"))
    checks["binance_websocket"] = {**feed, "health": "ok" if feed_state == "CONNECTED" else ("warning" if settings.data_mode.lower() == "binance" else "not_configured")}
    pair_freshness = []
    if settings.data_mode.lower() == "binance":
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for symbol in sorted(SYMBOLS):
            for interval in ("1h", "4h", "1d"):
                try:
                    latest = latest_open_time(symbol, interval)
                    age = None if latest is None else max(0, (now_ms - latest) // 1000)
                    # A candle's open time naturally ages for the duration of its interval.
                    threshold = {"1h": 3 * 3600, "4h": 12 * 3600, "1d": 72 * 3600}[interval]
                    pair_freshness.append({"symbol": symbol, "interval": interval, "latest_open_time_ms": latest, "age_seconds": age, "status": "missing" if age is None else ("stale" if age > threshold else "ok")})
                except Exception as exc:
                    pair_freshness.append({"symbol": symbol, "interval": interval, "status": "error", "error": str(exc)[:120]})
    stale_count = sum(1 for item in pair_freshness if item["status"] in {"missing", "stale", "error"})
    checks["market_data"] = {"status": "warning" if stale_count else ("ok" if pair_freshness else "not_configured"), "pairs": pair_freshness, "problem_pairs": stale_count}

    disk = shutil.disk_usage(DB_PATH.parent if DB_PATH.parent.exists() else Path.cwd())
    checks["disk"] = {"status": "warning" if disk.free < 1_000_000_000 else "ok", "free_bytes": disk.free, "total_bytes": disk.total}
    overall = "error" if any(v.get("status") == "error" for v in checks.values()) else ("degraded" if any(v.get("status") == "warning" for v in checks.values()) else "ok")
    return {"status": overall, "timestamp": _utc_now(), "version": "0.18.0", "environment": settings.app_env, "data_mode": settings.data_mode, "checks": checks}
