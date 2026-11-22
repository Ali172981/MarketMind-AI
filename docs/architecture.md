# Architecture notes — Phase 1

## Boundaries
- `market_data`: provider adapters and normalized market data.
- `api/routes`: HTTP and WebSocket transport.
- `schemas`: API contracts.
- `core`: configuration and cross-cutting concerns.
- `frontend`: dashboard presentation only; calculations belong in backend services.

## Data integrity rules
1. Every quote must carry provider/source, event timestamp and receive timestamp once live adapters are added.
2. Never label demo or delayed data as live.
3. News must retain publisher, original URL, publication timestamp and ingestion timestamp.
4. AI output must reference the evidence used to produce it.
5. A reversal score is not a probability until calibrated on out-of-sample historical data.

## Planned next steps
- Provider interface and Binance public WebSocket adapter for selected crypto pairs.
- Licensed XAUUSD/XAGUSD provider adapter.
- PostgreSQL schema and migrations.
- Redis caching and background workers.
- News ingestion with source verification and deduplication.


## Paper research and portfolio simulation boundaries
- `analysis/paper_observations.py`: causal SMC event observations and outcome settlement.
- `analysis/paper_execution.py`: per-observation cost-aware OHLC execution assumptions and net trade returns.
- `analysis/paper_portfolio.py`: portfolio-level risk sizing, exposure/concurrency constraints, overlap handling and realized-equity analytics. This is a derived research view over the execution ledger; it does not create broker orders or write a real account ledger.
- `api/routes/paper.py`: read-only portfolio summary route and existing paper recorder/execution routes.

Portfolio equity is realized-only. Mark-to-market valuation, cross-asset correlation, actual margin/liquidation mechanics and venue execution remain separate future work.
