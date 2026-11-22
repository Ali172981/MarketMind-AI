"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];
const INTERVALS = ["15m", "30m", "1h", "2h", "4h", "1d"];

type Analysis = {
  status: string;
  candles_analyzed?: number;
  last_close?: number;
  structure?: { trend: string; latest_event?: { type: string; level: number; price: number; explanation: string } | null };
  liquidity?: { pools: Array<{ type: string; level: number; touches: number }>; latest_sweep?: { type: string; level: number; explanation: string } | null };
  fair_value_gaps?: Array<{ type: string; lower: number; upper: number; status: string }>;
  order_blocks?: Array<{ type: string; lower: number; upper: number; status: string }>;
  message?: string;
};
type Result = { interval: string; data_status: string; analysis?: Analysis; error?: string };
type Payload = { symbol: string; alignment: string; intervals: Result[]; note: string };

const fmt = (n?: number) => n === undefined ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: n > 100 ? 2 : 5 }).format(n);
const trendLabel = (trend?: string) => trend === "BULLISH" ? "Bullish" : trend === "BEARISH" ? "Bearish" : trend === "RANGE" ? "Range" : "Insufficient";

export default function SMCPanel() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [focus, setFocus] = useState("1h");
  const [payload, setPayload] = useState<Payload | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const intervals = [...new Set(["15m", focus, "4h"])].join(",");
    async function load() {
      try {
        const response = await fetch(`${API}/market/smc/multi-timeframe?symbol=${symbol}&intervals=${intervals}&limit=300`, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? "SMC analysis request failed");
        if (active) { setPayload(data); setError(""); setLoading(false); }
      } catch (e) {
        if (active) { setError(e instanceof Error ? e.message : "Unable to load SMC analysis"); setLoading(false); }
      }
    }
    setLoading(true);
    load();
    const timer = window.setInterval(load, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, [symbol, focus]);

  const focused = payload?.intervals.find(x => x.interval === focus)?.analysis;
  const allResults = payload?.intervals ?? [];

  return (
    <section className="smcPanel">
      <div className="smcHeader">
        <div>
          <p className="eyebrow">DETERMINISTIC PRICE-ACTION ENGINE</p>
          <h2>Smart Money Concepts</h2>
          <p className="chartSub">Confirmed swings · BOS / CHoCH · liquidity · FVG · candidate order blocks</p>
        </div>
        <div className="smcControls">
          <select value={symbol} onChange={e => setSymbol(e.target.value)} aria-label="SMC market">
            {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={focus} onChange={e => setFocus(e.target.value)} aria-label="Focus timeframe">
            {INTERVALS.map(t => <option key={t} value={t}>{t} focus</option>)}
          </select>
        </div>
      </div>

      {error && <div className="chartError">{error}</div>}
      <div className="smcAlignment">
        <div><span className="smallMuted">Multi-timeframe alignment</span><strong>{loading ? "Analysing…" : (payload?.alignment ?? "—").replaceAll("_", " ")}</strong></div>
        <span className="smallMuted">Closed candles only · refreshes every 30 seconds</span>
      </div>

      <div className="smcTimeframes">
        {allResults.map(item => {
          const trend = item.analysis?.structure?.trend;
          const trendClass = trend === "BULLISH" ? "trendBull" : trend === "BEARISH" ? "trendBear" : "trendNeutral";
          return <article className="smcTfCard" key={item.interval}>
            <div className="cardTop"><span className="symbol">{item.interval}</span><span className="tag">{item.data_status}</span></div>
            <strong className={trendClass}>{trendLabel(trend)}</strong>
            <span className="smallMuted">{item.analysis?.candles_analyzed ?? 0} candles analysed</span>
          </article>;
        })}
      </div>

      {focused?.status === "INSUFFICIENT_DATA" && <div className="empty">{focused.message}</div>}
      {focused?.status === "OK" && <>
        <div className="smcMetrics">
          <div><span>Last closed price</span><strong>{fmt(focused.last_close)}</strong></div>
          <div><span>Liquidity pools</span><strong>{focused.liquidity?.pools.length ?? 0}</strong></div>
          <div><span>Fair value gaps</span><strong>{focused.fair_value_gaps?.length ?? 0}</strong></div>
          <div><span>Order block candidates</span><strong>{focused.order_blocks?.length ?? 0}</strong></div>
        </div>
        <div className="smcDetailGrid">
          <article className="smcSubPanel">
            <h3>Latest structure event</h3>
            {focused.structure?.latest_event ? <><span className="smcSignal">{focused.structure.latest_event.type.replaceAll("_", " ")}</span><strong>Level {fmt(focused.structure.latest_event.level)}</strong><p>{focused.structure.latest_event.explanation}</p></> : <p>No confirmed structure break detected in this window.</p>}
          </article>
          <article className="smcSubPanel">
            <h3>Latest liquidity sweep</h3>
            {focused.liquidity?.latest_sweep ? <><span className="smcSignal">{focused.liquidity.latest_sweep.type.replaceAll("_", " ")}</span><strong>Level {fmt(focused.liquidity.latest_sweep.level)}</strong><p>{focused.liquidity.latest_sweep.explanation}</p></> : <p>No qualifying sweep detected in this window.</p>}
          </article>
        </div>
        <div className="smcZones">
          <article className="smcSubPanel">
            <h3>Recent fair value gaps</h3>
            {(focused.fair_value_gaps ?? []).slice(-6).reverse().map((z, i) => <div className="smcZoneRow" key={`${z.type}-${i}`}><span>{z.type.replaceAll("_", " ")}</span><strong>{fmt(z.lower)} – {fmt(z.upper)}</strong><em>{z.status}</em></div>)}
            {!focused.fair_value_gaps?.length && <p>No gaps detected.</p>}
          </article>
          <article className="smcSubPanel">
            <h3>Order block candidates</h3>
            {(focused.order_blocks ?? []).slice(-6).reverse().map((z, i) => <div className="smcZoneRow" key={`${z.type}-${i}`}><span>{z.type.replaceAll("_", " ")}</span><strong>{fmt(z.lower)} – {fmt(z.upper)}</strong><em>Candidate</em></div>)}
            {!focused.order_blocks?.length && <p>No candidate blocks detected.</p>}
          </article>
        </div>
      </>}
      {!loading && !focused && <div className="empty">No SMC results returned for the selected timeframe.</div>}
      <p className="chartDisclaimer">SMC labels are deterministic pattern descriptions, not proof of institutional activity or trade recommendations. Order blocks are candidate zones. Signals require backtesting and forward validation.</p>
    </section>
  );
}
