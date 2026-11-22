"""Read-only deployment preflight for MarketMind AI.

Run from backend/: python scripts_preflight.py
The check never prints secrets and does not contact external providers.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path

from app.core.config import settings
from app.market_data.candle_store import DB_PATH


def run_checks() -> tuple[list[tuple[str, str, str]], int]:
    rows: list[tuple[str, str, str]] = []
    failures = 0

    def add(level: str, name: str, detail: str) -> None:
        nonlocal failures
        rows.append((level, name, detail))
        if level == "FAIL":
            failures += 1

    mode = settings.data_mode.strip().lower()
    if mode in {"demo", "binance", "alltick"}:
        add("PASS", "DATA_MODE", f"Configured provider mode: {mode}")
    else:
        add("FAIL", "DATA_MODE", "Must be demo, binance, or alltick")

    production = settings.app_env.strip().lower() == "production"
    if production and len(settings.api_access_key) < 32:
        add("FAIL", "API_ACCESS_KEY", "Production requires a secret of at least 32 characters")
    elif settings.api_access_key:
        add("PASS", "API_ACCESS_KEY", "Configured; secret value not displayed")
    else:
        add("WARN", "API_ACCESS_KEY", "Not configured; write endpoints are unauthenticated")

    if production and any(origin.strip() == "*" for origin in settings.cors_origins_list):
        add("FAIL", "CORS", "Wildcard origins are not permitted by this production preflight")
    elif production and any("localhost" in origin or "127.0.0.1" in origin for origin in settings.cors_origins_list):
        add("WARN", "CORS", "Production origins still include localhost; review CORS_ORIGINS")
    else:
        add("PASS", "CORS", "Configured origins reviewed for this environment")

    if mode == "alltick" and not settings.alltick_api_key:
        add("FAIL", "ALLTICK_API_KEY", "AllTick selected but no server-side token is configured")
    elif mode == "alltick":
        add("PASS", "ALLTICK_API_KEY", "Token configured; authentication is not tested by this offline check")

    if settings.alltick_ws_enabled and mode != "alltick":
        add("FAIL", "AllTick WebSocket", "WebSocket enabled while DATA_MODE is not alltick")
    elif settings.alltick_ws_enabled and settings.alltick_ws_subscription.lower() not in {"trade", "depth"}:
        add("FAIL", "AllTick WebSocket", "Subscription must be trade or depth")
    elif settings.alltick_ws_enabled:
        add("PASS", "AllTick WebSocket", f"Enabled in {settings.alltick_ws_subscription.lower()} mode")

    if settings.paper_recorder_enabled and mode != "binance":
        add("FAIL", "Paper recorder", "Scheduled recorder requires DATA_MODE=binance")
    elif settings.paper_recorder_enabled:
        add("WARN", "Paper recorder", "Enabled; run a single API worker to avoid duplicate scheduler loops")
    else:
        add("PASS", "Paper recorder", "Disabled by default")

    if settings.write_rate_limit_per_minute < 1:
        add("FAIL", "Write rate limit", "WRITE_RATE_LIMIT_PER_MINUTE must be at least 1")
    else:
        add("PASS", "Write rate limit", f"{settings.write_rate_limit_per_minute} requests/minute per IP in this process")

    db_path = Path(DB_PATH).expanduser()
    if not db_path.exists():
        add("WARN", "SQLite database", f"Not created yet; backend will initialize it at {db_path}")
    else:
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as conn:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if result == "ok":
                add("PASS", "SQLite integrity", f"Integrity check passed ({db_path})")
            else:
                add("FAIL", "SQLite integrity", f"SQLite reports: {result}")
        except Exception as exc:
            add("FAIL", "SQLite integrity", f"Could not inspect database: {type(exc).__name__}")

    usage = shutil.disk_usage(db_path.parent if db_path.parent.exists() else Path.cwd())
    free_gib = usage.free / (1024 ** 3)
    if free_gib < 1:
        add("WARN", "Disk space", f"Only {free_gib:.2f} GiB free; monitor database and backup growth")
    else:
        add("PASS", "Disk space", f"{free_gib:.2f} GiB free at database location")

    if not production:
        add("WARN", "Environment", "Not production mode; do not expose this instance directly to the public internet")
    else:
        add("PASS", "Environment", "Production mode selected; HTTPS must terminate at a trusted reverse proxy")

    return rows, failures


def main() -> int:
    rows, failures = run_checks()
    print("MarketMind AI deployment preflight (offline; no provider API calls)\n")
    for level, name, detail in rows:
        print(f"[{level:4}] {name}: {detail}")
    print(f"\nResult: {failures} failure(s), {sum(level == 'WARN' for level, *_ in rows)} warning(s)")
    print("This is a configuration/SQLite check, not a live provider or VPS acceptance test.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
