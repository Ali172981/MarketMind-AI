"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  is_closed: boolean;
};

type CandleResponse = {
  symbol: string;
  interval: string;
  data_status: string;
  source: string;
  last_live_update: string | null;
  count: number;
  items: Candle[];
  notice: string;
};

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];
const INTERVALS = ["15m", "30m", "1h", "2h", "4h", "1d"];
const fmt = (value: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: value > 100 ? 2 : 4 }).format(value);

export default function CandleChart() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("1h");
  const [payload, setPayload] = useState<CandleResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    async function load() {
      try {
        const response = await fetch(`${API}/market/candles?symbol=${symbol}&interval=${interval}&limit=300`, { cache: "no-store" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? "Unable to load OHLCV candles");
        if (active) { setPayload(data); setError(""); setLoading(false); }
      } catch (e) {
        if (active) { setError(e instanceof Error ? e.message : "Market data request failed"); setLoading(false); }
      }
    }
    setLoading(true);
    load();
    timer = setInterval(load, 10000);
    return () => { active = false; if (timer) clearInterval(timer); };
  }, [symbol, interval]);

  const candles = useMemo(() => payload?.items ?? [], [payload]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || candles.length === 0) return;
    const draw = () => {
      const width = canvas.clientWidth;
      const height = 340;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(width * ratio));
      canvas.height = Math.floor(height * ratio);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.scale(ratio, ratio);
      ctx.clearRect(0, 0, width, height);
      const left = 12, right = 70, top = 18, priceBottom = 250, volumeBottom = 320;
      const plotWidth = Math.max(100, width - left - right);
      const highs = candles.map(c => c.high), lows = candles.map(c => c.low);
      const max = Math.max(...highs), min = Math.min(...lows);
      const pad = (max - min || max * 0.002 || 1) * 0.08;
      const upper = max + pad, lower = min - pad;
      const y = (price: number) => top + ((upper - price) / (upper - lower)) * (priceBottom - top);
      const maxVol = Math.max(...candles.map(c => c.volume), 1);
      const step = plotWidth / candles.length;
      const bodyWidth = Math.max(1, Math.min(10, step * 0.68));

      ctx.font = "10px Arial";
      ctx.textBaseline = "middle";
      for (let i = 0; i <= 4; i++) {
        const gy = top + (priceBottom - top) * i / 4;
        const value = upper - (upper - lower) * i / 4;
        ctx.strokeStyle = "#243247"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(left, gy); ctx.lineTo(width - right + 8, gy); ctx.stroke();
        ctx.fillStyle = "#8c9bb0"; ctx.textAlign = "left"; ctx.fillText(fmt(value), width - right + 14, gy);
      }
      ctx.strokeStyle = "#1c2a3d"; ctx.beginPath(); ctx.moveTo(left, volumeBottom + 8); ctx.lineTo(width - right + 8, volumeBottom + 8); ctx.stroke();

      candles.forEach((c, i) => {
        const x = left + i * step + step / 2;
        const up = c.close >= c.open;
        const color = up ? "#36d399" : "#ff7185";
        const openY = y(c.open), closeY = y(c.close);
        ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, y(c.high)); ctx.lineTo(x, y(c.low)); ctx.stroke();
        const bodyTop = Math.min(openY, closeY), bodyHeight = Math.max(1, Math.abs(closeY - openY));
        ctx.fillRect(x - bodyWidth / 2, bodyTop, bodyWidth, bodyHeight);
        const volumeHeight = (c.volume / maxVol) * 55;
        ctx.globalAlpha = 0.65;
        ctx.fillRect(x - bodyWidth / 2, volumeBottom - volumeHeight, bodyWidth, volumeHeight);
        ctx.globalAlpha = 1;
      });

      ctx.fillStyle = "#8c9bb0"; ctx.textAlign = "center";
      const labelIndices = [0, Math.floor(candles.length / 3), Math.floor(candles.length * 2 / 3), candles.length - 1];
      [...new Set(labelIndices)].forEach(i => {
        const c = candles[i];
        const label = new Date(c.time * 1000).toLocaleString([], { month: "short", day: "numeric", hour: interval === "1d" ? undefined : "2-digit", minute: interval === "1d" ? undefined : "2-digit" });
        const x = left + i * step + step / 2;
        ctx.fillText(label, x, 334);
      });
      const last = candles[candles.length - 1];
      const lastY = y(last.close);
      ctx.setLineDash([4, 4]); ctx.strokeStyle = last.close >= last.open ? "#36d399" : "#ff7185";
      ctx.beginPath(); ctx.moveTo(left, lastY); ctx.lineTo(width - right + 8, lastY); ctx.stroke(); ctx.setLineDash([]);
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [candles, interval]);

  const last = candles[candles.length - 1];
  const first = candles[0];
  const move = first && last ? ((last.close - first.open) / first.open) * 100 : null;

  return (
    <section className="chartPanel">
      <div className="chartHeader">
        <div>
          <p className="eyebrow">PRICE ACTION · OHLCV</p>
          <h2>Market structure workspace</h2>
          <p className="chartSub">Exchange spot candles · historical backfill + live candle updates</p>
        </div>
        <div className="chartControls">
          <div className="controlGroup" aria-label="Select market">
            {SYMBOLS.map(s => <button key={s} className={symbol === s ? "controlActive" : "controlButton"} onClick={() => setSymbol(s)}>{s.replace("USDT", "")}</button>)}
          </div>
          <div className="controlGroup" aria-label="Select timeframe">
            {INTERVALS.map(t => <button key={t} className={interval === t ? "controlActive" : "controlButton"} onClick={() => setInterval(t)}>{t}</button>)}
          </div>
        </div>
      </div>
      <div className="chartStats">
        <div><span>Last close</span><strong>{last ? fmt(last.close) : "—"}</strong></div>
        <div><span>Visible range</span><strong>{move === null ? "—" : `${move >= 0 ? "+" : ""}${move.toFixed(2)}%`}</strong></div>
        <div><span>Candles</span><strong>{candles.length || "—"}</strong></div>
        <div><span>Feed</span><strong className={payload?.data_status === "LIVE" ? "feedLive" : "feedHistorical"}>{payload?.data_status ?? (loading ? "CONNECTING" : "UNKNOWN")}</strong></div>
      </div>
      {error && <div className="chartError">{error}. Check the backend connection and Binance availability.</div>}
      {loading && candles.length === 0 ? <div className="chartLoading">Loading historical candles from Binance…</div> : candles.length ? <canvas ref={canvasRef} className="candleCanvas" aria-label={`${symbol} ${interval} candlestick chart`} /> : <div className="chartLoading">No candles are available yet.</div>}
      <div className="chartFooter"><span>Source: Binance Spot public market data</span><span>Green = close above open · Red = close below open</span></div>
      <p className="chartDisclaimer">The current candle can change until its interval closes. This chart represents Binance Spot, not XAUUSD/XAGUSD broker pricing or executable trade quotes.</p>
    </section>
  );
}
