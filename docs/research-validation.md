# MarketMind AI — Strict Research Validation Protocol v2

## 1. Research question and outcome label

For each confirmed SMC structure-break event, the model estimates a narrowly defined conditional probability: the configured take-profit is touched before the configured stop-loss within a fixed horizon.

Defaults:

- Signal: bullish or bearish BOS / CHoCH / initial structure break from the deterministic SMC engine.
- Feature timestamp: signal candle close.
- Entry: next candle open.
- Stop: 1.5 × simple ATR(14), computed using candles through the signal candle.
- Target: 2R relative to the initial stop distance.
- Horizon: 48 candles including the entry candle.
- Same-bar ambiguity: STOP first.
- TIMEOUT: negative label for this target-before-stop question; not necessarily a net losing trade.

The target is not a general bullish/bearish forecast and does not incorporate fees, spread, slippage, funding, borrow, market impact, taxes or execution failures.

## 2. Causal features and regime labels

The model uses five interpretable signal-time features:

1. Directional break distance divided by ATR.
2. Candle body divided by candle range.
3. Log current volume relative to the mean of the preceding 20 candles.
4. CHoCH indicator.
5. Direction-aligned three-candle FVG indicator ending on the signal candle.

All model features use information available no later than the signal candle close. Regime labels are also causal. The trailing 50-candle close-to-close return classifies each event as UPTREND (at least +1%), DOWNTREND (at most -1%), or RANGE (between those thresholds). A second volatility label compares current ATR(14) as a percentage of close against the mean of up to 200 preceding ATR-percent observations (excluding the current observation), producing HIGH_VOL or LOW_VOL after at least 20 prior observations. Regimes are descriptive slices, not additional model features.

## 3. Walk-forward design, purging and embargo

The controlling protocol in v0.8.0 uses five expanding-window folds. It does not randomly shuffle events.

- Initial training window: 35% of candle history.
- Training window expands by 10 percentage points for each subsequent fold.
- Calibration window: 15% of candle history, immediately after the training boundary except for the embargo.
- Test window: 10% of candle history, after the calibration window and its embargo.
- Fold test periods are chronological and non-overlapping.
- A 48-candle embargo is applied after the training boundary and after the calibration boundary. This default matches the maximum outcome horizon; custom research settings may change it, and the response records the actual value.
- Any event whose label end reaches or crosses its segment end is purged. Events whose signal occurs inside an embargo interval are excluded from that fold.
- Training labels are complete before the calibration segment; calibration labels are complete before the test segment. The calibrator is never fitted on a fold's test outcomes.

The test windows progress through the history. A later expanding fold may use older history that was a test period in an earlier fold, because that information would have been historically available by the later fold's training cutoff. The pooled OOS prediction sequence includes each test event only in its own chronological test window.

## 4. Per-fold sample and class-balance gates

Every fold must meet all of these minimums:

| Segment | Events | Target-first minimum | Stop/timeout minimum |
|---|---:|---:|---:|
| Train | 200 | 30 | 30 |
| Calibration | 100 | 20 | 20 |
| Test | 100 | 20 | 20 |

All five folds must complete their sample gates. A non-positive or non-finite Platt slope in any fold fails strict validation.

## 5. Model fitting and baseline

Within each fold:

- Feature means and scales are fitted using that fold's training segment only.
- L2-regularised logistic regression is fitted on training events only.
- A two-parameter Platt calibrator is fitted on calibration logits and labels only.
- Test predictions are generated only after model and calibrator fitting is complete.
- The benchmark is a constant probability equal to that fold's training target-first rate. This probability is fixed before the test outcomes are scored.

The implementation uses the Python standard library; it does not require a paid model service or third-party ML package.

## 6. Strict probability publication gates

Historical probability values are suppressed unless **all** conditions pass:

1. All five walk-forward folds meet event-count and class-balance requirements.
2. Every fold has a positive finite Platt slope.
3. At least four of five folds beat their fold-specific training-rate baseline on Brier score.
4. Pooled OOS Brier score beats the pooled fold-specific baseline.
5. Pooled OOS log loss beats the pooled fold-specific baseline.
6. The lower endpoint of a 95% moving-block bootstrap confidence interval for pooled Brier skill is strictly above zero. The default uses 500 deterministic bootstrap replicates and blocks of 10 sequential OOS events.
7. Pooled expected calibration error (ECE) is no greater than 0.10.
8. At least two trend regimes and at least two volatility regimes each have at least 50 OOS events and both outcome classes; every sufficiently populated group in both dimensions must beat its fold-specific training-rate baseline on Brier score.

A failed condition sets `probabilities_published=false`, `historical_probabilities_available=false`, and returns an empty `historical_oos_predictions` array. Fold-level aggregate metrics and failure explanations remain available for diagnosis, but raw per-event probability values are not returned.

A pass means only that historical OOS predictions met this predeclared research gate. It does **not** enable live signals: `live_signal_eligible` remains `false` regardless of historical results.

## 7. Metrics and uncertainty

The study reports:

- Brier score, fold-specific baseline Brier score and Brier skill.
- Log loss and fold-specific baseline log loss.
- Expected calibration error.
- Observed target-first rate and a nominal Wilson interval.
- Per-fold event counts, class counts, Platt slope, purged-event counts and embargoed-event counts.
- Regime-level sample counts and Brier skill where sample minimums are met.
- A moving-block bootstrap interval for pooled Brier skill, which preserves short blocks of event ordering rather than assuming every event is independent.
- A SHA-256 fingerprint of normalized OHLCV candles.

The block bootstrap is an uncertainty diagnostic; it does not eliminate all serial dependence, structural breaks, data-snooping or model-selection bias. The nominal Wilson interval does not adjust for event clustering.

## 8. Operational policy

- A failed gate suppresses all raw probability estimates in the API response and dashboard.
- A passed gate may expose historical walk-forward probabilities, clearly labelled as historical OOS estimates.
- Live alert and trading probability use remains disabled even after a historical pass.
- Prospective paper trading, cost-aware execution simulation, drift monitoring, and a separately reviewed release decision are still mandatory before any live alert can use a probability.
- Do not tune features, labels or thresholds repeatedly against the same walk-forward folds. Freeze the protocol before evaluating new data and retain a genuinely future holdout for subsequent model changes.

## 9. Interpretation

A historical estimate of 0.60 refers only to the chance that the configured target is touched before the configured stop within the specified horizon, conditional on the defined SMC event and feature set. It is not a 60% chance that the asset rises, a 60% chance of net profitability, or a forecast for the next live market event.


## 10. Milestone 8 diagnostic protocol and prospective observation log

### Label and score-direction audit

The study explicitly audits its outcome mapping: `TARGET` is positive class 1, while `STOP` and `TIMEOUT` are negative class 0. Any inconsistent event fails the publication gate. The current logistic model reports ROC AUC on training, calibration and test partitions. A test AUC below 0.5 is reported as an inverted score ordering, but test labels are never used to reverse or refit the score. A non-positive Platt slope remains a strict failure. Investigations must be formulated from training/calibration evidence and confirmed on a new untouched period.

### Feature investigation

For each feature, the univariate direction is selected from training-only AUC. That fixed orientation is then measured on the fold test partition. The report also shows feature distribution shift in training standard deviations and the standardized coefficient from the full logistic model. These are marginal diagnostics, not causal effects; correlated features and repeated comparisons can produce unstable apparent importance. No feature is automatically promoted or removed by this analysis.

### Transparent benchmarks

Each completed fold compares the full SMC logistic model with (a) the fold training-rate constant baseline, (b) a Laplace-smoothed direction-frequency benchmark, and (c) a Laplace-smoothed event-type-frequency benchmark. Categorical benchmark calibrators are fitted only on the calibration partition. All models are evaluated on the same test events. Results are diagnostic only. The best-looking challenger cannot be selected and reported as validated on the same folds used to compare it; a challenger requires a newly reserved future holdout after a protocol freeze.

### Prospective paper observation recorder

`POST /api/v1/market/research/paper/observe` advances existing observations with the current closed-candle history and records only confirmed SMC events whose event time equals the latest closed candle. Duplicate events are ignored. The recorder stores the event, causal signal-time feature values, ATR at observation and fixed outcome parameters. Once the following candle is available, its open is used as a hypothetical entry. Subsequent closed OHLC bars advance the observation until stop, target or horizon timeout. If stop and target are both touched inside one OHLC candle, STOP is assumed first.

In v0.9.0, capture was user-triggered. Since v0.10.0, an optional FastAPI-lifespan scheduler can poll configured Binance Spot markets, but it is disabled by default and must be explicitly enabled with `PAPER_RECORDER_ENABLED=true` while `DATA_MODE=binance`. It filters forming candles, rejects non-Binance/stale data, persists a run audit and requires a single Uvicorn worker. It is not connected to an exchange account and does not simulate execution fills, fees, spread, slippage, funding, borrow, market impact, rejected orders or latency. It records no probability and submits no order. Results are therefore prospective structural-event observations, not proof of paper-trading profitability.

### Release restrictions

Milestone 8 does not relax the v0.8.0 strict probability gates. Historical probability values remain automatically suppressed whenever the original requirements fail. The recorder is separate from the probability publication process, and `live_signal_eligible` remains false unconditionally.


## Milestone 10 — cost-aware OHLC paper-execution scenario

Each new observation receives an immutable `paper_execution_simulations` row containing the explicit assumptions used for its scenario. The current defaults are placeholders: 10 bps taker fee per side, 4 bps full spread, 2 bps slippage per side, zero additional candle-bar delay, 1,000 quote-currency notional and a 0% optional deterministic entry-rejection stress rate. These are not claims about a user's account fee tier, live spread or measured rejection rate. A nonzero entry-rejection percentage is a seeded deterministic stress scenario only. A historical observation created before this feature is assigned current defaults and tagged `MIGRATED_DEFAULT`. Cost-aware execution accepts only observations whose captured data source is Binance-labelled; demo/sample source records are blocked.

Signal observations use the first eligible candle open after the configured extra bar delay as the reference entry. Modeled fills move adversely by half the configured full spread plus per-side slippage. Fees are charged on both sides. The stop reference uses the stop level unless the bar opens beyond the stop, in which case the worse opening price is used; adverse spread and slippage are then applied. When both stop and target touch the same OHLC candle, STOP is assumed first. A target touch is assumed filled at the target with no price improvement; this is an explicit fill assumption because OHLC alone cannot establish queue priority or partial execution. An optional seeded hash can mark a configured percentage of simulated entries as rejected; this is a deterministic stress device, not an empirical venue-rejection model. Timeouts exit at the horizon candle close.

The API reports gross P&L, spread cost, slippage cost, fees, total cost, net P&L, net return and net realized R. Net realized R is net P&L divided by the reference entry-to-stop price risk (before execution costs); gaps can therefore produce losses beyond -1R. Performance aggregation includes win rate after modeled costs, profit factor, average return/R and sequential closed-trade drawdown. That drawdown is not portfolio drawdown: overlapping exposures, shared capital, netting and margin requirements are not simulated.

Short-side results are synthetic directional exposures calculated from Spot OHLC. They do not model borrow availability/rates, margin, liquidation or perpetual funding; they must not be interpreted as executable Binance Spot shorts. Fixed spread/slippage assumptions also do not model market depth, impact, partial fills, empirical order rejections or actual latency. Sub-candle execution delays cannot be inferred from hourly OHLC.

Endpoints: `GET /api/v1/market/research/paper/executions`, `/executions/summary`, and `/executions/assumptions`. No account credentials are used, no orders are created, no probabilities are added, and this layer does not change strict probability-publication gates.
