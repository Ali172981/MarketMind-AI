"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

type BacktestResponse = {
  symbol: string;
  interval: string;
  data_status: string;
  source: string;
  backtest: {
    status: string;
    candles_analyzed: number;
    signals_found: number;
    metrics: null | {
      trades: number; win_rate_pct: number; net_profit: number;
      net_return_pct: number; profit_factor: number | string | null;
      average_net_r: number; max_drawdown_pct: number;
      starting_equity: number; ending_equity: number;
      estimated_costs_total: number;
    };
    trades: Array<{
      trade_number: number; direction: string; signal: string;
      entry_time: number; exit_time: number; entry_price: number;
      exit_price: number; exit_reason: string; net_pnl: number;
      net_r_multiple: number;
    }>;
    limitations: string[];
  };
};

function stamp(value: number) {
  return new Date(value * 1000).toLocaleString();
}

export default function BacktestPanel() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setIntervalValue] = useState("1h");
  const [historyLimit, setHistoryLimit] = useState("10000");
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function run() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API}/market/backtest/smc?symbol=${symbol}&interval=${interval}&limit=${historyLimit}`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Backtest request failed");
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to run backtest");
    } finally {
      setLoading(false);
    }
  }

  const m = result?.backtest.metrics;

  return (
    <section className="section backtestSection">
      <div className="sectionHeading">
        <div><p className="eyebrow">STRATEGY RESEARCH</p><h2>SMC Backtest Lab</h2></div>
        <span className="smallMuted">Historical simulation · No orders placed</span>
      </div>
      <div className="backtestControls">
        <label>Market<select value={symbol} onChange={(e) => setSymbol(e.target.value)}><option>BTCUSDT</option><option>ETHUSDT</option><option>SOLUSDT</option></select></label>
        <label>Timeframe<select value={interval} onChange={(e) => setIntervalValue(e.target.value)}><option value="15m">15 minutes</option><option value="30m">30 minutes</option><option value="1h">1 hour</option><option value="2h">2 hours</option><option value="4h">4 hours</option><option value="1d">1 day</option></select></label>
        <label>History<select value={historyLimit} onChange={(e) => setHistoryLimit(e.target.value)}><option value="5000">5,000 candles</option><option value="10000">10,000 candles</option><option value="20000">20,000 candles</option></select></label>
        <button className="primaryButton" onClick={run} disabled={loading}>{loading ? "Fetching history & running…" : "Run backtest"}</button>
      </div>
      {error && <div className="error">{error}</div>}
      {!result && <p className="panelHint">Run a historical SMC structure-break simulation. Larger history selections are fetched in public REST pages and saved locally. Default assumptions: next-candle entry, 1.5 ATR stop, 2R target, 1% risk per trade, 5 bps fee and 2 bps slippage per side.</p>}
      {result && result.backtest.status === "INSUFFICIENT_DATA" && <div className="empty">{result.backtest.message}</div>}
      {m && <>
        <div className="backtestMeta">{result?.symbol} · {result?.interval} · {result?.data_status} · {result?.backtest.candles_analyzed} candles · {result?.backtest.signals_found} structure events</div>
        <div className="backtestMetrics">
          <article><span>Net return</span><strong className={m.net_return_pct >= 0 ? "positive" : "negative"}>{m.net_return_pct.toFixed(2)}%</strong></article>
          <article><span>Win rate</span><strong>{m.win_rate_pct.toFixed(1)}%</strong></article>
          <article><span>Profit factor</span><strong>{m.profit_factor ?? "—"}</strong></article>
          <article><span>Max drawdown</span><strong className="negative">{m.max_drawdown_pct.toFixed(2)}%</strong></article>
          <article><span>Trades</span><strong>{m.trades}</strong></article>
          <article><span>Average net R</span><strong>{m.average_net_r.toFixed(2)}R</strong></article>
        </div>
        <div className="backtestMeta">Starting equity: ${m.starting_equity.toFixed(2)} · Ending equity: ${m.ending_equity.toFixed(2)} · Estimated costs: ${m.estimated_costs_total.toFixed(2)}</div>
        <div className="tableWrap"><table className="tradeTable"><thead><tr><th>#</th><th>Side</th><th>Signal</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Net P&amp;L</th><th>Net R</th></tr></thead><tbody>
          {result.backtest.trades.slice(-20).reverse().map((trade) => <tr key={trade.trade_number}><td>{trade.trade_number}</td><td>{trade.direction}</td><td>{trade.signal}</td><td>{stamp(trade.entry_time)}</td><td>{stamp(trade.exit_time)}</td><td>{trade.exit_reason}</td><td className={trade.net_pnl >= 0 ? "positive" : "negative"}>${trade.net_pnl.toFixed(2)}</td><td>{trade.net_r_multiple.toFixed(2)}R</td></tr>)}
        </tbody></table></div>
        <p className="panelHint">Showing the latest 20 trades. Costs and slippage are estimates. Intrabar order is unknown, so a bar touching both stop and target is counted as a stop. {result.backtest.limitations[0]}</p>
      </>}
    </section>
  );
}
