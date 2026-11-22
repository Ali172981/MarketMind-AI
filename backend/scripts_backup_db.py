#!/usr/bin/env python3
"""Create and verify an online SQLite backup with retention."""
from __future__ import annotations
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.market_data.candle_store import DB_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default=str(Path(__file__).resolve().parent / "backups"))
    parser.add_argument("--retain", type=int, default=14)
    args = parser.parse_args()
    if args.retain < 1:
        parser.error("--retain must be at least 1")
    source = Path(DB_PATH)
    if not source.exists():
        print(f"Database does not exist: {source}", file=sys.stderr)
        return 2
    target_dir = Path(args.destination).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = target_dir / f"marketmind-{stamp}.db"
    temporary = target_dir / f".{final.name}.tmp"
    try:
        with sqlite3.connect(source, timeout=30) as src, sqlite3.connect(temporary) as dst:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"Backup integrity check failed: {result}")
        os.replace(temporary, final)
        backups = sorted(target_dir.glob("marketmind-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[args.retain:]:
            old.unlink()
        print(f"Backup verified: {final}")
        return 0
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
