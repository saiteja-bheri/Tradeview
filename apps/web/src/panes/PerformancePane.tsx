import { ColorType, CrosshairMode, createChart, LineStyle, type IChartApi, type Time } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { Timeline } from "../api/types";
import { ASSET_NAME, inr, pct, signed, tone } from "../format";
import { useStore } from "../state/store";
import { Empty } from "../ui";

type View = "value" | "networth" | "gain" | "benchmark" | "classes";

const VIEWS: { value: View; label: string; hint: string }[] = [
  { value: "value", label: "VALUE VS MONEY IN", hint: "Portfolio value, portfolio cash, and the new money you put in (less withdrawals)" },
  { value: "networth", label: "NET WORTH", hint: "Portfolio, portfolio cash, deposits, pension and insurance, stacked" },
  { value: "gain", label: "GAIN / LOSS", hint: "Value plus portfolio cash minus the money you put in" },
  { value: "benchmark", label: "VS BENCHMARK", hint: "Your portfolio against the benchmark, started at the same value" },
  { value: "classes", label: "BY ASSET CLASS", hint: "Portfolio value by asset class, stacked" },
];

const PRESETS = [
  { label: "1M", days: 31 }, { label: "3M", days: 92 }, { label: "6M", days: 183 }, { label: "1Y", days: 365 },
  { label: "3Y", days: 1095 }, { label: "ALL", days: 0 },
];

const PALETTE = ["#55c8f2", "#ffb000", "#2bd47d", "#e07bd0", "#9b8cff", "#ff8f6b", "#5fd3a8", "#c98a3b"];
const GROUP_ORDER = ["Retirement", "Deposits", "Insurance", "Cash", "Other"];

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

// values: what is drawn (running totals for stacked views); own: the item's own value, for the legend.
type Line = { key: string; label: string; color: string; values: (number | null)[]; own?: (number | null)[];
              kind: "line" | "area" | "dashed" };

/** Graphs of the portfolio and net worth over time. Pick the graph, the period
 *  (presets or FROM / TO), drag to pan, scroll to zoom, hover for the figures. */
export function PerformancePane() {
  const epoch = useStore((s) => s.portfolio);          // a new object after every recompute (import, edit, refresh)
  const [data, setData] = useState<Timeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("value");

  useEffect(() => {
    api.timeline().then(setData).catch((e) => setError((e as Error).message));
  }, [epoch]);

  const lines = useMemo<Line[]>(() => {
    if (!data || !data.dates.length) return [];
    const s = data.series;
    if (view === "value") {
      return [
        { key: "market", label: "Portfolio value", color: PALETTE[0], values: s.market, kind: "area" },
        { key: "invested", label: "Money put in", color: "#7b8492", values: s.invested, kind: "dashed" },
        { key: "cash", label: "Portfolio cash", color: PALETTE[2], values: s.cash, kind: "line" },
      ];
    }
    if (view === "gain") return [{ key: "gain", label: "Gain / loss", color: PALETTE[2], values: s.gain, kind: "area" }];
    if (view === "benchmark") {
      return [
        { key: "market", label: "Your portfolio", color: PALETTE[0], values: s.market, kind: "line" },
        { key: "benchmark", label: data.benchmark_name, color: PALETTE[1], values: s.benchmark ?? [], kind: "line" },
      ];
    }
    // Stacked views: each band is drawn as the running total from the bottom up.
    const parts: { label: string; values: (number | null)[] }[] =
      view === "classes"
        ? Object.entries(data.by_class).map(([c, v]) => ({ label: ASSET_NAME[c] ?? c, values: v }))
        : [
            { label: "Market portfolio", values: s.market },
            { label: "Portfolio cash", values: s.cash },
            ...GROUP_ORDER.filter((g) => data.wealth_groups[g]).map((g) => ({ label: g, values: data.wealth_groups[g] })),
          ];
    const totals = data.dates.map(() => 0);
    const stacked = parts.map((p, i) => {
      const values = p.values.map((v, k) => (totals[k] += v ?? 0));
      return { key: p.label, label: p.label, color: PALETTE[i % PALETTE.length], values: [...values], own: p.values,
               kind: "area" as const };
    });
    return stacked.reverse();                         // tallest first, so each band shows on top of the next
  }, [data, view]);

  if (error) return <Empty title="Could not load the history" hint={error} />;
  if (!data) return <Empty title="Loading history…" />;
  if (!data.dates.length) return <Empty title="Nothing to graph yet" hint={data.warnings[0] ?? "Import trades first."} />;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1.5">
        {VIEWS.map((v) => (
          <button key={v.value} onClick={() => setView(v.value)} title={v.hint} aria-pressed={view === v.value}
                  className={`border px-1.5 py-0.5 text-[10px] tracking-widest ${view === v.value ? "border-amber bg-amber text-black" : "border-line text-dim hover:text-ink"}`}>
            {v.label}
          </button>
        ))}
      </div>
      <Chart key={view} dates={data.dates} lines={lines} view={view} />
      <div className="border-t border-line px-3 py-1 text-[10px] leading-relaxed text-dim">
        {VIEWS.find((v) => v.value === view)?.hint}. Dividends, coupons and sale proceeds stay as portfolio cash until a
        purchase uses them or you record a withdrawal (WEALTH tab). Other wealth only has a known past for fixed deposits; the rest is shown at today&apos;s
        value from its start date.
        {data.warnings.length > 0 && <span className="text-amber"> ⚠ {data.warnings.join("; ")}</span>}
      </div>
    </div>
  );
}

function Chart({ dates, lines, view }: { dates: string[]; lines: Line[]; view: View }) {
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const first = dates[0], last = dates[dates.length - 1];
  const [from, setFrom] = useState(first);
  const [to, setTo] = useState(last);
  const [preset, setPreset] = useState("ALL");
  const [hover, setHover] = useState<number | null>(null);    // index into dates

  useEffect(() => {
    if (!box.current) return;
    const dim = cssVar("--color-dim", "#7b8492"), line = cssVar("--color-line", "#1f242d");
    const bg = cssVar("--color-panel", "#0d0f13"), raise = cssVar("--color-raise", "#151920");
    const chart = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: bg }, textColor: dim, fontSize: 11 },
      grid: { vertLines: { color: line }, horzLines: { color: line } },
      rightPriceScale: { borderColor: line },
      timeScale: { borderColor: line, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Normal, vertLine: { labelBackgroundColor: raise, color: dim },
                   horzLine: { labelBackgroundColor: raise, color: dim } },
      localization: { priceFormatter: (v: number) => inr(v) },
    });
    for (const l of lines) {
      const points = dates.map((d, k) => ({ time: d as Time, value: l.values[k] })).filter((p) => p.value != null) as
        { time: Time; value: number }[];
      if (!points.length) continue;
      if (view === "gain") {
        const s = chart.addBaselineSeries({
          baseValue: { type: "price", price: 0 }, lineWidth: 2, priceLineVisible: false,
          topLineColor: cssVar("--color-up", "#2bd47d"), topFillColor1: "rgba(43,212,125,0.28)", topFillColor2: "rgba(43,212,125,0.02)",
          bottomLineColor: cssVar("--color-down", "#ff5263"), bottomFillColor1: "rgba(255,82,99,0.02)", bottomFillColor2: "rgba(255,82,99,0.28)",
        });
        s.setData(points);
      } else if (l.kind === "area") {
        const s = chart.addAreaSeries({ lineColor: l.color, topColor: `${l.color}66`, bottomColor: `${l.color}10`,
                                        lineWidth: 2, priceLineVisible: false });
        s.setData(points);
      } else {
        const s = chart.addLineSeries({ color: l.color, lineWidth: 2, priceLineVisible: false,
                                        lineStyle: l.kind === "dashed" ? LineStyle.Dashed : LineStyle.Solid });
        s.setData(points);
      }
    }
    chart.timeScale().setVisibleRange({ from: from as Time, to: to as Time });
    chart.subscribeCrosshairMove((p) => setHover(p.time ? dates.indexOf(String(p.time)) : null));
    chart.timeScale().subscribeVisibleTimeRangeChange((r) => {
      if (!r) return;
      setFrom(String(r.from) < first ? first : String(r.from));
      setTo(String(r.to) > last ? last : String(r.to));
      setPreset("");
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines]);

  const show = (f: string, t: string, label = "") => {
    const lo = f < first ? first : f, hi = t > last ? last : t;
    if (lo >= hi) return;
    chartRef.current?.timeScale().setVisibleRange({ from: lo as Time, to: hi as Time });
    setFrom(lo);
    setTo(hi);
    setPreset(label);
  };

  // Change over the visible window, for the first (main) series.
  const main = lines.find((l) => l.key === "market" || l.key === "gain") ?? lines[0];
  const iFrom = dates.findIndex((d) => d >= from), iTo = (() => {
    let i = dates.length - 1;
    while (i > 0 && dates[i] > to) i--;
    return i;
  })();
  const startV = main?.values[iFrom] ?? null, endV = main?.values[iTo] ?? null;
  const at = hover ?? iTo;

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
        {lines.slice().reverse().map((l) => (
          <span key={l.key} className="flex items-center gap-1 text-[11px]">
            <i className="inline-block h-2 w-3" style={{ background: l.color, opacity: l.kind === "dashed" ? 0.6 : 1 }} />
            <span className="text-dim">{l.label}</span>
            <span className={`tabular-nums ${view === "gain" ? tone(l.values[at]) : ""}`}>
              {view === "gain" ? signed(l.values[at]) : inr((l.own ?? l.values)[at])}
            </span>
          </span>
        ))}
        {(view === "networth" || view === "classes") && (
          <span className="flex items-center gap-1 text-[11px]">
            <span className="text-dim">Total</span><span className="tabular-nums text-amber">{inr(lines[0]?.values[at])}</span>
          </span>
        )}
        <span className="text-[10.5px] text-dim">{dates[at]}</span>
        <span className="ml-auto flex">
          {PRESETS.map((p) => (
            <button key={p.label} onClick={() => show(p.days ? shiftDays(last, p.days) : first, last, p.label)}
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
        {view !== "gain" && view !== "networth" && view !== "classes" && startV && endV ? (
          <span className={`normal-case tracking-normal ${tone(endV - startV)}`}>
            {signed(endV - startV)} ({pct(endV / startV - 1, 1)}) in this period
          </span>
        ) : null}
        <span className="ml-auto normal-case tracking-normal">drag to pan, scroll to zoom</span>
      </div>
      <div ref={box} className="min-h-[180px] flex-1" />
    </>
  );
}
