# MarketMind AI — Backtesting Methodology (v1)

## Baseline strategy simulation

The initial strategy simulator uses deterministic bullish/bearish structure-break events from the SMC engine. Swing points become available only after their configured right-hand confirmation bars. A signal is observed at the signal candle close and the simulated entry is the next candle open.

- Direction: bullish structure event = long; bearish structure event = short.
- Stop: 1.5 × ATR(14) measured using candles available at signal close.
- Target: 2 × initial risk (2R).
- Risk budget: 1% of simulated equity per trade.
- Holding limit: 48 bars.
- Estimated costs: default 5 bps fee + 2 bps slippage per side.
- Overlap: one position at a time.
- Same-bar ambiguity: stop is assumed to occur before target if both are touched.
- Only closed candles are included.

## Metrics

The report contains net equity return, win rate, profit factor, average net R, maximum equity drawdown, estimated costs, and a trade ledger. Equity sizing uses stop-distance risk, caps gross exposure at 1× simulated equity (no leverage), and deducts estimated transaction costs from P&L. When the exposure cap binds, effective risk is lower than the configured risk budget.

## Limitations

This is an initial benchmark, not an optimised or validated trading system. OHLC candles cannot reveal intrabar order. The model omits variable spreads, market impact, funding, borrow costs, taxes, outages and latency. Short trades are hypothetical research positions, not actual spot borrowing/margin execution. Costs are illustrative inputs, not current exchange fee quotes.

See [research-validation.md](research-validation.md) for the separate event-probability target, causal features, temporal splits, boundary purging and calibration gates.


## Portfolio overlay (v0.12.0)

The cost-adjusted execution ledger can be re-simulated through a portfolio allocator. It uses the configured initial portfolio capital and sizes each position from the current realized equity and the entry-to-stop distance. The resulting notional is capped by the per-position exposure limit, remaining gross-exposure capacity and remaining aggregate open-stop-risk capacity. A maximum concurrent-position count is enforced. Simultaneous entries share the available exposure/risk capacity pro rata; stable symbol/timeframe/id ordering is used when there are more simultaneous candidates than available position slots.

For conservatism, entries at a candle timestamp are allocated before exits at the same timestamp. This avoids assuming that an intrabar stop/target frees capital before another entry. Current open executions reserve simulated capacity but are not counted in realized performance. The equity curve updates at settled exits and the reported drawdown is realized-only, not mark-to-market account drawdown. The overlay scales each stored per-trade net return to its portfolio allocation, assuming the underlying percentage costs scale linearly with notional.

Default settings are 10,000 quote-currency units of starting capital, 1% risk-per-trade, 3% maximum aggregate open stop risk, 100% gross exposure, 25% max per-position exposure and three concurrent positions. These are research defaults, not recommendations. The portfolio overlay does not model correlation/netting, margin, leverage, liquidation, borrow, funding, contract multipliers, observed depth, partial fills or actual account constraints.


## Mark-to-market and market-risk overlay (v0.13.0)

The portfolio summary now adds an independent risk snapshot for open simulated positions. It uses the latest cached **closed Binance Spot candle close** for each symbol/timeframe. Forming, non-Binance, missing or stale marks cannot produce a complete marked-equity figure. Stale marks are flagged; if any open position lacks a fresh mark, aggregate estimated marked equity is withheld.

Estimated unrealized P&L scales each position to its portfolio allocation and applies the position's frozen entry fill, adverse estimated exit spread/slippage and two-sided fee assumptions. This remains a candle-close estimate, not an executable bid/ask valuation. Realized equity and realized drawdown remain separately reported.

Correlation matrices use synchronized close-to-close simple returns for BTCUSDT, ETHUSDT and SOLUSDT, grouped by timeframe. At least 30 paired returns are required. Realized volatility uses sample standard deviation and annualizes assuming 24/7 crypto trading. These are descriptive statistics only; they do not net exposures or assume future correlation stability.

Stress scenarios apply instantaneous linear parallel price shocks from -10% to +10%, plus a separate 2% adverse-to-each-position shock. These are not historical replays and omit nonlinear effects, gaps, margin, liquidation, funding, borrow, market impact and account execution.
