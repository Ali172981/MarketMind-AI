# Development roadmap

## v1.0.0 — Strategy Intelligence Engine (implemented)
- Explainable multi-timeframe confluence engine with separate long/short evidence scores.
- SMC structure, recent breaks, liquidity sweeps, open FVG proximity, EMA trend, RSI, ATR and relative volume.
- News headlines remain non-directional context.
- Evidence score is not a probability; validated probabilities remain suppressed.
- Next: prospective setup journaling, outcome attribution, strategy comparison and drift monitoring before considering calibrated probabilities.

# Development roadmap

1. Phase 1: local foundation, API, dashboard, demo stream.
2. Phase 2: real market feeds and normalized persistence.
3. Phase 3: news and economic calendar ingestion.
4. Phase 4: technical structure and macro analytics.
5. Phase 5: AI scenario engine and calibrated reversal research.
6. Phase 6: Telegram, email and push alerts.
7. Phase 7: VPS deployment, monitoring, Android and desktop packaging.

## Milestone 8 — model diagnostics and prospective observation log (v0.9.0)

Completed:
- Explicit positive-class/outcome audit and score-order diagnostics using ROC AUC on train, calibration and test partitions.
- Train-only feature orientation with test-period marginal diagnostics and coefficient stability summaries.
- Same-fold transparent comparisons: constant training target rate, direction-frequency prior, event-type-frequency prior and full SMC logistic model.
- Challenger promotion remains prohibited on the same test folds; new model selection requires a newly reserved future holdout.
- SQLite prospective SMC observation recorder with latest-closed-candle capture, deduplication, next-open hypothetical entry, future-bar settlement and conservative STOP-first same-bar handling.
- REST API and dashboard view for observation collection and outcome review.

Still outstanding before any live-trading consideration:
- Automated unattended recorder scheduling (implemented in Milestone 9; live VPS soak test and supervised restart validation remain outstanding).
- Paper execution model including realistic spread, fees, slippage, latency and rejected orders.
- Separate untouched future holdout after protocol and model freeze.
- Drift monitoring, model versioning and independent release review.
- Authentication, rate-limiting and access controls before exposing write endpoints on a public VPS.


## Milestone 9 — scheduled prospective paper observations (v0.10.0)

Completed:
- Optional FastAPI-lifespan polling worker, disabled by default and gated on `DATA_MODE=binance`.
- Configurable asset, timeframe, polling cadence and history window; default is BTCUSDT/ETHUSDT/SOLUSDT on 1h candles.
- Provider identity, closed-candle, minimum history and data freshness checks before recording.
- Per-pair failure isolation and persisted SQLite audit history for each collection cycle.
- Read-only automation status and run-history API plus dashboard status display.
- Single-process deployment requirement documented; duplicate event protection remains idempotent at the database level.

Still outstanding:
- Live VPS soak test and supervised deployment validation.
- Distributed scheduler lock if/when multiple API workers or replicas are required.
- Alerts for collector downtime/data staleness and backup/retention policy for the SQLite observation ledger.
- Realistic paper execution layer for spread, commission, slippage, latency and rejected orders; this is still separate from the current observation-only recorder.
- Authentication and rate-limiting before exposing write endpoints publicly.
- Separate future holdout and independent release review before any probabilities are eligible for release.


## Milestone 10 — cost-aware paper execution and performance (v0.11.0)

Completed:
- Immutable per-observation execution-assumption snapshots.
- Configurable taker fee per side, full spread, slippage per side, entry delay in bars and fixed quote notional.
- Reference-vs-fill price recording, adverse entry/exit price adjustments, gap-aware stop reference fills, STOP-first same-bar handling and target-touch fill disclosure.
- Gross/net P&L, separate cost decomposition, net return and net realized R.
- Execution ledger, summary/assumptions APIs and dashboard performance view.
- Legacy observation migration tagged as `MIGRATED_DEFAULT` rather than implying historical assumption capture.

Still outstanding before real venue simulation or live trading consideration:
- Replace fixed spread/slippage placeholders with timestamp-aligned observed bid/ask and market-depth data, or keep them as scenario assumptions with sensitivity bands.
- Add order-book depth, partial fills, queue position and empirically grounded order-rejection behavior (the current seeded rejection rate is only a stress scenario).
- Add explicit millisecond/second latency only when finer-grained market/trade data is available; OHLC bars cannot model sub-candle fill timing.
- Add instrument-specific short/margin/funding/borrow mechanics before treating synthetic shorts as executable.
- Add portfolio capital, overlapping position, exposure and equity-curve simulation; current sequential trade drawdown is not portfolio drawdown.
- Independent forward paper period, drift monitoring, supervised runtime soak test, authentication and public-endpoint rate limits.


## Milestone 11 — portfolio capital, overlap and equity curve (v0.12.0)

Completed:
- Portfolio-wide re-simulation of cost-adjusted Binance paper executions with configurable starting capital and dynamic risk-based sizing; the target per-trade risk budget can be reduced by binding exposure constraints.
- Per-trade exposure, aggregate gross-exposure, aggregate open-stop-risk and maximum-concurrent-position limits.
- Pro-rata capacity allocation across simultaneous entries; stable deterministic priority when concurrent-position slots are insufficient.
- Conservative entry-before-exit ordering at matching timestamps to avoid optimistic intrabar capital reuse.
- Current open positions reserve capacity; settled P&L and return are kept separate from open exposure.
- Portfolio realized-equity curve, max realized drawdown, win rate, profit factor, net P&L/return, peak/current exposure and rejection diagnostics.
- Read-only portfolio summary API and dashboard panel.

Still outstanding:
- Mark-to-market portfolio equity and intrabar risk require timestamp-aligned price marks and explicit gap/valuation policies.
- Cross-asset correlation, hedging/netting, contract multipliers, margin, liquidation, borrow and funding are not modelled.
- Portfolio limits are hypothetical and require a prospective paper period plus an independent review before any real account consideration.
- Live VPS soak test, SQLite backup/retention, API authentication and rate limiting remain outstanding.
- Live signal eligibility, probabilities and order submission remain disabled.


## Milestone 12 — mark-to-market and portfolio risk analytics (v0.13.0)

Completed:
- Latest closed Binance Spot candle marks for open portfolio positions with freshness/missing-mark status.
- Estimated net unrealized P&L and marked equity, kept separate from realized equity and withheld when any open position lacks a fresh mark.
- Cross-asset synchronized-return correlation matrices and per-asset realized/annualized volatility by timeframe.
- Linear parallel price-shock scenarios and adverse-to-each-position stress scenario.
- Dashboard visibility for marked positions, correlation, volatility and stress outcomes.

Still outstanding:
- Intrabar mark-to-market path and executable bid/ask marks from timestamp-aligned order-book/trade data.
- Correlation-aware portfolio sizing/netting only after independently validated methodology; current correlations are descriptive only.
- Margin, liquidation, funding, borrow, contract multipliers and account-specific risk.
- Live VPS soak testing, monitoring/alerting, SQLite backup/retention, authentication and rate limits before public deployment.
- Prospective paper evidence and independent release review; probabilities and live trading remain disabled.


## Milestone 13 — operational reliability (v0.14.0)

Implemented: diagnostics, optional Telegram/SMTP alerts, API write-key gate, single-process write rate limiting, verified SQLite backup/retention, and systemd/Caddy deployment examples. Remaining production work includes deployment-specific reverse-proxy policy, external/offsite backup destination, multi-process/shared rate limiting, user authentication/roles, and live notification delivery verification.


## Milestone 14 — news intelligence and market event analysis (v0.15.0)

Completed in this release:
- Public RSS ingestion from CoinDesk, Cointelegraph and Federal Reserve press releases with per-feed status and failure isolation.
- Source publication time, original source link, source name and ingestion timestamp stored separately.
- Normalized-title deduplication and tracking-parameter cleanup.
- Rule-based event categories and asset tags with an explicit non-directional `UNASSESSED` field.
- Descriptive pre/post closed-candle returns around a story publication time; results explicitly disclaim causal attribution.
- REST listing, feed status, manual refresh and event-reaction endpoints; optional periodic ingestion worker.

Still outstanding:
- Expand feed coverage only after source licensing, terms, stability and timestamp quality review.
- Add robust multilingual entity resolution and contextual classification with audited precision/recall before any ML interpretation.
- Build a properly specified event study with controls, confounder handling, multiple-testing correction and out-of-sample evaluation before claiming predictive value.
- Live RSS provider availability, frontend production build, VPS soak test and notification delivery require deployment-time verification.
- No news-derived trading probabilities, live signals or order submission are enabled.


## Milestone 15 — AllTick provider adapter (v0.16.0)

Completed:
- Optional AllTick REST latest-quote and K-line adapters for crypto and precious metals.
- Server-side API token configuration and provider status reporting.
- Free-tier pacing guard and conservative polling defaults based on the supplied repository documentation.
- Provider symbol/timeframe normalization and explicit missing-field/data-quality disclosures.
- Existing Binance and demo providers remain selectable.

Still outstanding:
- Configure a real AllTick token and verify authentication, account entitlements, and all five configured symbol codes.
- Compare AllTick timestamps and prices against independent sources over a supervised period.
- Implement WebSocket quote streaming only after confirming account permissions, subscription limits, heartbeat behavior and reconnect semantics.
- Keep historical research datasets source-segregated; do not mix Binance and AllTick candles in a single backtest without explicit provider/source controls.


## Milestone 16 — AllTick WebSocket streaming and feed diagnostics (v0.17.0)

Completed in this release:
- Opt-in AllTick WebSocket trade ticks and mutually exclusive order-book subscription mode, following the uploaded provider protocol documentation.
- Ten-second application heartbeat, reconnect/backoff, timestamp normalization, sequence checks and feed freshness/error diagnostics.
- Read-only stream status/order-book endpoint and stream-backed quote display when enabled.
- REST K-line history remains separate because the provider documentation states K-line push is unsupported.

Still outstanding:
- Authenticated live soak test and verification of product codes/entitlements with the user's AllTick account.
- Independent cross-provider price comparison and empirical spread/latency quality report.
- Persisted tick/order-book archive with explicit storage/retention policy; no ticks are currently written to candle history.
- Multi-process coordination and shared stream service if the API is deployed with multiple workers.


## v0.18.0 completed — Cross-provider data quality

- AllTick versus independent Binance/XAUS reference quote checks.
- Sampled AllTick tick and order-book midpoint storage with retention.
- Freshness and deviation diagnostics exposed through API/dashboard.
- No provider-price blending and no changes to paper execution eligibility.

Next: improve execution research using timestamp-aligned bid/ask observations only after live provider coverage and instrument comparability are verified.


## v0.19.0 completed — Execution microstructure

- Visible book spread, top-five bid/ask depth, imbalance, microprice and 10/25 bps depth metrics.
- Snapshot-based buy/sell depth sweep estimator with VWAP, slippage versus mid and partial-depth coverage.
- Historical snapshot metrics and dashboard component.
- Limitation: no venue queue model, latency replay, hidden liquidity, order cancellations, fees or real fill simulation. Requires AllTick depth subscription, which is mutually exclusive with trade ticks on the same documented connection.


## 1.0.0 — Final release and feature freeze

MarketMind AI is now considered feature-complete as a research-first application. Further work should be limited to correctness, security, compatibility, dependency and operational fixes unless a new research specification is approved. Any changes to features, labels, market-data normalization, execution assumptions or validation methodology require a new version and fresh out-of-sample evaluation. The open deployment acceptance items are listed in `docs/FINAL-RELEASE.md`; they require the operator's credentials, network and VPS and cannot be truthfully marked complete in this build environment.
