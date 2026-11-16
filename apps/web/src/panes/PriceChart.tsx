import { ColorType, CrosshairMode, createChart, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { num, pct, ticker, tone } from "../format";
import { useStore } from "../state/store";
import { Empty, EyeIcon } from "../ui";

type Bar = { time: string; value: number };

const PRESETS = [
  { label: "1M", days: 31 }, { label: "3M", days: 92 }, { label: "6M", days: 183 },
  { label: "1Y", days: 365 }, { label: "2Y", days: 730 }, { label: "5Y", days: 1826 }, { label: "ALL", days: 0 },
];

function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

/** Interactive daily-close chart from Yahoo Finance data: drag to pan, scroll or
 *  pinch to zoom, hover for the exact date and price, and pick any window with the
 *  presets or the FROM / TO dates. Held, watched and starred stocks come from the
 *  local cache; anything else is loaded only when asked and is not saved. */
export function PriceChart({ symbol }: { symbol: string }) {
  const toggleWatch = useStore((s) => s.toggleWatch);
  const watched = useStore((s) => s.watch.some((w) => w.symbol === symbol && w.watched));
  const [bars, setBars] = useState<Bar[] | null>(null);
  const [meta, setMeta] = useState<{ currency: string; saved: boolean; tracked: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = (fetch: boolean) => {
    setLoading(true);
    setError(null);
    api.prices(symbol, 3660, fetch)
      .then((r) => {
        setBars(r.bars.map((b) => ({ time: b.date, value: b.close })));
        setMeta({ currency: r.currency, saved: r.saved, tracked: r.tracked });
        if (!r.bars.length && (r.tracked || fetch)) setError(r.warning ?? "No price history for this symbol");
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    setBars(null);
    setMeta(null);
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, watched]);

  if (error) return <Empty title="No chart" hint={error} />;
  if (!bars || !meta) return <Empty title="Loading prices…" />;
  if (!bars.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
        <div className="text-dim">{ticker(symbol)} is in your history only, so its prices are not saved.</div>
        <div className="flex flex-wrap justify-center gap-2">
          <button onClick={() => load(true)} disabled={loading}
                  className="border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40">
            {loading ? "LOADING…" : "SHOW CHART (NOT SAVED)"}
          </button>
          <button onClick={() => toggleWatch(symbol)}
                  className="flex items-center gap-1.5 border border-line px-3 py-1 text-dim hover:border-cyan hover:text-cyan">
            <EyeIcon on={false} /> WATCH AND KEEP PRICES
          </button>
        </div>
      </div>
    );
  }
  return <Chart key={`${symbol}:${bars.length}`} symbol={symbol} bars={bars} currency={meta.currency} saved={meta.saved} />;
}

function Chart({ symbol, bars, currency, saved }: { symbol: string; bars: Bar[]; currency: string; saved: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const first = bars[0].time, last = bars[bars.length - 1].time;
  const [from, setFrom] = useState(shiftDays(last, 365) < first ? first : shiftDays(last, 365));
  const [to, setTo] = useState(last);
  const [preset, setPreset] = useState("1Y");
  const [hover, setHover] = useState<{ time: string; value: number } | null>(null);

  // Change over the visible window, from the first to the last bar in it.
  const inView = bars.filter((b) => b.time >= from && b.time <= to);
  const startV = inView[0]?.value, endV = inView[inView.length - 1]?.value;
  const change = startV && endV ? endV / startV - 1 : null;

  useEffect(() => {
    if (!box.current) return;
    const dim = cssVar("--color-dim", "#7b8492"), raise = cssVar("--color-raise", "#151920");
    const line = cssVar("--color-line", "#1f242d"), bg = cssVar("--color-panel", "#0d0f13");
    const up = bars[bars.length - 1].value >= bars[0].value;
    const color = cssVar(up ? "--color-up" : "--color-down", up ? "#2bd47d" : "#ff5263");
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: bg }, textColor: dim, fontSize: 11 },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      rightPriceScale: { borderColor: line },
      timeScale: { borderColor: line, rightOffset: 2, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Magnet, vertLine: { labelBackgroundColor: raise, color: dim },
                   horzLine: { labelBackgroundColor: raise, color: dim } },
      handleScroll: true,
      handleScale: true,
    });
    const series = chart.addAreaSeries({
      lineColor: color, topColor: `${color}55`, bottomColor: `${color}05`, lineWidth: 2,
      priceLineVisible: false, lastValueVisible: true,
    });
    series.setData(bars as { time: Time; value: number }[]);
    chart.timeScale().setVisibleRange({ from: from as Time, to: to as Time });
    chart.subscribeCrosshairMove((p) => {
      const d = p.time ? (p.seriesData.get(series) as { value?: number } | undefined) : undefined;
      setHover(p.time && d?.value != null ? { time: String(p.time), value: d.value } : null);
    });
    chart.timeScale().subscribeVisibleTimeRangeChange((r) => {
      if (!r) return;
      setFrom(String(r.from) < first ? first : String(r.from));
      setTo(String(r.to) > last ? last : String(r.to));
      setPreset("");
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars]);

  const show = (f: string, t: string, label = "") => {
    const lo = f < first ? first : f, hi = t > last ? last : t;
    if (lo >= hi) return;
    chartRef.current?.timeScale().setVisibleRange({ from: lo as Time, to: hi as Time });
    setFrom(lo);
    setTo(hi);
    setPreset(label);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-1.5">
        <span className="font-semibold text-cyan">{ticker(symbol)}</span>
        <span className="tabular-nums">{num(hover?.value ?? endV)}</span>
        {currency && <span className="text-[10px] text-dim">{currency}</span>}
        {hover ? <span className="text-[10.5px] text-dim">{hover.time}</span>
          : <span className={`text-[11px] ${tone(change)}`}>{pct(change, 1)} in view</span>}
        <span className="ml-auto flex">
          {PRESETS.map((p) => (
            <button key={p.label}
                    onClick={() => show(p.days ? shiftDays(last, p.days) : first, last, p.label)}
                    className={`-ml-px border px-1.5 py-0.5 text-[10px] first:ml-0 ${preset === p.label ? "relative z-10 border-amber bg-amber text-black" : "border-line text-dim hover:text-ink"}`}>
              {p.label}
            </button>
          ))}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-3 pb-1.5 text-[10px] tracking-widest text-dim">
        <label className="flex items-center gap-1">FROM
          <input type="date" value={from} min={first} max={to} onChange={(e) => show(e.target.value, to)}
                 className="border border-line bg-bg px-1 py-0.5 text-[11px] text-ink outline-none focus:border-amber" />
        </label>
        <label className="flex items-center gap-1">TO
          <input type="date" value={to} min={from} max={last} onChange={(e) => show(from, e.target.value)}
                 className="border border-line bg-bg px-1 py-0.5 text-[11px] text-ink outline-none focus:border-amber" />
        </label>
        <span className="ml-auto normal-case tracking-normal">
          {inView.length} of {bars.length} days · drag to pan, scroll to zoom
        </span>
      </div>
      <div ref={box} className="min-h-[160px] flex-1" />
      <div className="border-t border-line px-3 py-1 text-[10px] text-dim">
        Daily closes from Yahoo Finance{symbol.startsWith("MF:") ? " / AMFI NAV" : ""} ·{" "}
        {saved ? "kept in the local cache" : "shown once, not saved"}
      </div>
    </div>
  );
}
