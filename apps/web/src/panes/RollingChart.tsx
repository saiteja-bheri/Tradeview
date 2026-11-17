import { ColorType, CrosshairMode, LineStyle, createChart, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Rolling, RollingKey } from "../api/types";
import { num, pct } from "../format";
import { useStore } from "../state/store";
import { Seg } from "../ui";

const WINDOWS = [{ value: 21, label: "1M" }, { value: 63, label: "3M" }, { value: 126, label: "6M" }, { value: 252, label: "1Y" }];
const SPANS = [{ value: 252, label: "1Y" }, { value: 504, label: "2Y" }, { value: 756, label: "3Y" }, { value: 1260, label: "5Y" }];

/** Ratios share the right scale; percentages get the left one. */
const METRICS: { key: RollingKey; label: string; color: string; percent: boolean; title: string }[] = [
  { key: "sharpe", label: "SHARPE", color: "#ffb000", percent: false, title: "Excess return per unit of total risk, annualised" },
  { key: "sortino", label: "SORTINO", color: "#c792ea", percent: false, title: "Excess return per unit of downside risk, annualised" },
  { key: "beta", label: "BETA", color: "#55c8f2", percent: false, title: "Sensitivity to the benchmark" },
  { key: "volatility", label: "VOL", color: "#ff5263", percent: true, title: "Annualised volatility" },
  { key: "alpha", label: "ALPHA", color: "#2bd47d", percent: true, title: "Jensen's alpha, annualised" },
  { key: "return", label: "RETURN", color: "#f78c6c", percent: true, title: "Compound annual return over the window" },
];

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function load(key: string, fallback: number): number {
  try {
    const v = Number(localStorage.getItem(key));
    return Number.isFinite(v) && v > 0 ? v : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: number | string): void {
  try {
    localStorage.setItem(key, String(value));
  } catch {
    /* storage is optional */
  }
}

/** Rolling Sharpe (and Sortino, beta, volatility, alpha, return) of today's
 *  mix: drag to pan, scroll to zoom, hover for the day's figures. Follows live
 *  prices and benchmark changes; the target line and the share of days above
 *  it are yours to set. */
export function RollingChart() {
  const epoch = useStore((s) => s.portfolio);   // new object after any recompute (live, benchmark, import)
  const [window_, setWindow] = useState(() => load("qt.rolling.window", 63));
  const [span, setSpan] = useState(() => load("qt.rolling.span", 504));
  const [shown, setShown] = useState<RollingKey[]>(() => {
    try {
      const v = JSON.parse(localStorage.getItem("qt.rolling.shown") ?? "null");
      return Array.isArray(v) && v.length ? v : ["sharpe", "beta"];
    } catch {
      return ["sharpe", "beta"];
    }
  });
  const [target, setTarget] = useState(() => load("qt.rolling.target", 1));
  const [data, setData] = useState<Rolling | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<{ time: string; values: Partial<Record<RollingKey, number>> } | null>(null);

  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Map<RollingKey, ISeriesApi<"Line">>>(new Map());
  const targetLine = useRef<IPriceLine | null>(null);
  const fitted = useRef(false);

  useEffect(() => {
    let alive = true;
    api.rolling(window_, span)
      .then((r) => { if (alive) { setData(r); setError(null); } })
      .catch((e) => { if (alive) setError((e as Error).message); });
    return () => { alive = false; };
  }, [epoch, window_, span]);

  // One chart for the pane's lifetime, so live updates keep your zoom.
  useEffect(() => {
    if (!box.current) return;
    const dim = cssVar("--color-dim", "#7b8492"), raise = cssVar("--color-raise", "#151920");
    const line = cssVar("--color-line", "#1f242d"), bg = cssVar("--color-panel", "#0d0f13");
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: bg }, textColor: dim, fontSize: 10 },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      rightPriceScale: { borderColor: line, visible: true },
      leftPriceScale: { borderColor: line, visible: false },
      timeScale: { borderColor: line, rightOffset: 2 },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { labelBackgroundColor: raise, color: dim },
                   horzLine: { labelBackgroundColor: raise, color: dim } },
    });
    chart.subscribeCrosshairMove((p) => {
      if (!p.time) { setHover(null); return; }
      const values: Partial<Record<RollingKey, number>> = {};
      seriesRef.current.forEach((s, k) => {
        const d = p.seriesData.get(s) as { value?: number } | undefined;
        if (d?.value != null) values[k] = d.value;
      });
      setHover({ time: String(p.time), values });
    });
    chartRef.current = chart;
    const series = seriesRef.current;
    return () => {
      chart.remove();
      chartRef.current = null;
      series.clear();
      targetLine.current = null;
    };
  }, []);

  // Series follow the toggles and the data.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !data) return;
    const map = seriesRef.current;
    for (const [k, s] of map) {
      if (!shown.includes(k)) {
        if (k === "sharpe") targetLine.current = null;
        chart.removeSeries(s);
        map.delete(k);
      }
    }
    let usesLeft = false;
    for (const m of METRICS) {
      if (!shown.includes(m.key)) continue;
      usesLeft ||= m.percent;
      let s = map.get(m.key);
      if (!s) {
        s = chart.addLineSeries({
          color: m.color, lineWidth: m.key === "sharpe" ? 2 : 1, priceScaleId: m.percent ? "left" : "right",
          priceLineVisible: false, lastValueVisible: true, title: m.label,
          priceFormat: m.percent
            ? { type: "custom", formatter: (v: number) => `${(v * 100).toFixed(1)}%`, minMove: 0.0001 }
            : { type: "price", precision: 2, minMove: 0.01 },
        });
        map.set(m.key, s);
      }
      const values = data.series[m.key] ?? [];
      s.setData(data.dates.flatMap((d, i) => (values[i] == null ? [] : [{ time: d as Time, value: values[i] as number }])));
    }
    chart.applyOptions({ leftPriceScale: { visible: usesLeft } });
    const sharpe = map.get("sharpe");
    if (sharpe) {
      if (targetLine.current) sharpe.removePriceLine(targetLine.current);
      targetLine.current = sharpe.createPriceLine({
        price: target, color: "#ffb000", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "TARGET",
      });
    }
    if (!fitted.current && data.dates.length) {
      chart.timeScale().fitContent();
      fitted.current = true;
    }
  }, [data, shown, target]);

  useEffect(() => { fitted.current = false; }, [window_, span]);

  const sharpe = data?.series.sharpe ?? [];
  const stats = useMemo(() => {
    const vals = sharpe.filter((v): v is number => v != null);
    if (!vals.length) return null;
    const above = vals.filter((v) => v >= target).length;
    return { last: vals[vals.length - 1], max: Math.max(...vals), min: Math.min(...vals),
             mean: vals.reduce((a, b) => a + b, 0) / vals.length, above: above / vals.length };
  }, [sharpe, target]);

  const toggle = (k: RollingKey) => {
    const next = shown.includes(k) ? shown.filter((x) => x !== k) : [...shown, k];
    if (!next.length) return;
    setShown(next);
    save("qt.rolling.shown", JSON.stringify(next));
  };

  const fmt = (k: RollingKey, v: number | null | undefined) =>
    METRICS.find((m) => m.key === k)?.percent ? pct(v, 1) : num(v);

  return (
    <div className="flex flex-col border-t border-line">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 pt-2.5">
        <span className="text-[10px] tracking-widest text-dim">ROLLING</span>
        {data?.live && <span className="text-[9px] tracking-widest text-up" title="Today's live prices count as a provisional day">● LIVE</span>}
        <Seg<number> label="WINDOW" value={window_} options={WINDOWS}
                     onChange={(v) => { setWindow(v); save("qt.rolling.window", v); }} />
        <Seg<number> label="SPAN" value={span} options={SPANS}
                     onChange={(v) => { setSpan(v); save("qt.rolling.span", v); }} />
      </div>
      <div className="flex flex-wrap items-center gap-1 px-3 pt-1.5" role="group" aria-label="Series shown">
        {METRICS.map((m) => {
          const on = shown.includes(m.key);
          return (
            <button key={m.key} type="button" aria-pressed={on} title={m.title} onClick={() => toggle(m.key)}
                    className={`flex items-center gap-1 border px-1.5 py-0.5 text-[10px] ${on ? "border-line text-ink" : "border-transparent text-dim/60 hover:text-dim"}`}>
              <span className="inline-block h-0.5 w-2.5" style={{ background: on ? m.color : "currentColor" }} />
              {m.label}
            </button>
          );
        })}
        <label className="ml-auto flex items-center gap-1 text-[10px] tracking-widest text-dim"
               title="Dashed line on the Sharpe series; the share of days at or above it is shown below">
          SHARPE TARGET
          <input type="number" step={0.1} value={target} aria-label="Sharpe target"
                 onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v)) { setTarget(v); save("qt.rolling.target", v); } }}
                 className="w-14 border border-line bg-bg px-1 py-0.5 text-right text-ink outline-none focus:border-amber" />
        </label>
      </div>
      <div className="flex min-h-[18px] flex-wrap gap-x-3 px-3 pt-1 text-[10.5px] tabular-nums">
        {hover ? (
          <>
            <span className="text-dim">{hover.time}</span>
            {shown.map((k) => (
              <span key={k} style={{ color: METRICS.find((m) => m.key === k)?.color }}>
                {METRICS.find((m) => m.key === k)?.label} {fmt(k, hover.values[k])}
              </span>
            ))}
          </>
        ) : stats ? (
          <>
            <span>SHARPE now <span className="text-amber">{num(stats.last)}</span></span>
            <span className="text-dim">high {num(stats.max)} · low {num(stats.min)} · avg {num(stats.mean)}</span>
            <span className="text-dim">≥ target on {pct(stats.above, 0)} of days</span>
          </>
        ) : null}
      </div>
      <div ref={box} className="h-[220px]" />
      {(error || (data && data.warnings.length > 0)) && (
        <div className="px-3 py-1 text-[10.5px] text-amber">⚠ {error ?? data!.warnings.join(" · ")}</div>
      )}
      <div className="px-3 py-1 text-[10px] text-dim">
        Today's mix over trailing {WINDOWS.find((w) => w.value === window_)?.label ?? `${window_}D`} windows ·
        vs {data?.benchmark_name ?? "benchmark"} · risk-free {pct(data?.risk_free_rate, 1)} · drag to pan, scroll to zoom
      </div>
    </div>
  );
}
