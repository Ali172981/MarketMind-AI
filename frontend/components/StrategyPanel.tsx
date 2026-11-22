"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XAUUSD", "XAGUSD"];
const INTERVALS = ["15m", "30m", "1h", "2h", "4h", "1d"];

type Evidence = { points: number; factor: string; detail: string };
type Result = {
  status: string;
  symbol: string;
  direction: string;
  focus_interval?: string;
  evidence_score: number | null;
  long_score?: number;
  short_score?: number;
  score_margin?: number;
  score_definition?: string;
  validated_probability: number | null;
  price_reference?: number | null;
  invalidation_reference?: number | null;
  target_1_reference?: number | null;
  target_2_reference?: number | null;
  indicators?: { ema20?: number; ema50?: number; rsi14?: number; atr14?: number; relative_volume20?: number };
  supporting_evidence?: Evidence[];
  opposing_evidence?: Evidence[];
  neutral_notes?: string[];
  multi_timeframe?: Array<{ interval: string; trend: string; data_status: string }>;
  news_context?: { relevant_headlines: number; interpretation: string; items: Array<{ headline: string; source_name: string; published_at: string | null }> };
  data_sources?: Array<{ interval: string; source: string; data_status: string; candles: number }>;
  unavailable_intervals?: Array<{ interval: string; error: string }>;
  message?: string;
  disclaimer?: string;
};

const fmt = (n?: number | null) => n == null ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 5 }).format(n);

export default function StrategyPanel() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [focus, setFocus] = useState("1h");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function analyze() {
    setLoading(true);
    setError("");
    try {
      const intervals = [...new Set([focus === "15m" ? "15m" : "15m", focus, "4h"])].join(",");
      const response = await fetch(`${API}/market/strategy/analyze?symbol=${symbol}&intervals=${intervals}&limit=300`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Strategy analysis failed");
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to run strategy analysis");
    } finally {
      setLoading(false);
    }
  }

  const statusClass = result?.status === "WATCH" ? "successStatus" : "warningStatus";

  return (
    <section className="calibrationSection smcPanel strategySection">
      <div className="smcHeader">
        <div>
          <p className="eyebrow">MARKETMIND v1.0 · EXPLAINABLE CONFLUENCE</p>
          <h2>Strategy Intelligence Engine</h2>
          <p className="chartSub">SMC · trend · momentum · volume · multi-timeframe context · news</p>
        </div>
        <div className="smcControls">
          <select value={symbol} onChange={e => setSymbol(e.target.value)} aria-label="Strategy instrument">
            {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={focus} onChange={e => setFocus(e.target.value)} aria-label="Strategy focus timeframe">
            {INTERVALS.map(t => <option key={t} value={t}>{t} focus</option>)}
          </select>
          <button className="primaryButton" onClick={analyze} disabled={loading}>{loading ? "Analysing…" : "Run analysis"}</button>
        </div>
      </div>
      {error && <div className="chartError">{error}</div>}
      {!result && !loading && <div className="empty">Select a market and timeframe, then run the strategy analysis.</div>}
      {loading && <div className="empty">Evaluating closed-candle evidence across the selected timeframes…</div>}
      {result && <>
        <div className={`calibrationStatus ${statusClass}`}>
          <strong>{result.status.replaceAll("_", " ")} · {result.direction}</strong>
          <span>{result.message ?? "Research hypothesis only. No trade is submitted."}</span>
        </div>
        <div className="smcMetrics">
          <div><span>Confluence index</span><strong>{result.evidence_score ?? "—"}/100</strong></div>
          <div><span>Long evidence</span><strong>{result.long_score ?? "—"}</strong></div>
          <div><span>Short evidence</span><strong>{result.short_score ?? "—"}</strong></div>
          <div><span>Validated probability</span><strong>Not published</strong></div>
        </div>
        <div className="smcMetrics">
          <div><span>Closed-price reference</span><strong>{fmt(result.price_reference)}</strong></div>
          <div><span>Invalidation reference</span><strong>{fmt(result.invalidation_reference)}</strong></div>
          <div><span>Target 1 reference</span><strong>{fmt(result.target_1_reference)}</strong></div>
          <div><span>Target 2 reference</span><strong>{fmt(result.target_2_reference)}</strong></div>
        </div>
        <div className="calibrationGrid">
          <article className="calibrationSubPanel">
            <h3>Supporting evidence</h3>
            {(result.supporting_evidence ?? []).map((item, i) => <div className="splitList" key={`${item.factor}-${i}`}><div><span>{item.factor.replaceAll("_", " ")} · +{item.points}</span><small>{item.detail}</small></div></div>)}
            {!result.supporting_evidence?.length && <p>No side has met the evidence and score-margin thresholds.</p>}
          </article>
          <article className="calibrationSubPanel">
            <h3>Opposing evidence & cautions</h3>
            {(result.opposing_evidence ?? []).map((item, i) => <div className="splitList" key={`${item.factor}-${i}`}><div><span>{item.factor.replaceAll("_", " ")} · +{item.points}</span><small>{item.detail}</small></div></div>)}
            {(result.neutral_notes ?? []).map((note, i) => <p key={i}>{note}</p>)}
          </article>
        </div>
        <div className="smcZones">
          <article className="smcSubPanel">
            <h3>Multi-timeframe context</h3>
            {(result.multi_timeframe ?? []).map(item => <div className="smcZoneRow" key={item.interval}><span>{item.interval}</span><strong>{item.trend}</strong><em>{item.data_status}</em></div>)}
            {(result.data_sources ?? []).map(item => <p key={item.interval}>{item.interval}: {item.candles} closed candles · {item.source ?? "Source unavailable"}</p>)}
          </article>
          <article className="smcSubPanel">
            <h3>News context · non-directional</h3>
            <p>{result.news_context?.relevant_headlines ?? 0} relevant stored RSS headline(s). {result.news_context?.interpretation ?? "No news context."}</p>
            {(result.news_context?.items ?? []).map((item, i) => <p key={i}><strong>{item.source_name}:</strong> {item.headline}</p>)}
          </article>
        </div>
        <p className="chartDisclaimer">{result.score_definition} {result.disclaimer}</p>
      </>}
    </section>
  );
}
