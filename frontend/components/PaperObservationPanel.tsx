"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

type Observation = {
  id: number;
  symbol: string;
  interval: string;
  event_time: number;
  event_type: string;
  direction: string;
  signal_close: number;
  status: string;
  entry_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  exit_price: number | null;
  outcome: string | null;
  created_at: string;
};

type Summary = {
  total_observations: number;
  by_status: Record<string, number>;
  settled_outcomes: Record<string, number>;
  probabilities_recorded: false;
  orders_submitted: false;
};

type Execution = {
  id: number;
  observation_id: number;
  symbol: string;
  interval: string;
  event_time: number;
  event_type: string;
  direction: string;
  status: string;
  assumption_source: string;
  entry_reference_price: number | null;
  entry_fill_price: number | null;
  exit_reference_price: number | null;
  exit_fill_price: number | null;
  exit_reason: string | null;
  gross_pnl_quote: number | null;
  total_cost_quote: number | null;
  net_pnl_quote: number | null;
  net_return_pct: number | null;
  realized_r: number | null;
  assumptions: {
    fee_bps_per_side?: number;
    full_spread_bps?: number;
    slippage_bps_per_side?: number;
    entry_delay_bars?: number;
    position_notional_quote?: number;
    entry_rejection_rate_pct?: number;
  };
};

type ExecutionStats = {
  trades: number;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  gross_pnl_quote: number;
  spread_cost_quote?: number;
  slippage_cost_quote?: number;
  fee_cost_quote?: number;
  total_cost_quote: number;
  net_pnl_quote: number;
  average_net_return_pct: number | null;
  aggregate_net_return_pct: number | null;
  average_realized_r: number | null;
  sequential_trade_drawdown_quote: number;
};

type ExecutionSummary = {
  total_simulations: number;
  by_status: Record<string, number>;
  overall: ExecutionStats;
  notice: string;
  current_default_assumptions: {
    fee_bps_per_side: number;
    full_spread_bps: number;
    slippage_bps_per_side: number;
    entry_delay_bars: number;
    position_notional_quote: number;
    entry_rejection_rate_pct?: number;
  };
};


type PortfolioSummary = {
  source_execution_rows: number;
  input_settled_or_open_trades: number;
  accepted_settled_trades: number;
  accepted_open_positions: number;
  rejected_trades: number;
  rejected_by_reason: Record<string, number>;
  wins: number;
  losses: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  initial_capital_quote: number;
  ending_realized_equity_quote: number;
  net_realized_pnl_quote: number;
  net_return_on_initial_capital_pct: number;
  max_realized_drawdown_quote: number;
  max_realized_drawdown_pct: number;
  peak_concurrent_positions: number;
  peak_gross_exposure_pct_of_equity: number;
  peak_open_stop_risk_pct_of_equity: number;
  current_open_positions: number;
  current_gross_exposure_quote: number;
  current_gross_exposure_pct_of_equity: number | null;
  current_open_stop_risk_quote: number;
  current_open_stop_risk_pct_of_equity: number | null;
  equity_curve: Array<{
    time: number | null;
    equity_quote: number;
    realized_drawdown_quote: number;
    realized_drawdown_pct: number;
    event: string;
  }>;
  configuration: {
    risk_per_trade_pct: number;
    max_open_risk_pct: number;
    max_gross_exposure_pct: number;
    max_position_exposure_pct: number;
    max_concurrent_positions: number;
  };
  notice: string;
  estimated_marked_equity_quote: number | null;
  estimated_marked_return_on_initial_capital_pct: number | null;
  mark_to_market: {
    as_of: string;
    status: string;
    open_position_count: number;
    marked_position_count: number;
    missing_mark_count: number;
    stale_mark_count: number;
    gross_unrealized_pnl_quote: number | null;
    estimated_net_unrealized_pnl_quote: number | null;
    positions: Array<{ execution_id: number; symbol: string; interval: string; direction: string; mark_status: string; mark_price: number | null; estimated_unrealized_pnl_quote: number | null; mark_age_seconds?: number }>;
    correlation_by_interval: Record<string, {
      symbols: string[];
      correlation: Record<string, Record<string, number | null>>;
      paired_return_observations: Record<string, Record<string, number>>;
      realized_volatility: Record<string, { annualized_realized_volatility_pct: number | null; return_observations: number }>;
    }>;
    stress_scenarios: Array<{ scenario: string; estimated_incremental_pnl_quote: number; interpretation: string }>;
    notice: string;
  };
  live_trading_eligible: false;
};

type Automation = {
  configuration?: {
    configured_enabled: boolean;
    enabled: boolean;
    blocked_reason: string | null;
    data_mode: string;
    symbols: string[];
    intervals: string[];
    poll_seconds: number;
  };
  runtime?: {
    state: string;
    started_at: string | null;
    last_cycle_at: string | null;
    last_error: string | null;
  };
  latest_run?: {
    id: number;
    status: string;
    finished_at: string;
    pairs_processed: number;
    pairs_total: number;
    observations_created: number;
    observations_advanced: number;
    observations_settled: number;
    errors: Array<{ symbol: string; interval: string; error: string }>;
  } | null;
};

function stamp(value: number) {
  return new Date(value * 1000).toLocaleString();
}

function price(value: number | null) {
  return value === null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function equityCurvePoints(points: PortfolioSummary["equity_curve"]) {
  if (points.length < 2) return "";
  const values = points.map((point) => point.equity_quote);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return values.map((value, index) => {
    const x = (index / Math.max(1, values.length - 1)) * 580 + 10;
    const y = 126 - ((value - min) / span) * 104;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

export default function PaperObservationPanel() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setIntervalValue] = useState("1h");
  const [items, setItems] = useState<Observation[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [executionSummary, setExecutionSummary] = useState<ExecutionSummary | null>(null);
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null);
  const [automation, setAutomation] = useState<Automation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("No prospective observation capture has been requested yet.");

  async function refreshAutomation() {
    const response = await fetch(`${API}/market/research/paper/automation/status`, { cache: "no-store" });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail ?? "Unable to load recorder automation status");
    setAutomation(body);
  }

  async function refresh() {
    const response = await fetch(
      `${API}/market/research/paper/observations?symbol=${symbol}&interval=${interval}&limit=100`,
      { cache: "no-store" }
    );
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail ?? "Unable to load paper observations");
    setItems(body.items ?? []);
    setSummary(body.summary ?? null);
    const executionResponse = await fetch(
      `${API}/market/research/paper/executions?symbol=${symbol}&interval=${interval}&limit=100`,
      { cache: "no-store" }
    );
    const executionBody = await executionResponse.json();
    if (!executionResponse.ok) throw new Error(executionBody.detail ?? "Unable to load paper execution results");
    setExecutions(executionBody.items ?? []);
    setExecutionSummary(executionBody.summary ?? null);
    const portfolioResponse = await fetch(
      `${API}/market/research/paper/portfolio/summary`,
      { cache: "no-store" }
    );
    const portfolioBody = await portfolioResponse.json();
    if (!portfolioResponse.ok) throw new Error(portfolioBody.detail ?? "Unable to load portfolio simulation");
    setPortfolioSummary(portfolioBody);
  }

  useEffect(() => {
    const load = () => {
      refresh().catch((err) => setError(err instanceof Error ? err.message : "Unable to load paper observations"));
      refreshAutomation().catch((err) => setError(err instanceof Error ? err.message : "Unable to load recorder status"));
    };
    load();
    const timer = window.setInterval(load, 30000);
    return () => window.clearInterval(timer);
    // Refresh is intentionally tied to the selected asset and timeframe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, interval]);

  async function capture() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        `${API}/market/research/paper/observe?symbol=${symbol}&interval=${interval}`,
        { method: "POST", cache: "no-store" }
      );
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Observation capture failed");
      await refresh();
      setNotice(
        `${body.recording?.observations_created ?? 0} new observation(s) recorded; ` +
        `${body.advancement?.settled ?? 0} prior observation(s) settled. ` +
        `${body.recording?.message ?? "No new latest-candle structure event."}`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Observation capture failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="section calibrationSection paperSection">
      <div className="sectionHeading">
        <div><p className="eyebrow">PROSPECTIVE OBSERVATION LOG</p><h2>Paper Research Recorder</h2></div>
        <span className="smallMuted">No probability · No order routing</span>
      </div>
      <div className="calibrationIntro">
        <strong>Observation-only policy</strong>
        <p>Records confirmed SMC structure events on the latest closed candle. A hypothetical next-candle-open entry is tracked against the defined stop, target and horizon as later closed bars arrive. This is not a broker simulation: no fills, execution costs, probabilities, recommendations or orders are created.</p>
      </div>
      <div className="backtestControls">
        <label>Market<select value={symbol} onChange={(e) => setSymbol(e.target.value)}><option>BTCUSDT</option><option>ETHUSDT</option><option>SOLUSDT</option></select></label>
        <label>Timeframe<select value={interval} onChange={(e) => setIntervalValue(e.target.value)}><option value="15m">15 minutes</option><option value="30m">30 minutes</option><option value="1h">1 hour</option><option value="2h">2 hours</option><option value="4h">4 hours</option><option value="1d">1 day</option></select></label>
        <button className="primaryButton" onClick={capture} disabled={loading}>{loading ? "Updating observations…" : "Capture latest closed-candle observation"}</button>
      </div>
      {error && <div className="error">{error}</div>}
      <p className="panelHint">{notice}</p>
      <div className="calibrationSubPanel">
        <div className="sectionHeading">
          <div><p className="eyebrow">UNATTENDED COLLECTION</p><h3>Recorder automation</h3></div>
          <span className="tag">{automation?.runtime?.state ?? "STATUS UNKNOWN"}</span>
        </div>
        <p className="panelHint">
          {automation?.configuration?.enabled
            ? `Scheduled collection is enabled for ${(automation.configuration.symbols ?? []).join(", ")} · ${(automation.configuration.intervals ?? []).join(", ")} · every ${automation.configuration.poll_seconds}s.`
            : automation?.configuration?.blocked_reason ?? "Scheduled collection is disabled by default. Enable it explicitly in backend/.env after confirming DATA_MODE=binance."}
        </p>
        {automation?.latest_run && <p className="smallMuted">
          Last cycle: {automation.latest_run.status} · {automation.latest_run.pairs_processed}/{automation.latest_run.pairs_total} market/timeframe pairs · {automation.latest_run.observations_created} new · {automation.latest_run.observations_settled} settled · {new Date(automation.latest_run.finished_at).toLocaleString()}
        </p>}
        {automation?.runtime?.last_error && <div className="error">{automation.runtime.last_error}</div>}
        {automation?.latest_run?.errors?.map((item, index) => <p className="smallMuted" key={`${item.symbol}-${item.interval}-${index}`}>{item.symbol} {item.interval}: {item.error}</p>)}
        <p className="smallMuted">To enable: set PAPER_RECORDER_ENABLED=true, DATA_MODE=binance, and configure PAPER_RECORDER_SYMBOLS / PAPER_RECORDER_INTERVALS in backend/.env, then restart the API. The worker is process-local; run a single Uvicorn worker.</p>
      </div>
      <div className="backtestMetrics calibrationMetrics">
        <article><span>Total observations</span><strong>{summary?.total_observations ?? 0}</strong></article>
        <article><span>Waiting for entry</span><strong>{summary?.by_status?.WAITING_FOR_ENTRY ?? 0}</strong></article>
        <article><span>Open observations</span><strong>{summary?.by_status?.OPEN ?? 0}</strong></article>
        <article><span>Settled observations</span><strong>{summary?.by_status?.SETTLED ?? 0}</strong></article>
        <article><span>Target outcomes</span><strong>{summary?.settled_outcomes?.TARGET ?? 0}</strong></article>
        <article><span>Stop / timeout</span><strong>{(summary?.settled_outcomes?.STOP ?? 0) + (summary?.settled_outcomes?.TIMEOUT ?? 0)}</strong></article>
      </div>
      <div className="calibrationSubPanel">
        <h3>Recorded structure observations</h3>
        <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Event time</th><th>Structure event</th><th>Direction</th><th>Signal close</th><th>Status</th><th>Entry</th><th>Stop</th><th>Target</th><th>Outcome</th></tr></thead><tbody>
          {items.map((item) => <tr key={item.id}>
            <td>{stamp(item.event_time)}</td><td>{item.event_type}</td><td>{item.direction}</td>
            <td>{price(item.signal_close)}</td><td>{item.status}</td><td>{price(item.entry_price)}</td>
            <td>{price(item.stop_price)}</td><td>{price(item.target_price)}</td><td>{item.outcome ?? "—"}</td>
          </tr>)}
          {items.length === 0 && <tr><td colSpan={9}>No observations yet. Capture an observation after a completed candle; a record is created only when a confirmed structure event occurs on that candle.</td></tr>}
        </tbody></table></div>
      </div>
      <div className="calibrationSubPanel">
        <div className="sectionHeading">
          <div><p className="eyebrow">COST-AWARE SIMULATION</p><h3>Paper execution and performance</h3></div>
          <span className="tag">OHLC PROXY · NO BROKER</span>
        </div>
        <p className="panelHint">Applies the fee, full-spread and slippage assumptions saved with each observation. Entry is the next eligible candle open after the configured bar delay. Stops are gap-aware and stop-first on same-bar ambiguity. A target touch is assumed filled at the target; OHLC data cannot confirm queue fills or partial fills.</p>
        <div className="backtestMetrics calibrationMetrics">
          <article><span>Settled simulations</span><strong>{executionSummary?.overall?.trades ?? 0}</strong></article>
          <article><span>Win rate after costs</span><strong>{executionSummary?.overall?.win_rate_pct == null ? "—" : `${executionSummary.overall.win_rate_pct.toFixed(1)}%`}</strong></article>
          <article><span>Net P&amp;L (USDT)</span><strong>{price(executionSummary?.overall?.net_pnl_quote ?? null)}</strong></article>
          <article><span>Total modeled costs</span><strong>{price(executionSummary?.overall?.total_cost_quote ?? null)}</strong></article>
          <article><span>Profit factor</span><strong>{executionSummary?.overall?.profit_factor == null ? "—" : executionSummary.overall.profit_factor.toFixed(2)}</strong></article>
          <article><span>Average net R</span><strong>{executionSummary?.overall?.average_realized_r == null ? "—" : executionSummary.overall.average_realized_r.toFixed(2)}</strong></article>
          <article><span>Entry rejections</span><strong>{executionSummary?.by_status?.ENTRY_REJECTED ?? 0}</strong></article>
        </div>
        {executionSummary?.current_default_assumptions && <p className="smallMuted">
          Current defaults: fee {executionSummary.current_default_assumptions.fee_bps_per_side} bps/side · full spread {executionSummary.current_default_assumptions.full_spread_bps} bps · slippage {executionSummary.current_default_assumptions.slippage_bps_per_side} bps/side · entry delay {executionSummary.current_default_assumptions.entry_delay_bars} bar(s) · notional {price(executionSummary.current_default_assumptions.position_notional_quote)} USDT · entry rejection stress {executionSummary.current_default_assumptions.entry_rejection_rate_pct ?? 0}%. Each new trade stores its own assumption snapshot.
        </p>}
        {executionSummary?.notice && <p className="smallMuted">{executionSummary.notice}</p>}
        <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Event time</th><th>Direction</th><th>Status</th><th>Assumptions</th><th>Entry ref / fill</th><th>Exit ref / fill</th><th>Exit</th><th>Gross P&amp;L</th><th>Costs</th><th>Net P&amp;L</th><th>Net R</th></tr></thead><tbody>
          {executions.map((trade) => <tr key={trade.id}>
            <td>{stamp(trade.event_time)}</td><td>{trade.direction}</td><td>{trade.status}</td><td>{trade.assumption_source}</td>
            <td>{price(trade.entry_reference_price)} / {price(trade.entry_fill_price)}</td>
            <td>{price(trade.exit_reference_price)} / {price(trade.exit_fill_price)}</td>
            <td>{trade.exit_reason ?? "—"}</td><td>{price(trade.gross_pnl_quote)}</td>
            <td>{price(trade.total_cost_quote)}</td><td>{price(trade.net_pnl_quote)}</td>
            <td>{trade.realized_r == null ? "—" : trade.realized_r.toFixed(2)}</td>
          </tr>)}
          {executions.length === 0 && <tr><td colSpan={11}>No cost-aware execution scenarios yet. New observations receive an execution-assumption snapshot and are simulated as subsequent closed candles arrive.</td></tr>}
        </tbody></table></div>
      </div>
      <div className="calibrationSubPanel">
        <div className="sectionHeading">
          <div><p className="eyebrow">PORTFOLIO CAPITAL &amp; OVERLAP</p><h3>Risk-sized portfolio simulation</h3></div>
          <span className="tag">RESEARCH ONLY · NO ACCOUNT</span>
        </div>
        <p className="panelHint">All symbols and timeframes are combined. Each settled execution is rescaled using the current portfolio equity and its entry-to-stop distance. Overlapping positions consume shared open-risk, gross-exposure and concurrent-position capacity. Same-timestamp entries are processed before exits to avoid assuming that an intrabar exit frees capital first.</p>
        <div className="backtestMetrics calibrationMetrics">
          <article><span>Starting capital (USDT)</span><strong>{price(portfolioSummary?.initial_capital_quote ?? null)}</strong></article>
          <article><span>Ending realized equity</span><strong>{price(portfolioSummary?.ending_realized_equity_quote ?? null)}</strong></article>
          <article><span>Net realized P&amp;L</span><strong>{price(portfolioSummary?.net_realized_pnl_quote ?? null)}</strong></article>
          <article><span>Net return on capital</span><strong>{portfolioSummary ? `${portfolioSummary.net_return_on_initial_capital_pct.toFixed(2)}%` : "—"}</strong></article>
          <article><span>Max realized drawdown</span><strong>{portfolioSummary ? `${portfolioSummary.max_realized_drawdown_pct.toFixed(2)}%` : "—"}</strong></article>
          <article><span>Portfolio win rate</span><strong>{portfolioSummary?.win_rate_pct == null ? "—" : `${portfolioSummary.win_rate_pct.toFixed(1)}%`}</strong></article>
          <article><span>Accepted / rejected</span><strong>{portfolioSummary ? `${portfolioSummary.accepted_settled_trades} / ${portfolioSummary.rejected_trades}` : "—"}</strong></article>
          <article><span>Current open positions</span><strong>{portfolioSummary?.current_open_positions ?? 0}</strong></article>
          <article><span>Peak concurrent positions</span><strong>{portfolioSummary?.peak_concurrent_positions ?? 0}</strong></article>
          <article><span>Peak gross exposure</span><strong>{portfolioSummary ? `${portfolioSummary.peak_gross_exposure_pct_of_equity.toFixed(1)}%` : "—"}</strong></article>
          <article><span>Peak open stop risk</span><strong>{portfolioSummary ? `${portfolioSummary.peak_open_stop_risk_pct_of_equity.toFixed(2)}%` : "—"}</strong></article>
          <article><span>Profit factor</span><strong>{portfolioSummary?.profit_factor == null ? "—" : portfolioSummary.profit_factor.toFixed(2)}</strong></article>
        </div>
        <div className="portfolioCurvePanel">
          <div className="portfolioCurveHeading"><strong>Realized equity curve</strong><span>USDT · closed P&amp;L only</span></div>
          {portfolioSummary && portfolioSummary.equity_curve.length > 1
            ? <svg className="portfolioEquityChart" viewBox="0 0 600 145" role="img" aria-label="Portfolio realized equity curve">
                <line x1="10" y1="126" x2="590" y2="126" stroke="currentColor" strokeOpacity="0.22" strokeDasharray="4 4" />
                <polyline points={equityCurvePoints(portfolioSummary.equity_curve)} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
              </svg>
            : <p className="smallMuted">The realized equity curve will appear after at least one eligible portfolio entry has settled.</p>}
        </div>
        <div className="portfolioCurvePanel">
          <div className="portfolioCurveHeading"><strong>Mark-to-market risk snapshot</strong><span>{portfolioSummary?.mark_to_market.status ?? "—"}</span></div>
          <div className="backtestMetrics calibrationMetrics">
            <article><span>Estimated marked equity</span><strong>{price(portfolioSummary?.estimated_marked_equity_quote ?? null)}</strong></article>
            <article><span>Estimated net unrealized P&amp;L</span><strong>{price(portfolioSummary?.mark_to_market.estimated_net_unrealized_pnl_quote ?? null)}</strong></article>
            <article><span>Fresh / stale / missing marks</span><strong>{portfolioSummary ? `${portfolioSummary.mark_to_market.marked_position_count} / ${portfolioSummary.mark_to_market.stale_mark_count} / ${portfolioSummary.mark_to_market.missing_mark_count}` : "—"}</strong></article>
            <article><span>Marked return on capital</span><strong>{portfolioSummary?.estimated_marked_return_on_initial_capital_pct == null ? "—" : `${portfolioSummary.estimated_marked_return_on_initial_capital_pct.toFixed(2)}%`}</strong></article>
          </div>
          {portfolioSummary?.mark_to_market.positions.length ? <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Asset</th><th>Side</th><th>Mark</th><th>Mark status</th><th>Unrealized net P&amp;L</th></tr></thead><tbody>
            {portfolioSummary.mark_to_market.positions.map((position) => <tr key={position.execution_id}><td>{position.symbol} · {position.interval}</td><td>{position.direction}</td><td>{price(position.mark_price)}</td><td>{position.mark_status}</td><td>{price(position.estimated_unrealized_pnl_quote)}</td></tr>)}
          </tbody></table></div> : <p className="smallMuted">No open positions to mark at this time.</p>}
        </div>
        {Object.entries(portfolioSummary?.mark_to_market.correlation_by_interval ?? {}).map(([tf, group]) => <div className="portfolioCurvePanel" key={tf}>
          <div className="portfolioCurveHeading"><strong>Cross-asset dependence · {tf}</strong><span>Pearson · synchronized closed returns</span></div>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Asset</th>{group.symbols.map((symbol) => <th key={symbol}>{symbol.replace("USDT", "")}</th>)}</tr></thead><tbody>
            {group.symbols.map((left) => <tr key={left}><td>{left}</td>{group.symbols.map((right) => <td key={right}>{group.correlation[left]?.[right] == null ? "Insufficient data" : group.correlation[left][right].toFixed(3)}</td>)}</tr>)}
          </tbody></table></div>
          <p className="smallMuted">Annualized realized volatility: {Object.entries(group.realized_volatility).map(([asset, value]) => `${asset.replace("USDT", "")} ${value.annualized_realized_volatility_pct == null ? "—" : `${value.annualized_realized_volatility_pct.toFixed(1)}%`}`).join(" · ")}.</p>
        </div>)}
        <div className="portfolioCurvePanel">
          <div className="portfolioCurveHeading"><strong>Instantaneous stress scenarios</strong><span>Linear price shocks · USDT</span></div>
          <div className="tableWrap"><table className="tradeTable"><thead><tr><th>Scenario</th><th>Estimated incremental P&amp;L</th></tr></thead><tbody>
            {(portfolioSummary?.mark_to_market.stress_scenarios ?? []).map((scenario) => <tr key={scenario.scenario}><td>{scenario.scenario.replaceAll("_", " ")}</td><td>{price(scenario.estimated_incremental_pnl_quote)}</td></tr>)}
            {!portfolioSummary?.mark_to_market.stress_scenarios.length && <tr><td colSpan={2}>Stress scenarios require fresh marks for every open position.</td></tr>}
          </tbody></table></div>
        </div>
        {portfolioSummary?.mark_to_market.notice && <p className="smallMuted">{portfolioSummary.mark_to_market.notice}</p>}
        {portfolioSummary && <p className="smallMuted">Configuration: risk/trade {portfolioSummary.configuration.risk_per_trade_pct}% · max open risk {portfolioSummary.configuration.max_open_risk_pct}% · max gross exposure {portfolioSummary.configuration.max_gross_exposure_pct}% · max single-position exposure {portfolioSummary.configuration.max_position_exposure_pct}% · max concurrent positions {portfolioSummary.configuration.max_concurrent_positions}. Current gross exposure: {price(portfolioSummary.current_gross_exposure_quote)} USDT ({portfolioSummary.current_gross_exposure_pct_of_equity == null ? "—" : `${portfolioSummary.current_gross_exposure_pct_of_equity.toFixed(1)}%`}); current open stop risk: {price(portfolioSummary.current_open_stop_risk_quote)} USDT.</p>}
        {portfolioSummary && Object.keys(portfolioSummary.rejected_by_reason).length > 0 && <p className="smallMuted">Rejected entries: {Object.entries(portfolioSummary.rejected_by_reason).map(([reason, count]) => `${reason.replaceAll("_", " ")}: ${count}`).join(" · ")}.</p>}
        {portfolioSummary?.notice && <p className="smallMuted">{portfolioSummary.notice}</p>}
      </div>
      <p className="calibrationFooter">The realized curve and separate mark-to-market snapshot are research estimates, not account equity or intrabar marks. Correlation is historical; stress scenarios are instantaneous linear shocks. Margin, liquidation, funding, borrow, partial fills, nonlinear market impact and actual account execution are not modelled. This does not approve any strategy for live trading. No probabilities, recommendations or orders are created.</p>
    </section>
  );
}
