# Install MarketMind AI v1.0.0 on Kali Linux

This is a cumulative update based on the saved Phase 1–5 project. Install it beside the earlier folder so the old copy and any local database remain untouched until you verify the new release. This setup uses public Binance market data and does not need trading API keys or paid subscriptions.

## 1. System prerequisites

```bash
sudo apt update
sudo apt install -y git curl wget unzip build-essential python3 python3-pip python3-venv python3-dev
```

Check Python and Node:

```bash
python3 --version
node --version
npm --version
```

Use Python 3.10+ and Node.js 20+ (Node.js 22 LTS recommended). If `node` is missing or older and NVM is not installed:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.bashrc
nvm install 22
nvm use 22
```

## 2. Extract into a new folder

Assuming the ZIP is in `~/Downloads`:

```bash
mkdir -p ~/Projects/marketmind-ai-v1.0.0
unzip ~/Downloads/marketmind-ai-v1.0.0-final.zip -d ~/Projects/marketmind-ai-v1.0.0
cd ~/Projects/marketmind-ai-v1.0.0/marketmind-ai
```

Do not delete the old project folder yet. The new release contains the earlier application source but does not include your local SQLite database or `.env` settings. Stop the old backend before copying its SQLite database. To preserve v0.19.0 research history and configuration, run:

```bash
OLD=~/Projects/marketmind-ai-v0.19.0/marketmind-ai/backend
NEW=~/Projects/marketmind-ai-v1.0.0/marketmind-ai/backend

if [ -f "$OLD/.env" ]; then
  cp "$OLD/.env" "$NEW/.env"
else
  cp "$NEW/.env.example" "$NEW/.env"
fi

if [ -f "$OLD/data/marketmind.db" ]; then
  mkdir -p "$NEW/data"
  cp "$OLD/data/marketmind.db" "$NEW/data/marketmind.db"
fi
```

If `CANDLE_DB_PATH` points elsewhere in the old `.env`, copy that actual database file into the configured location in the new installation instead. Do not copy while the old API is still writing to SQLite.

## 3. Start the backend

```bash
cd ~/Projects/marketmind-ai-v1.0.0/marketmind-ai/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
# Confirm that the preserved .env exists; for a fresh install use:
# cp .env.example .env
python scripts_preflight.py
```

Ensure `.env` contains:

```ini
DATA_MODE=binance
```

The new unattended prospective recorder is **disabled by default**. To enable it, add these settings to `backend/.env`:

```ini
PAPER_RECORDER_ENABLED=true
PAPER_RECORDER_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
PAPER_RECORDER_INTERVALS=1h
PAPER_RECORDER_POLL_SECONDS=60
PAPER_RECORDER_CANDLE_LIMIT=500
```

It requires `DATA_MODE=binance`. The worker fetches public Binance Spot candles, filters out forming candles, rejects stale data, advances earlier observations and records new confirmed SMC events. Each cycle and any per-market errors are stored in SQLite. It never records probabilities or submits orders.

Run **one Uvicorn worker process only** while this in-process scheduler is enabled. Do not start the same collector in multiple API worker processes; they would duplicate polling and audit cycles. The existing unique event key prevents duplicate event rows but is not a distributed scheduler lock.

Start the API:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Keep this terminal open.

## 4. Start the frontend in a second terminal

```bash
cd ~/Projects/marketmind-ai-v1.0.0/marketmind-ai/frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. API documentation is at `http://127.0.0.1:8000/docs`.

## 5. Verify the API and tests in a third terminal

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/health/diagnostics
curl http://127.0.0.1:8000/api/v1/market/candles/status
curl http://127.0.0.1:8000/api/v1/market/research/paper/automation/status
curl "http://127.0.0.1:8000/api/v1/market/research/paper/automation/runs?limit=10"
curl "http://127.0.0.1:8000/api/v1/market/candles?symbol=BTCUSDT&interval=1h&limit=300" | python3 -m json.tool
```

Run backend tests:

```bash
cd ~/Projects/marketmind-ai-v1.0.0/marketmind-ai/backend
source .venv/bin/activate
python -m pytest -q
```

## 6. Fetch research history and run strict walk-forward validation

The first study requests a longer history and stores it in `backend/data/marketmind.db`:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/market/candles/backfill?symbol=BTCUSDT&interval=1h&limit=20000" | python3 -m json.tool
```

Then run the study:

```bash
curl "http://127.0.0.1:8000/api/v1/market/research/walk-forward?symbol=BTCUSDT&interval=1h&limit=20000" | python3 -m json.tool
```

Or use the dashboard's **Walk-Forward Probability Lab**. Select a symbol, timeframe and history size, then press **Run strict walk-forward study**.

If `probabilities_published` is `false`, this is an intentional strict safeguard. The application withholds per-event probabilities unless all five walk-forward folds, baseline comparisons, bootstrap confidence interval, calibration and regime gates pass. A historical pass does not enable live signal alerts.

## Optional: use AllTick instead of Binance

The uploaded AllTick repository documents token registration at https://alltick.co/register. The API token is not included in this project and must remain on the backend.

In `backend/.env`, configure:

```ini
DATA_MODE=alltick
ALLTICK_API_KEY=put_your_private_token_here
ALLTICK_POLL_SECONDS=90
```

Restart the backend, then inspect:

```bash
curl http://127.0.0.1:8000/api/v1/market/prices | python3 -m json.tool
curl http://127.0.0.1:8000/api/v1/market/candles/status | python3 -m json.tool
curl "http://127.0.0.1:8000/api/v1/market/candles?symbol=BTCUSDT&interval=1h&limit=300" | python3 -m json.tool
```

AllTick supports optional WebSocket trade-tick or order-book streaming in this release; REST remains responsible for historical K-line candles. The free-tier documentation states a maximum of 1,000 requests/day, a 10-second request interval, and up to five products per latest-quote batch. MarketMind uses a 90-second default polling interval and a local 1,000-request daily guard. Keep one API process per token and avoid frequent manual history requests. The K-line API returns at most 500 candles per request. Confirm ETHUSDT/SOLUSDT product support in your AllTick account; the supplied repository explicitly lists BTCUSDT, GOLD and Silver examples. The app will report unavailable quotes if a product is not returned. Streaming is disabled by default; see the optional WebSocket configuration section at the end of this guide.

To switch back, set `DATA_MODE=binance` and restart the backend. Do not paste your API key into the frontend `.env.local`, dashboard, screenshots or public issue tracker.

## Troubleshooting

- `externally-managed-environment`: activate `backend/.venv` and install packages only after the activation prompt appears.
- `uvicorn: command not found`: run `python -m pip install -r requirements.txt` inside the activated environment, then use `python -m uvicorn ...`.
- `npm` or `node` missing: install/load NVM as shown above, then run `nvm use 22`.
- Dashboard says backend unavailable: confirm the backend terminal is running on port 8000 and `.env.local` points to `http://127.0.0.1:8000/api/v1`.
- Binance REST/WebSocket unavailable: test normal internet/DNS access; public endpoints do not require an API key, but regional network restrictions, service limits or exchange availability can still prevent access.
- Probabilities suppressed: inspect `gate_failures` and fold/regime diagnostics, fetch more historical data, or choose a longer timeframe. Do not weaken the evidence gate to force a probability.

## Data safety

No buy/sell orders are sent. No exchange API secret is needed. SQLite candles are local to this installation. Stop the backend cleanly before copying or backing up its SQLite database. News remains demo data, metals are not yet supported by the historical OHLC research engine, and the broad USD macro series remains a proxy rather than ICE DXY.

## 7. Start prospective paper observation capture

The recorder can be user-triggered or scheduled. To enable scheduled capture, configure `PAPER_RECORDER_ENABLED=true` in `backend/.env` as described in section 3, then restart the backend. The worker is disabled by default, requires `DATA_MODE=binance`, and must run in a single Uvicorn process. Check its state and audit history with:

```bash
curl "http://127.0.0.1:8000/api/v1/market/research/paper/automation/status" | python3 -m json.tool
curl "http://127.0.0.1:8000/api/v1/market/research/paper/automation/runs?limit=10" | python3 -m json.tool

# Optional manual capture remains available:
curl -X POST "http://127.0.0.1:8000/api/v1/market/research/paper/observe?symbol=BTCUSDT&interval=1h" | python3 -m json.tool

curl "http://127.0.0.1:8000/api/v1/market/research/paper/observations?symbol=BTCUSDT&interval=1h&limit=100" | python3 -m json.tool

curl "http://127.0.0.1:8000/api/v1/market/research/paper/summary?symbol=BTCUSDT&interval=1h" | python3 -m json.tool
```

You can also use **Paper Research Recorder** in the dashboard. Scheduled cycles run at the configured cadence; duplicate structure events are ignored. This is not connected to a broker, does not place orders, and now applies configurable OHLC-based fee, spread and slippage assumptions for a separate execution scenario; it is not a broker emulator and cannot establish actual fills. The write endpoint should not be exposed on a public VPS until authentication and rate-limiting are added.


## 8. Configure and review cost-aware paper execution

The paper execution simulator is a local, deterministic OHLC scenario. It uses per-trade settings stored with each observation. The `.env.example` defaults are placeholders and should be adjusted only to documented venue/account assumptions:

```ini
PAPER_EXEC_FEE_BPS_PER_SIDE=10.0
PAPER_EXEC_FULL_SPREAD_BPS=4.0
PAPER_EXEC_SLIPPAGE_BPS_PER_SIDE=2.0
PAPER_EXEC_ENTRY_DELAY_BARS=0
PAPER_EXEC_POSITION_NOTIONAL_QUOTE=1000.0
PAPER_EXEC_ENTRY_REJECTION_RATE_PCT=0.0
PAPER_EXEC_REJECTION_SEED=marketmind-paper-v1
```

One basis point (bps) is 0.01%. The spread setting is the full spread; half is charged on each side. Fee and slippage are per side. `PAPER_EXEC_ENTRY_DELAY_BARS=0` means entry at the next eligible candle open; a value of 1 waits one additional full candle before entry. The notional is a fixed quote-currency exposure used to express P&L, not a wallet allocation or leverage setting. The rejection rate optionally creates repeatable synthetic rejected-entry scenarios and is not measured from exchange data.

Review the assumption snapshot and performance report:

```bash
curl "http://127.0.0.1:8000/api/v1/market/research/paper/executions/assumptions" | python3 -m json.tool
curl "http://127.0.0.1:8000/api/v1/market/research/paper/executions?symbol=BTCUSDT&interval=1h&limit=100" | python3 -m json.tool
curl "http://127.0.0.1:8000/api/v1/market/research/paper/executions/summary?symbol=BTCUSDT&interval=1h" | python3 -m json.tool
```

Target-touch fills are assumed, and fixed spread/slippage are not observed order-book values. Short-side results are synthetic and omit borrow/funding/margin/liquidation. Sequential trade drawdown is not portfolio drawdown. No probability publication or order submission is enabled by this feature.


## 9. Review portfolio capital and overlap simulation

The portfolio simulator combines all eligible Binance-sourced settled and currently open cost-aware paper executions by default. It uses hypothetical portfolio settings, not a live exchange account. Add or adjust these settings in `backend/.env` only as documented research scenarios:

```ini
PAPER_PORTFOLIO_INITIAL_CAPITAL_QUOTE=10000.0
PAPER_PORTFOLIO_RISK_PER_TRADE_PCT=1.0
PAPER_PORTFOLIO_MAX_OPEN_RISK_PCT=3.0
PAPER_PORTFOLIO_MAX_GROSS_EXPOSURE_PCT=100.0
PAPER_PORTFOLIO_MAX_POSITION_EXPOSURE_PCT=25.0
PAPER_PORTFOLIO_MAX_CONCURRENT_POSITIONS=3
```

The default is a 10,000 USDT hypothetical account, 1% target risk budget per entry, 3% maximum aggregate open stop risk, 100% gross exposure, 25% per-position exposure and three concurrent positions. Position notional is dynamically risk-sized using the current realized equity and the entry-to-stop distance, then constrained by all caps; the actual risk allocated can be lower than the 1% target when an exposure cap binds. Simultaneous entries share gross-exposure and open-risk capacity pro rata. When entries and exits share a candle timestamp, entries are processed first; this avoids assuming an intrabar exit frees capital before the new entry.

Query the portfolio-wide report:

```bash
curl "http://127.0.0.1:8000/api/v1/market/research/paper/portfolio/summary" | python3 -m json.tool
```

Optional filters for one supported symbol/timeframe:

```bash
curl "http://127.0.0.1:8000/api/v1/market/research/paper/portfolio/summary?symbol=BTCUSDT&interval=1h" | python3 -m json.tool
```

The API reports accepted and rejected entries, rejection reasons, realized P&L/return, max realized drawdown, concurrent positions, peak/current gross exposure and open stop risk. Current open paper executions reserve simulated exposure but are not counted as realized trades. The equity curve and drawdown use realized P&L only and do not include mark-to-market loss while positions are open. Cross-market correlation, margin, liquidation, borrow/funding, order-book execution and actual account constraints are not modelled. The feature generates no probabilities, recommendations or orders; it does not authorize live trading.


## 10. Review mark-to-market, correlation and stress analytics (v0.13.0)

The existing portfolio summary now includes a `mark_to_market` object and separate marked-equity fields. It uses the latest cached closed Binance Spot candles and will withhold aggregate marked equity if any open position has a stale or missing mark. Correlations are computed for the tracked BTC/ETH/SOL universe by timeframe, using synchronized returns with a 30-observation minimum.

Query the expanded portfolio report:

```bash
curl "http://127.0.0.1:8000/api/v1/market/research/paper/portfolio/summary" | python3 -m json.tool
```

Inspect `mark_to_market.positions`, `mark_to_market.correlation_by_interval`, `mark_to_market.stress_scenarios`, `estimated_marked_equity_quote`, and `estimated_marked_return_on_initial_capital_pct`. A `null` marked-equity value is intentional when marks are stale or incomplete; do not substitute realized equity and call it marked equity. Stress scenarios are instantaneous linear shocks, not forecasts or liquidation tests.

## v0.14.0 operational setup

### Configure write protection and alerts

Copy the new `.env.example` values into your existing `backend/.env`. For a VPS, set `APP_ENV=production` and generate a unique API key:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Set the result as `API_ACCESS_KEY`. Production startup refuses to run without it. Requests that modify data under `/api/v1` must include `X-API-Key: <your-key>`. Keep the key out of source control and never paste it into support logs. The API key is not needed for read-only dashboard endpoints.

For Telegram, create a bot using Telegram's BotFather, obtain the chat ID, and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Alternatively configure SMTP using `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_TO`, and optional credentials. Telegram and email are optional; without credentials, monitoring still runs and the diagnostics endpoint remains available. Alerts are deduplicated per issue using `ALERT_COOLDOWN_SECONDS`.

Check diagnostics at `http://127.0.0.1:8000/api/v1/health/diagnostics`. Candle freshness checks use stored Binance candles for BTCUSDT, ETHUSDT and SOLUSDT on 1h, 4h and 1d. A missing interval is reported as a warning, not proof that the entire exchange feed is down.

### Verify and restore SQLite backups

Run from the backend directory with its virtual environment active:

```bash
python scripts_backup_db.py --destination ./backups --retain 14
```

The script takes a consistent online SQLite backup (including committed WAL state), checks it with `PRAGMA integrity_check`, and only then publishes the backup file. To verify a backup manually:

```bash
python -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute("PRAGMA integrity_check").fetchone()[0]); c.close()' ./backups/marketmind-YYYYMMDDTHHMMSSZ.db
```

For restore, stop the API first, preserve the current database, then copy the verified backup to the configured `CANDLE_DB_PATH` (default `backend/data/marketmind.db`). Restart the API and check diagnostics. Keep backups off the VPS as well; a local backup does not protect against VPS or disk loss.

### VPS service and HTTPS

The `deploy/` directory contains a single-worker systemd service, daily backup timer, and Caddy reverse-proxy example. Review and adapt the paths and the `marketmind` service account before installation. Keep Uvicorn bound to `127.0.0.1`; expose HTTPS through Caddy only. Do not publicly expose port 8000, SQLite, Postgres, or Redis. Configure firewall rules to allow SSH and HTTPS only. The supplied in-memory write rate limiter is single-process; if you change to multiple workers, configure rate limiting in Caddy or another reverse proxy.

The detailed diagnostics endpoint includes local database path and disk capacity. Restrict it at the reverse proxy or firewall if the API is publicly reachable. The included Caddyfile is a starting point, not a complete authentication/authorization policy for a public multi-user product.


## Enable AllTick WebSocket streaming (optional)

In `backend/.env`, keep `DATA_MODE=alltick` and configure:

```ini
ALLTICK_API_KEY=your_private_token
ALLTICK_WS_ENABLED=true
ALLTICK_WS_SUBSCRIPTION=trade
ALLTICK_WS_SYMBOLS=BTCUSDT,XAUUSD,XAGUSD
ALLTICK_WS_HEARTBEAT_SECONDS=10
ALLTICK_WS_STALE_SECONDS=45
ALLTICK_WS_RECONNECT_MAX_SECONDS=60
```

Choose `trade` for latest trade ticks or `depth` for order-book snapshots. AllTick documents one active subscription per connection, so these modes cannot be active simultaneously. The free tier documentation lists one WebSocket connection and up to five products. Verify current entitlement and exact product codes in your account. The stream remains disabled by default.

After restarting the backend, inspect `http://127.0.0.1:8000/api/v1/market/stream`. The dashboard includes an AllTick stream monitor. `feed_freshness=STALE` or a growing reconnect count indicates that live streaming is not healthy. AllTick K-line push is documented as unsupported; historical OHLCV remains REST-sourced.


## v0.18.0 cross-provider data quality

When running `DATA_MODE=alltick`, the service starts independent Binance Spot and XAUS indicative metals feeds as reference sources. Configure the following in `backend/.env` (defaults are suitable for a first run):

```ini
DATA_QUALITY_ENABLED=true
DATA_QUALITY_POLL_SECONDS=30
DATA_QUALITY_MAX_QUOTE_AGE_SECONDS=90
TICK_STORAGE_ENABLED=true
TICK_STORAGE_MIN_INTERVAL_SECONDS=1
TICK_STORAGE_RETENTION_DAYS=14
```

Inspect `/api/v1/market/data-quality`, `/api/v1/market/data-quality/comparisons`, and `/api/v1/market/data-quality/observations`. Cross-provider validation requires fresh quotes from both sides. A missing comparison is not evidence that either provider is malfunctioning. Crypto compares AllTick with Binance Spot; XAU/XAG compares AllTick with XAUS indicative spot. These are not guaranteed identical instruments or executable quotes. Provider histories remain separate.


## v0.19.0 execution microstructure

To collect order-book depth instead of trade ticks, configure the AllTick stream as follows (the provider permits one subscription mode per connection):

```ini
DATA_MODE=alltick
ALLTICK_WS_ENABLED=true
ALLTICK_WS_SUBSCRIPTION=depth
ALLTICK_WS_SYMBOLS=BTCUSDT,XAUUSD,XAGUSD
TICK_STORAGE_ENABLED=true
TICK_STORAGE_MIN_INTERVAL_SECONDS=1
TICK_STORAGE_RETENTION_DAYS=14
```

Restart the backend and allow depth snapshots to arrive. Then inspect `GET /api/v1/market/microstructure/BTCUSDT`, `GET /api/v1/market/microstructure/BTCUSDT/history`, or `GET /api/v1/market/microstructure/BTCUSDT/estimate?side=buy&quantity=0.01`. The sweep estimator is a hypothetical walk of one stored visible-depth snapshot, not an execution.
