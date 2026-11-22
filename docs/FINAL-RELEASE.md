# MarketMind AI 1.0.0 — Final Research Platform Release

## Release decision

This release freezes feature development and consolidates the research platform delivered through v0.19.0. It is a **completed research and paper-analysis application**, not a validated or production-authorized automated trading system.

The final release includes:
- FastAPI backend and Next.js dashboard.
- Binance public crypto market data and optional AllTick REST/WebSocket integration.
- Indicative XAUS metals quotes and public macro/news context with explicit source caveats.
- Provider-separated candle histories, cross-provider quality diagnostics and sampled observations.
- SMC structure annotations, explainable strategy evidence, historical backtests and strict walk-forward diagnostics.
- Prospective paper observations, cost-aware OHLC execution scenarios, portfolio risk scenarios and mark-to-market estimates.
- Order-book snapshot analytics and visible-depth sweep estimates.
- Operational diagnostics, optional alerts, SQLite backup utility, deployment templates and a deployment preflight script.

## Explicit non-goals

- No broker/exchange order placement, API trading keys, live automation or account connectivity.
- No claim that any strategy is profitable.
- No automatic publication of unvalidated probabilities. Historical probabilities remain subject to all declared walk-forward, calibration, baseline, uncertainty and regime gates; a historical pass does not authorize live probabilities.
- No assumption that indicative metals prices are executable XAUUSD/XAGUSD broker prices.
- No merging of Binance and AllTick candles into a common research series.
- No claim that a single order-book snapshot predicts actual fills.

## Release verification in the build environment

- Backend tests: 130 passed.
- Python compilation: passed.
- FastAPI route registration: checked during release validation.
- Frontend TypeScript/TSX syntax transpilation: checked; full Next.js production build was not run in this environment.
- ZIP integrity and exclusion of `.env`, SQLite database files and dependency caches: checked.

## Required acceptance tests on the user's machine

1. Install into a new directory and restore the SQLite database from a clean backup.
2. Run `python scripts_preflight.py` and resolve all failures and relevant warnings.
3. Start API and frontend; verify `/api/v1/health`, `/api/v1/health/diagnostics`, dashboard load and browser console.
4. Verify actual provider authentication and symbol entitlements. AllTick requires the user's own token; a mocked test is not live connectivity verification.
5. Verify feed freshness, timestamp sanity, reconnect behaviour and cross-provider comparisons over a supervised period.
6. Run a new walk-forward study on the user's actual candle history. Preserve suppressed probabilities when any gate fails.
7. Run and restore a database backup; verify `PRAGMA integrity_check` on the restored copy.
8. If deploying to a VPS, configure HTTPS, firewall, API key, restricted CORS, offsite backups, monitoring and a single worker for in-process schedulers.

## Known limitations that remain open

- Full frontend production build and deployment-specific browser testing are not verified here.
- Live authenticated AllTick connectivity, entitlements, WebSocket soak testing and real provider uptime are not verified without the user's token and runtime.
- XAUS is an indicative reference source, not a broker execution feed.
- News categories are keyword heuristics; event returns are descriptive associations, not causal inference.
- Microstructure sweep estimates use one visible-depth snapshot and omit queue priority, cancellations, hidden liquidity, latency evolution and matching-engine rules.
- OHLC paper execution cannot reproduce intrabar order paths, actual bid/ask fills, queue position or venue-specific partial fills.
- Short-side borrow, funding, margin and liquidation are not fully modelled.
- SQLite and in-process rate limiting/schedulers are intended for a modest single-instance deployment. Multi-replica operation needs shared database/locking/rate limiting architecture.
- User accounts, roles, billing, and multi-tenant isolation are not implemented.

## Change policy after 1.0.0

Only correctness, security, dependency, compatibility and operational fixes should be accepted without reopening the research protocol. New strategy features require a separate specification, test plan and independent out-of-sample validation. Any change affecting data normalization, labels, fills, costs or features requires a new research version and re-validation.
