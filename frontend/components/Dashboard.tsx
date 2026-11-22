"use client";

import { useEffect, useState } from "react";
import CandleChart from "./CandleChart";
import SMCPanel from "./SMCPanel";
import BacktestPanel from "./BacktestPanel";
import CalibrationPanel from "./CalibrationPanel";
import PaperObservationPanel from "./PaperObservationPanel";
import MicrostructurePanel from "./MicrostructurePanel";
import StrategyPanel from "./StrategyPanel";

type Quote = {
  symbol: string;
  price: number;
  change_percent_24h: number | null;
  source: string;
  data_status: string;
  timestamp: string;
};

type StreamInfo = {
  stream?: {
    status?: string;
    subscription?: string;
    feed_freshness?: string;
    connected?: boolean;
    messages_received?: number;
    reconnect_count?: number;
    last_tick_at?: string | null;
    last_error?: string | null;
    enabled?: boolean;
  };
  orderbooks?: Array<{ symbol: string; best_bid: number | null; best_ask: number | null; spread_bps: number | null }>;
};

type QualitySummary = {
  status: string;
  comparisons_in_window: number;
  status_counts: Record<string, number>;
  latest_by_symbol: Record<string, { deviation_bps: number | null; status: string; primary_price: number | null; reference_price: number | null; primary_age_seconds: number | null; reference_age_seconds: number | null }>;
  notice: string;
};

type MacroItem = {
  symbol: string;
  name: string;
  value: number;
  unit: string;
  observation_date: string;
  data_status: string;
};

type NewsItem = {
  id: string;
  headline: string;
  summary: string;
  source_name: string;
  verification: string;
  published_at: string | null;
  event_categories: string[];
  assets: string[];
  importance: string;
  source_url: string | null;
  directional_bias: string;
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

function money(value: number, symbol: string) {
  const digits = symbol === "XAGUSD" ? 3 : 2;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

export default function Dashboard() {
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [newsFeedStatus, setNewsFeedStatus] = useState("Checking RSS sources");
  const [macro, setMacro] = useState<MacroItem[]>([]);
  const [streamInfo, setStreamInfo] = useState<StreamInfo | null>(null);
  const [quality, setQuality] = useState<QualitySummary | null>(null);
  const [macroStatus, setMacroStatus] = useState("Waiting for public data");
  const [status, setStatus] = useState("Connecting");
  const [error, setError] = useState("");
  const [dataNotice, setDataNotice] = useState("Market quotes are provider-labelled; news is sourced from public RSS feeds when available.");
  const [dataMode, setDataMode] = useState("DEMO");

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const [priceResponse, newsResponse, macroResponse, streamResponse, qualityResponse] = await Promise.all([
          fetch(`${API}/market/prices`, { cache: "no-store" }),
          fetch(`${API}/news`, { cache: "no-store" }),
          fetch(`${API}/macro/overview`, { cache: "no-store" }),
          fetch(`${API}/market/stream`, { cache: "no-store" }),
          fetch(`${API}/market/data-quality`, { cache: "no-store" })
        ]);
        if (!priceResponse.ok || !newsResponse.ok || !macroResponse.ok || !streamResponse.ok || !qualityResponse.ok) throw new Error("API request failed");
        const priceData = await priceResponse.json();
        const newsData = await newsResponse.json();
        const macroData = await macroResponse.json();
        const streamData = await streamResponse.json();
        const qualityData = await qualityResponse.json();
        if (!active) return;
        setQuotes(priceData.items);
        setNews(newsData.items);
        setNewsFeedStatus(newsData.feed_status?.status ?? "UNKNOWN");
        setMacro(macroData.items ?? []);
        setStreamInfo(streamData);
        setQuality(qualityData.summary ?? null);
        setMacroStatus(macroData.status ?? "UNKNOWN");
        setDataMode(priceData.data_status ?? "DEMO");
        setDataNotice(priceData.notice ?? "");
        setStatus(priceData.data_status === "LIVE_PARTIAL" ? "API connected · LIVE FEEDS PARTIAL" : priceData.data_status === "CONNECTING" ? "API connected · FEEDS CONNECTING" : "API connected · DEMO DATA");
        setError("");
      } catch {
        if (active) {
          setStatus("Backend unavailable");
          setError("Start the FastAPI backend on http://127.0.0.1:8000, then refresh.");
        }
      }
    }

    load();
    const timer = window.setInterval(load, 10000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <div className="brand"><span className="brandMark">M</span> MarketMind <span className="muted">AI</span></div>
          <div className="subtitle">Trading intelligence workspace</div>
        </div>
        <div className="status"><span className="pulse" />{status}</div>
      </header>

      <section className="welcome">
        <div>
          <p className="eyebrow">MARKET OVERVIEW</p>
          <h1>See the market.<br /><span>Understand the move.</span></h1>
          <p className="intro">A unified workspace for crypto, precious metals, macro events and technical intelligence.</p>
        </div>
        <div className="demoNotice"><strong>{dataMode === "LIVE_PARTIAL" ? "LIVE FEEDS · PARTIAL COVERAGE" : dataMode === "CONNECTING" ? "LIVE MODE · CONNECTING" : "DEMO MODE"}</strong><br />{dataNotice} News classification is heuristic and non-directional.</div>
      </section>

      {error && <div className="error">{error}</div>}

      {streamInfo?.stream && <section className="section">
        <div className="sectionHeading"><div><p className="eyebrow">LIVE DATA QUALITY</p><h2>AllTick stream monitor</h2></div><span className="smallMuted">{streamInfo.stream.status} · {streamInfo.stream.feed_freshness ?? "UNKNOWN"}</span></div>
        <div className="marketGrid">
          <article className="marketCard"><div className="cardTop"><span className="symbol">Connection</span><span className="tag">{streamInfo.stream.connected ? "CONNECTED" : "NOT CONNECTED"}</span></div><div className="price">{streamInfo.stream.subscription ?? "—"}</div><div className="smallMuted">Subscription mode</div></article>
          <article className="marketCard"><div className="cardTop"><span className="symbol">Messages</span></div><div className="price">{streamInfo.stream.messages_received ?? 0}</div><div className="smallMuted">Received this process lifetime</div></article>
          <article className="marketCard"><div className="cardTop"><span className="symbol">Reconnects</span></div><div className="price">{streamInfo.stream.reconnect_count ?? 0}</div><div className="smallMuted">Connection recovery count</div></article>
        </div>
        {streamInfo.orderbooks && streamInfo.orderbooks.length > 0 && <div className="newsItem"><strong>Order-book snapshots</strong>{streamInfo.orderbooks.map((book) => <p key={book.symbol}>{book.symbol}: bid {book.best_bid ?? "—"} · ask {book.best_ask ?? "—"} · spread {book.spread_bps == null ? "—" : `${book.spread_bps.toFixed(2)} bps`}</p>)}</div>}
        {streamInfo.stream.last_error && <p className="panelHint">Last stream error: {streamInfo.stream.last_error}</p>}
        <p className="panelHint">{streamInfo.stream.enabled ? "Stream enabled. Confirm provider entitlement and live timestamps; a connected socket alone does not prove complete market coverage." : "Streaming is disabled by default. Configure DATA_MODE=alltick, ALLTICK_API_KEY and ALLTICK_WS_ENABLED=true to enable it."}</p>
      </section>}

      {quality && <section className="section">
        <div className="sectionHeading"><div><p className="eyebrow">CROSS-PROVIDER VALIDATION</p><h2>Market data quality</h2></div><span className="smallMuted">{quality.status} · {quality.comparisons_in_window} recent checks</span></div>
        <div className="marketGrid">
          {Object.entries(quality.latest_by_symbol).map(([symbol, row]) => <article className="marketCard" key={symbol}>
            <div className="cardTop"><span className="symbol">{symbol}</span><span className="tag">{row.status}</span></div>
            <div className="price">{row.deviation_bps == null ? "—" : `${row.deviation_bps.toFixed(2)} bps`}</div>
            <div className="smallMuted">Absolute AllTick/reference deviation</div>
            <div className="cardFoot">AllTick {row.primary_price == null ? "—" : money(row.primary_price, symbol)} · Reference {row.reference_price == null ? "—" : money(row.reference_price, symbol)}</div>
            <div className="cardFoot">Quote ages: {row.primary_age_seconds == null ? "—" : `${row.primary_age_seconds.toFixed(1)}s`} / {row.reference_age_seconds == null ? "—" : `${row.reference_age_seconds.toFixed(1)}s`}</div>
          </article>)}
          {Object.keys(quality.latest_by_symbol).length === 0 && <div className="empty">Waiting for comparable provider quotes. Both sources must be fresh.</div>}
        </div>
        <p className="panelHint">{quality.notice} Deviation bands are screening thresholds, not universal fair-value limits. Provider prices are never merged.</p>
      </section>}

      <CandleChart />
      <StrategyPanel />
      <SMCPanel />
      <BacktestPanel />
      <CalibrationPanel />
      <PaperObservationPanel />
      <MicrostructurePanel />

      <section className="section">
        <div className="sectionHeading"><div><p className="eyebrow">WATCHLIST</p><h2>Markets</h2></div><span className="smallMuted">24-hour rolling change · per-symbol source/status shown</span></div>
        <div className="marketGrid">
          {quotes.map((q) => (
            <article className="marketCard" key={q.symbol}>
              <div className="cardTop"><span className="symbol">{q.symbol}</span><span className="tag">{q.data_status}</span></div>
              <div className="price">{q.data_status === "UNAVAILABLE" || q.data_status === "CONNECTING" ? "—" : money(q.price, q.symbol)}</div>
              <div className={q.change_percent_24h !== null && q.change_percent_24h >= 0 ? "positive" : "negative"}>
                {q.change_percent_24h !== null && (q.data_status === "LIVE" || q.data_status === "DEMO") ? `${q.change_percent_24h >= 0 ? "+" : ""}${q.change_percent_24h.toFixed(2)}%` : "Change unavailable"} <span className="smallMuted">24h</span>
              </div>
              <div className="cardFoot">Source: {q.source}</div>
            </article>
          ))}
          {quotes.length === 0 && <div className="empty">Waiting for backend market data…</div>}
        </div>
      </section>

      <section className="section macroSection">
        <div className="sectionHeading"><div><p className="eyebrow">MACRO CONTEXT</p><h2>Dollar & Treasury yields</h2></div><span className="smallMuted">Public FRED daily observations · status: {macroStatus}</span></div>
        <div className="macroGrid">
          {macro.map((item) => (
            <article className="marketCard" key={item.symbol}>
              <div className="cardTop"><span className="symbol">{item.symbol}</span><span className="tag">DAILY</span></div>
              <div className="price">{item.value.toFixed(2)}{item.unit === "%" ? "%" : ""}</div>
              <div className="smallMuted">{item.name}</div>
              <div className="cardFoot">Observation: {item.observation_date} · FRED · daily</div>
            </article>
          ))}
          {macro.length === 0 && <div className="empty">Waiting for public macro observations from FRED.</div>}
        </div>
        <p className="panelHint">Gold and silver are indicative spot prices from XAUS, polled every 60 seconds; they are not broker execution quotes. DTWEXBGS is a broad trade-weighted USD proxy, not ICE DXY. Treasury yields are daily observations, not live intraday quotes.</p>
      </section>

      <section className="lowerGrid">
        <article className="panel">
          <p className="eyebrow">INTELLIGENCE FEED</p>
          <h2>Market news</h2>
          <p className="panelHint">Public RSS headlines · feed status: {newsFeedStatus} · source timestamps preserved · keyword tags are review aids, not verified interpretations or trading signals.</p>
          {news.map((item) => (
            <div className="newsItem" key={item.id}>
              <div className="newsMeta"><span className="tag">{item.importance}</span><span>{item.source_name}</span></div>
              <h3>{item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.headline}</a> : item.headline}</h3>
              <p>{item.summary}</p>
              <div className="smallMuted">Published: {item.published_at ? new Date(item.published_at).toLocaleString() : "Source timestamp unavailable"}</div>
              <div className="smallMuted">Tags: {item.event_categories.join(", ")} · Assets: {item.assets.length ? item.assets.join(", ") : "Unassigned"}</div>
              <div className="smallMuted">{item.verification} · Direction: {item.directional_bias}</div>
            </div>
          ))}
          {news.length === 0 && <div className="empty">No stored public news yet. Check feed status or wait for the next refresh.</div>}
        </article>

        <article className="panel">
          <p className="eyebrow">RESEARCH PIPELINE</p>
          <h2>Intelligence engines</h2>
          <div className="feature"><span>01</span><div><strong>Macro monitor</strong><p>Daily Treasury yields and broad USD proxy connected; exact DXY pending licensed feed.</p></div><em>Partial</em></div>
          <div className="feature"><span>02</span><div><strong>Market structure</strong><p>Confirmed swings, BOS/CHoCH, liquidity pools, FVGs and candidate order blocks.</p></div><em>Active</em></div>
          <div className="feature"><span>03</span><div><strong>Reversal scanner</strong><p>Evidence-based zones, confirmation and invalidation.</p></div><em>Planned</em></div>
          <div className="feature"><span>04</span><div><strong>Smart alerts</strong><p>Telegram, email and app notifications.</p></div><em>Planned</em></div>
        </article>
      </section>

      <footer>MarketMind AI · Historical OHLCV engine · Research only, not investment advice</footer>
    </main>
  );
}
