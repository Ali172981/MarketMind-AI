"""SQLite-backed OHLCV cache with provider-separated Binance and AllTick tables.

Separate tables prevent a provider switch from silently overwriting or mixing
historical observations. SQLite keeps the first deployment simple and free.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "marketmind.db"
DB_PATH = Path(os.getenv("CANDLE_DB_PATH", str(DEFAULT_DB))).expanduser()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def db_connection():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                close_time INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL NOT NULL DEFAULT 0,
                trades INTEGER NOT NULL DEFAULT 0,
                taker_buy_base REAL NOT NULL DEFAULT 0,
                is_closed INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'Binance',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, interval, open_time)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles(symbol, interval, open_time DESC)")
        # AllTick observations live in a separate table so changing providers
        # cannot overwrite or contaminate the Binance historical research series.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alltick_candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                close_time INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL NOT NULL DEFAULT 0,
                trades INTEGER NOT NULL DEFAULT 0,
                taker_buy_base REAL NOT NULL DEFAULT 0,
                is_closed INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'AllTick REST K-line',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, interval, open_time)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alltick_candles_lookup ON alltick_candles(symbol, interval, open_time DESC)")


def upsert_candles(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    init_db()
    groups: dict[str, list[dict[str, Any]]] = {"candles": [], "alltick_candles": []}
    for row in rows:
        table = "alltick_candles" if "alltick" in str(row.get("source", "")).lower() else "candles"
        groups[table].append(row)
    sql_template = """
        INSERT INTO {table} (
            symbol, interval, open_time, close_time, open, high, low, close,
            volume, quote_volume, trades, taker_buy_base, is_closed, source, updated_at
        ) VALUES (
            :symbol, :interval, :open_time, :close_time, :open, :high, :low, :close,
            :volume, :quote_volume, :trades, :taker_buy_base, :is_closed, :source, CURRENT_TIMESTAMP
        )
        ON CONFLICT(symbol, interval, open_time) DO UPDATE SET
            close_time=excluded.close_time, open=excluded.open, high=excluded.high,
            low=excluded.low, close=excluded.close, volume=excluded.volume,
            quote_volume=excluded.quote_volume, trades=excluded.trades,
            taker_buy_base=excluded.taker_buy_base, is_closed=excluded.is_closed,
            source=excluded.source, updated_at=CURRENT_TIMESTAMP
    """
    with db_connection() as conn:
        for table, group in groups.items():
            if group:
                conn.executemany(sql_template.format(table=table), group)


def get_candles(
    symbol: str,
    interval: str,
    limit: int,
    source: str | None = None,
) -> list[dict[str, Any]]:
    init_db()
    if source is None:
        try:
            from app.core.config import settings
            source = "AllTick" if settings.data_mode.lower() == "alltick" else "Binance"
        except Exception:
            source = "Binance"
    table = "alltick_candles" if "alltick" in source.lower() else "candles"
    with db_connection() as conn:
        result = conn.execute(
            f"SELECT * FROM {table} WHERE symbol=? AND interval=? ORDER BY open_time DESC LIMIT ?",
            (symbol, interval, limit),
        ).fetchall()
    output = []
    for row in reversed(result):
        item = dict(row)
        item["time"] = item.pop("open_time") // 1000
        item["is_closed"] = bool(item["is_closed"])
        output.append(item)
    return output


def latest_open_time(symbol: str, interval: str, source: str | None = None) -> int | None:
    init_db()
    if source is None:
        try:
            from app.core.config import settings
            source = "AllTick" if settings.data_mode.lower() == "alltick" else "Binance"
        except Exception:
            source = "Binance"
    table = "alltick_candles" if "alltick" in source.lower() else "candles"
    with db_connection() as conn:
        row = conn.execute(
            f"SELECT MAX(open_time) AS latest FROM {table} WHERE symbol=? AND interval=?",
            (symbol, interval),
        ).fetchone()
    return int(row["latest"]) if row and row["latest"] is not None else None
