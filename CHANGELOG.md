# Changelog

## 1.0.0 — Final research platform release

- Froze feature development after the v0.19.0 execution-microstructure milestone and consolidated the complete research workspace.
- Added an offline deployment preflight for provider configuration, production API-key policy, CORS, scheduler compatibility, SQLite integrity and disk capacity. It never prints secrets or contacts providers.
- Added final release acceptance criteria and an operator runbook covering startup, health checks, backup, restore, updates, VPS hardening and incident response.
- Aligned frontend package metadata and installation documentation with release 1.0.0.
- Final build validation: 130 backend tests passed; Python compilation and API route registration passed; frontend syntax transpilation passed. Full Next.js production build and authenticated provider/live VPS verification remain operator acceptance tasks.
- This release remains research-only: no broker order execution, no profitability claims, and no live probability authorization.

## Strategy Intelligence Engine (included in 1.0.0)
- Added explainable multi-timeframe strategy hypotheses combining EMA trend, RSI, ATR, relative volume, SMC structure, recent BOS/CHoCH, nearby open FVGs, liquidity sweeps and higher-timeframe structure.
- Added RSS headline context without using heuristic news direction to score setups.
- Added separate long/short evidence scores, supporting/opposing factors, provenance and reference invalidation/target levels.
- Added Strategy Intelligence dashboard panel.
- Explicitly keeps calibrated probabilities suppressed (`validated_probability: null`); evidence score is not a probability.


## 0.17.0 — Milestone 16: AllTick WebSocket streaming and feed diagnostics

- Added opt-in AllTick WebSocket trade-tick streaming using documented command 22004 subscription / 22998 push messages.
- Added optional order-book subscription mode using command 22002 / 22999, with normalized bid/ask levels, best bid/ask and spread estimates. Trade and depth are mutually exclusive per connection, matching the provider's one-active-subscription behavior.
- Added required application heartbeat every 10 seconds, receive timeout, bounded exponential reconnect, connection/message counters, provider timestamp normalization (seconds or milliseconds), sequence-order rejection and malformed/error-message isolation.
- Added `/api/v1/market/stream` diagnostics and WebSocket quote selection in `/api/v1/market/prices` when streaming is enabled.
- Kept REST K-line history separate: the supplied AllTick documentation marks K-line push as unsupported. No WebSocket tick is synthesized into OHLC candles.
- Default stream remains disabled until explicitly configured. Free-tier one-connection/five-product limits are disclosed; only one stream is opened.
- No live token was supplied; authenticated connectivity, account entitlement, symbol availability and production feed quality remain unverified. No probabilities or trading execution were enabled.

## 0.16.0 — Milestone 15: optional AllTick market-data integration

- Added an opt-in AllTick REST adapter for latest trade quotes and K-line history, using the documented forex/crypto/metals `/quote-b-api/v1` endpoints and server-side `X-API-Key` authentication.
- Added normalized mappings for BTCUSDT, XAUUSD (`GOLD`) and XAGUSD (`Silver`); ETHUSDT and SOLUSDT mappings are configurable in code but product availability must be verified against the provider's product list and account.
- Added provider-labelled quotes, timestamp normalization, K-line interval mapping, source persistence and API status diagnostics.
- Added conservative request pacing: at least 10 seconds between provider calls, a local 1,000-request/day process budget, and 90-second default quote polling to leave quota for manual history requests under the documented free-tier ceiling.
- Kept Binance and demo providers intact; AllTick is opt-in via `DATA_MODE=alltick` and `ALLTICK_API_KEY`.
- Explicitly disclosed REST polling rather than WebSocket streaming, no documented 24-hour change field, missing trade/taker-buy volume fields, 500-K-line request maximum, product-entitlement uncertainty, and non-broker-specific pricing.
- No token was supplied, so authenticated live provider connectivity and symbol entitlements remain unverified. No probabilities or live trading features were enabled.

# Changelog

## 0.13.0 — Milestone 12: mark-to-market and portfolio risk analytics

- Added latest closed Binance Spot candle marks for currently open portfolio positions, including mark timestamp/age and stale/missing status.
- Added estimated net unrealized P&L using allocated portfolio quantity, frozen entry fill assumptions, adverse estimated exit spread/slippage and two-sided fees.
- Added marked equity and marked return separately from realized equity; aggregate marked equity is withheld unless every open position has a fresh mark.
- Added BTC/ETH/SOL synchronized-return Pearson correlation matrices by timeframe, a minimum 30 paired observations, and per-asset realized/annualized volatility. Correlations are market diagnostics and are not used for risk netting.
- Added instantaneous parallel underlying shocks from -10% to +10% and a separate 2% adverse-to-each-position scenario.
- Added dashboard panels for open-position marks, unrealized P&L, correlation, volatility and stress scenarios.
- Disclosed candle-close proxy marks, historical-correlation instability, linear stress assumptions and exclusions for margin, liquidation, funding, borrow, nonlinear impact and actual execution.
- Preserved strict probability suppression, research-only status and disabled live trading/order submission.

## 0.12.0 — Milestone 11: portfolio capital, overlap and equity-curve simulation

- Added a portfolio-level simulation across all eligible Binance-sourced settled and currently open cost-aware paper executions.
- Added configurable initial capital, risk-per-trade sizing, aggregate open-stop-risk cap, gross-exposure cap, per-position exposure cap and maximum concurrent positions.
- Added pro-rata sharing of exposure and open-risk capacity among simultaneous entries; maximum-position slots use deterministic symbol/timeframe/id ordering.
- Entries at a timestamp are evaluated before exits at that timestamp, conservatively avoiding reuse of capital where intrabar OHLC ordering is unknown.
- Added entry sizing from current realized equity and entry-to-stop distance, realized portfolio P&L, return on initial capital, realized-equity drawdown, peak concurrent positions and exposure diagnostics.
- Added current open-position exposure/risk reservation and explicit exclusion/rejection reason reporting.
- Added read-only portfolio summary API and dashboard metrics. The existing per-trade execution ledger remains unchanged.
- Clearly labelled equity curve/drawdown as realized-only; unrealized mark-to-market, correlation netting, margin, liquidation, funding, borrow and venue execution remain outside scope.
- Preserved strict probability suppression, disabled live-trading eligibility and no-order guarantees.

## 0.11.0 — Milestone 10: cost-aware paper execution and performance measurement

- Added immutable per-observation snapshots of simulated fee, spread, slippage, bar-delay and notional assumptions.
- Added next-eligible-candle-open entry with configurable additional candle delay, modeled adverse entry/exit fills, two-sided taker fees and an optional deterministic entry-rejection stress scenario.
- Added gap-aware stop fills and stop-first treatment when stop and target both touch within one OHLC candle.
- Added explicit target-touch assumption: a candle touch is assumed filled at the target; OHLC cannot verify queue execution or partial fills.
- Added gross/net P&L, separate spread/slippage/fee costs, aggregate net return and net realized R.
- Added execution ledger, assumptions and performance-summary endpoints plus dashboard UI; demo/non-Binance source observations are explicitly blocked from simulation.
- Tagged legacy observations migrated using current defaults; preserved strict probability suppression and no-order safeguards.
- Explicitly disclosed synthetic short exposure and unmodelled borrow, funding, margin, liquidation, order-book impact, rejected orders and sub-candle latency.


## 0.10.0 — Milestone 9: scheduled prospective paper observations

- Added an optional asyncio scheduler managed by the FastAPI lifespan; disabled by default and explicitly enabled with `PAPER_RECORDER_ENABLED=true`.
- Added configurable symbol, interval, poll cadence and candle lookback settings. Defaults cover BTCUSDT, ETHUSDT and SOLUSDT on 1h candles.
- Added guards that require Binance-labelled data, at least 80 valid closed candles, and a fresh latest closed candle; forming, non-Binance and stale inputs are rejected.
- Each cycle advances waiting/open observations before recording newly confirmed events and isolates failures per market/timeframe pair.
- Added persistent SQLite run audit with status, processed pairs, new/advanced/settled observations, provider errors and result details.
- Added automation status and run-history endpoints and dashboard visibility.
- Documented single-Uvicorn-worker operation. Strict probability suppression remains unchanged; no probability, broker fill or order is generated.

## 0.9.0 — Milestone 8: model diagnostics and prospective paper observations

- Added explicit outcome-label semantic audit: `TARGET=1`; `STOP` and `TIMEOUT=0`.
- Added train/calibration/test score-order diagnostics (ROC AUC) and a non-positive Platt-slope investigation trail; test labels are never used to flip score direction.
- Added per-feature train-only orientation selection, out-of-sample marginal AUC, test-distribution shift and fold logistic-coefficient diagnostics.
- Added same-fold comparisons for constant training-rate, direction-frequency, event-type-frequency and full SMC logistic benchmarks. Challenger selection is explicitly prohibited on these same test windows.
- Added a SQLite prospective SMC observation recorder that captures only structure events on the latest closed candle, advances hypothetical next-open outcomes over future closed bars, and applies conservative same-bar STOP-first settlement.
- Added API endpoints and a dashboard panel for observation capture, status and outcome review.
- Paper observation records contain no probabilities and never submit orders. Collection is user-triggered; no hidden scheduler or broker execution is included.
- Bumped backend/frontend version to 0.9.0; strict probability suppression and disabled live signal eligibility remain unchanged.

## 0.8.0 — Milestone 7: strict walk-forward validation

- Replaced sample-gate-only probability publication with strict five-fold expanding-window walk-forward validation.
- Added label-boundary purging and 48-candle embargoes between training, calibration and test windows.
- Added fold-specific training-rate baselines, pooled Brier/log-loss acceptance criteria and a moving-block bootstrap confidence interval for Brier skill.
- Added causal trend/range regime labels and regime-sliced robustness gates.
- Added automatic suppression of all per-event probabilities whenever any publication requirement fails.
- Kept live signal eligibility permanently disabled; historical research pass is not a live signal approval.
- Updated API, dashboard, research protocol, Kali install guidance and build status.

## 0.7.1 — Reproducible research snapshots

- Added SHA-256 fingerprints of the exact normalized candle snapshot used by each study.
- Added explicit train/calibration/test time ranges to research reports.
- Added warnings that minimum sample gates are guardrails, Wilson intervals do not account for serial dependence, and repeated holdout tuning contaminates the test.
- Added an MIT license for the MarketMind AI project code. Provider data terms remain separate.

## 0.7.0 — Research validation and historical depth

- Added paginated Binance public Spot kline history backfill (up to 20,000 candles per request; 1,000 candles per REST page).
- Added causal SMC event outcome labels with next-candle-open entry, fixed ATR stop/target, same-bar STOP-first handling, and right-censoring.
- Added chronological train/calibration/untouched-test split and purged events whose label horizon crosses a boundary.
- Added standard-library L2 logistic model and Platt calibrator.
- Added initial sample-size and per-class gates, Brier score, training-rate baseline, log loss, ECE and Wilson interval.
- Added Out-of-Sample Probability Lab dashboard panel.

## 0.6.0 — Backtest baseline

- Added the deterministic SMC next-candle historical simulator with estimated costs, equity metrics, and trade ledger.

## 0.5.0 and earlier

- Added the SMC structure engine, FVG / liquidity analysis, and earlier market-data integrations.

## v0.14.0 — Operational reliability and deployment hardening

- Added detailed operational diagnostics for SQLite connectivity/integrity, Binance WebSocket state, stored candle freshness, and disk capacity (`GET /api/v1/health/diagnostics`).
- Added optional Telegram Bot API and SMTP email alerts with per-issue cooldown and recovery reset. No credentials are required for local development; secrets are read only from environment configuration.
- Added API-key protection for API write methods when `API_ACCESS_KEY` is configured, a single-process write-rate limiter, and a production startup guard requiring an API key.
- Added online SQLite backup utility using SQLite's backup API, `PRAGMA integrity_check`, atomic publication, and configurable retention.
- Added systemd service/timer templates and a Caddy reverse-proxy example for HTTPS VPS deployment. The API binds to loopback in the supplied service template.
- Operational checks and alerts are monitoring-only. They do not change strategy logic, research eligibility, probabilities, or submit orders.
- Rate limiting is in-memory and single-process; use a reverse-proxy limit for multi-worker deployments. The detailed health endpoint is intended for trusted operators and should be restricted at the proxy if exposed publicly.


## 0.18.0 — Cross-provider validation & tick storage

- Added a bounded SQLite observation store for sampled AllTick trade ticks and order-book midpoint observations, with configurable per-symbol sampling and retention.
- Added cross-provider quote comparisons: AllTick versus Binance Spot for crypto and AllTick versus XAUS indicative spot for gold/silver.
- Added quote freshness, absolute deviation in basis points, source timestamp skew, and screening statuses (WITHIN_BAND, WARNING, OUTLIER, STALE, INSUFFICIENT_DATA).
- In AllTick mode, independent Binance and XAUS reference feeds run alongside the selected AllTick feed; their data is not merged into AllTick history.
- Added API endpoints and dashboard visibility for comparison summaries, comparison history, and stored observations.
- All thresholds are heuristic screening bands, not universal fair-value limits or trade signals. Instrument/venue basis differences remain possible, especially for indicative metals quotes.


## 0.19.0 — Execution microstructure & visible-depth research

- Added order-book analytics and depth-aware sweep estimation from stored AllTick depth snapshots.
- Added endpoints for latest microstructure metrics, snapshot history and hypothetical buy/sell sweep estimates.
- Added dashboard microstructure panel.
- Explicitly reports stale books, crossed/invalid books and partial visible-depth coverage.
- No orders are sent; no actual execution or guaranteed fill is represented.
