# MarketMind AI — Operations Runbook

## Start locally

Backend terminal:

```bash
cd ~/Projects/marketmind-ai-v1.0.0/marketmind-ai/backend
source .venv/bin/activate
python scripts_preflight.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend terminal:

```bash
cd ~/Projects/marketmind-ai-v1.0.0/marketmind-ai/frontend
npm run dev
```

Dashboard: `http://localhost:3000`  
API docs: `http://127.0.0.1:8000/docs`

## Routine health checks

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health
curl -fsS http://127.0.0.1:8000/api/v1/health/diagnostics
curl -fsS http://127.0.0.1:8000/api/v1/market/candles/status
curl -fsS http://127.0.0.1:8000/api/v1/market/data-quality
curl -fsS http://127.0.0.1:8000/api/v1/market/stream
```

Some endpoints return `CONNECTING`, `NO_COMPARISONS` or unavailable states until their optional provider is configured. Do not interpret those states as healthy live data.

## Back up SQLite

Stop the API for a simple maintenance window, or use the SQLite online backup utility while it is running:

```bash
cd ~/Projects/marketmind-ai-v1.0.0/marketmind-ai/backend
source .venv/bin/activate
python scripts_backup_db.py --destination ./backups --retain 14
```

Copy a verified backup to an offsite destination. Local retention alone is not disaster recovery.

## Restore procedure

1. Stop the backend.
2. Preserve the current database file and its `-wal`/`-shm` siblings for forensic recovery.
3. Copy the selected verified backup to the configured database path.
4. Run `python scripts_preflight.py` and confirm SQLite integrity.
5. Start the backend and check health, candle status, paper ledger and observation counts.
6. Keep the pre-restore database until the restored application is confirmed.

Never copy a live SQLite database using a plain file copy while the API is writing. Use the backup utility or SQLite's online backup API.

## Update procedure

1. Back up the current database and `.env` securely.
2. Stop the API and any frontend process.
3. Extract the new release into a new versioned directory.
4. Create a fresh Python virtual environment and install `requirements.txt`.
5. Copy `.env` and restore the database backup into the new release's configured database location.
6. Run tests and `python scripts_preflight.py`.
7. Start the API and frontend; verify health and key research endpoints.
8. Keep the previous release and backup until acceptance is complete.

Do not overwrite the old release in place.

## Public VPS checklist

- `APP_ENV=production` and a randomly generated `API_ACCESS_KEY` of at least 32 characters.
- HTTPS at a trusted reverse proxy; backend bound to loopback/private interface.
- Firewall exposes only required HTTPS/SSH ports; do not expose Uvicorn port 8000 publicly.
- Exact frontend origin in `CORS_ORIGINS`; no wildcard.
- Secrets only in protected server environment files; restrict file permissions.
- Reverse-proxy request limits and access logs. Built-in write limiter is per-process only.
- Single API worker while in-process paper/news/data-quality schedulers are enabled.
- Offsite, encrypted, periodically restore-tested backups.
- Disk, memory, logs, feed freshness and notification delivery monitored.
- Do not expose detailed diagnostics or interactive API docs to the public without an access policy.

## Incident response

- **Feed stale/disconnected:** inspect provider status and source timestamps; do not use stale quotes for research decisions. Check provider status page, token entitlement, DNS/network and service logs.
- **AllTick authentication failure:** verify token locally and account product access. Never paste the token into support chats, logs or screenshots.
- **SQLite integrity failure:** stop writes, preserve database plus WAL/SHM files, restore a verified backup to a separate path, and inspect before switching over.
- **Disk pressure:** pause high-volume observation capture, preserve a backup, review retention and free space. Do not delete the active database manually.
- **Unexpected research output:** save the exact data snapshot/fingerprint, settings and report. Do not relax validation gates to obtain a passing result.

## Security note

The write API key is a shared service key, not user authentication or role-based access control. It is not a substitute for a proper identity system if multiple users will access the service.
