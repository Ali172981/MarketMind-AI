"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

type Metrics = {
  status: string;
  symbol?: string;
  best_bid?: number;
  best_ask?: number;
  mid_price?: number;
  spread_bps?: number;
  top5_imbalance?: number;
  microprice_vs_mid_bps?: number;
  depth_10bps?: { bids: { notional: number }; asks: { notional: number } };
  notice?: string;
};

type Estimate = {
  status: string;
  estimated_vwap?: number;
  reference_mid?: number;
  estimated_slippage_bps_vs_mid?: number;
  filled_visible_quantity?: number;
  unfilled_quantity?: number;
  visible_fill_ratio?: number;
  notice?: string;
};

export default function MicrostructurePanel() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [side, setSide] = useState("buy");
  const [quantity, setQuantity] = useState("0.01");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [error, setError] = useState("Waiting for stored AllTick depth snapshots.");

  async function load() {
    try {
      const response = await fetch(`${API}/market/microstructure/${symbol}`, { cache: "no-store" });
      if (!response.ok) throw new Error(response.status === 404 ? "No stored depth snapshot. Configure ALLTICK_WS_SUBSCRIPTION=depth and enable tick storage." : "Microstructure endpoint unavailable.");
      setMetrics(await response.json());
      setError("");
    } catch (err) {
      setMetrics(null);
      setError(err instanceof Error ? err.message : "Unable to load order-book metrics.");
    }
  }

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 10000);
    return () => window.clearInterval(timer);
  }, [symbol]);

  async function estimateSweep() {
    setEstimate(null);
    try {
      const params = new URLSearchParams({ side, quantity });
      const response = await fetch(`${API}/market/microstructure/${symbol}/estimate?${params}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to estimate visible depth.");
      setEstimate(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to estimate visible depth.");
    }
  }

  return <section className="section">
    <div className="sectionHeading"><div><p className="eyebrow">EXECUTION MICROSTRUCTURE</p><h2>Visible depth & sweep estimator</h2></div><span className="smallMuted">AllTick order-book snapshots</span></div>
    <div className="marketGrid">
      <article className="marketCard">
        <div className="cardTop"><span className="symbol">Instrument</span><select value={symbol} onChange={(e) => { setSymbol(e.target.value); setEstimate(null); }}><option>BTCUSDT</option><option>ETHUSDT</option><option>SOLUSDT</option><option>XAUUSD</option><option>XAGUSD</option></select></div>
        {metrics ? <>
          <div className="price">{metrics.spread_bps?.toFixed(2) ?? "—"} bps</div>
          <div className="smallMuted">Displayed bid/ask spread</div>
          <div className="cardFoot">Bid {metrics.best_bid?.toLocaleString() ?? "—"} · Ask {metrics.best_ask?.toLocaleString() ?? "—"}</div>
          <div className="cardFoot">Top-5 imbalance {metrics.top5_imbalance == null ? "—" : `${(metrics.top5_imbalance * 100).toFixed(1)}%`}</div>
          <div className="cardFoot">Microprice deviation {metrics.microprice_vs_mid_bps?.toFixed(2) ?? "—"} bps</div>
          <div className="cardFoot">10 bps depth notional: bid {metrics.depth_10bps?.bids.notional.toFixed(2) ?? "—"} · ask {metrics.depth_10bps?.asks.notional.toFixed(2) ?? "—"}</div>
        </> : <p className="panelHint">{error}</p>}
      </article>
      <article className="marketCard">
        <div className="cardTop"><span className="symbol">Snapshot sweep estimate</span></div>
        <div className="feature"><label>Side <select value={side} onChange={(e) => setSide(e.target.value)}><option value="buy">Buy</option><option value="sell">Sell</option></select></label><label>Quantity <input type="number" min="0.00000001" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label><button type="button" onClick={estimateSweep}>Estimate</button></div>
        {estimate && <>
          <div className="price">{estimate.estimated_slippage_bps_vs_mid?.toFixed(2) ?? "—"} bps</div>
          <div className="smallMuted">Estimated slippage versus mid · {estimate.status}</div>
          <div className="cardFoot">Visible fill: {estimate.filled_visible_quantity?.toFixed(8) ?? "—"} · Unfilled: {estimate.unfilled_quantity?.toFixed(8) ?? "—"}</div>
          <div className="cardFoot">Estimated VWAP: {estimate.estimated_vwap?.toLocaleString() ?? "—"}</div>
        </>}
      </article>
    </div>
    <p className="panelHint">Depth sweep is a deterministic calculation against one stored snapshot, not a guaranteed fill. It excludes fees, latency during execution, queue priority, hidden liquidity, cancellations and market impact beyond displayed levels. Requires ALLTICK_WS_SUBSCRIPTION=depth.</p>
  </section>;
}
