import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { ASSET_NAME, inr, num, pct, signed, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty, Seg } from "../ui";

type Metric = "return" | "unrealized" | "total" | "xirr" | "beta" | "risk";
type Size = "value" | "equal" | "risk";
type Period = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y" | "YTD";

const METRICS: { value: Metric; label: string; title: string; diverging: boolean }[] = [
  { value: "return", label: "RETURN", title: "Price return over the period (dividends included); today's move is live", diverging: true },
  { value: "unrealized", label: "UNRL %", title: "Unrealised gain on cost", diverging: true },
  { value: "total", label: "TOTAL %", title: "Total return incl. dividends and coupons", diverging: true },
  { value: "xirr", label: "XIRR", title: "Annualised money-weighted return", diverging: true },
  { value: "beta", label: "BETA", title: "Beta vs the benchmark (1 = moves with it)", diverging: true },
  { value: "risk", label: "RISK SHARE", title: "Share of portfolio VaR from this holding", diverging: false },
];
const PERIODS: Period[] = ["1D", "1W", "1M", "3M", "6M", "1Y", "YTD"];
const SIZES: { value: Size; label: string }[] = [
  { value: "value", label: "VALUE" }, { value: "equal", label: "EQUAL" }, { value: "risk", label: "RISK" },
];

interface Tile {
  symbol: string; name: string; cls: string; size: number; metric: number | null; value: number | null;
  weight: number | null; ret: number | null; unrl: number | null; xirr: number | null; beta: number | null;
  risk: number | null; total: number | null;
}
interface Rect { x: number; y: number; w: number; h: number }

/** Squarified treemap (Bruls, Huizing & van Wijk): rows of tiles whose aspect
 *  ratios stay close to square, so small holdings remain readable. */
function squarify(sizes: number[], box: Rect): Rect[] {
  const total = sizes.reduce((a, b) => a + b, 0);
  if (!total || box.w <= 0 || box.h <= 0) return sizes.map(() => ({ x: box.x, y: box.y, w: 0, h: 0 }));
  const scale = (box.w * box.h) / total;
  const areas = sizes.map((s) => s * scale);
  const out: Rect[] = new Array(sizes.length);
  let { x, y, w, h } = box;
  let i = 0;
  const worst = (row: number[], side: number) => {
    const s = row.reduce((a, b) => a + b, 0);
    const mx = Math.max(...row), mn = Math.min(...row);
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  while (i < areas.length) {
    const side = Math.min(w, h);
    const row = [areas[i]];
    let j = i + 1;
    while (j < areas.length && worst([...row, areas[j]], side) <= worst(row, side)) row.push(areas[j++]);
    const s = row.reduce((a, b) => a + b, 0);
    if (w >= h) {
      const cw = s / h;
      let cy = y;
      row.forEach((a, k) => { out[i + k] = { x, y: cy, w: cw, h: a / cw }; cy += a / cw; });
      x += cw; w -= cw;
    } else {
      const rh = s / w;
      let cx = x;
      row.forEach((a, k) => { out[i + k] = { x: cx, y, w: a / rh, h: rh }; cx += a / rh; });
      y += rh; h -= rh;
    }
    i = j;
  }
  return out;
}

/** Diverging red-grey-green (or grey-amber for one-sided metrics). */
function colour(v: number | null, range: number, diverging: boolean, centre: number): string {
  if (v == null || !Number.isFinite(v)) return "var(--color-raise)";
  if (!diverging) {
    const t = Math.min(1, Math.max(0, v / (range || 1)));
    return `rgb(${Math.round(30 + t * 225)} ${Math.round(34 + t * 142)} ${Math.round(41 - t * 41)})`;
  }
  const t = Math.max(-1, Math.min(1, (v - centre) / (range || 1)));
  const a = Math.abs(t);
  const [r, g, b] = t >= 0 ? [43, 212, 125] : [255, 82, 99];
  const mix = (c: number, base: number) => Math.round(base + (c - base) * (0.15 + 0.85 * a));
  return `rgb(${mix(r, 30)} ${mix(g, 34)} ${mix(b, 41)})`;
}

function saved<T extends string>(key: string, fallback: T): T {
  try { return (localStorage.getItem(key) as T) || fallback; } catch { return fallback; }
}
function keep(key: string, v: string) {
  try { localStorage.setItem(key, v); } catch { /* optional */ }
}

/** Holdings as a heatmap: area by value (or equal, or risk), colour by the
 *  metric and period you pick, optionally against the benchmark. Grouped by
 *  asset class if you like: click a group's heading to zoom into it. Updates
 *  with live prices; click a tile to select the stock for CHART, NEWS and the rest. */
export function HeatmapPane() {
  const portfolio = useStore((s) => s.portfolio);
  const live = useStore((s) => s.live);
  const selected = useStore((s) => s.selected);
  const select = useStore((s) => s.select);
  const [metric, setMetric] = useState<Metric>(() => {
    const m = saved<Metric | "day">("qt.heatmap.metric", "return");
    return m === "day" ? "return" : m;
  });
  const [period, setPeriod] = useState<Period>(() => saved<Period>("qt.heatmap.period", "1D"));
  const [relative, setRelative] = useState(() => saved<"abs" | "rel">("qt.heatmap.relative", "abs") === "rel");
  const [grouped, setGrouped] = useState(() => saved<"flat" | "class">("qt.heatmap.grouped", "flat") === "class");
  const [focus, setFocus] = useState<string | null>(null);     // asset class zoomed into
  const [size, setSize] = useState<Size>("value");
  const [hover, setHover] = useState<Tile | null>(null);
  const [periodData, setPeriodData] = useState<{ period: string; returns: Record<string, number | null>;
                                                 benchmark_return: number | null; from: string | null; to: string | null } | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 0, h: 0 });
  const hasTiles = (portfolio?.holdings ?? []).some((h) => (h.value ?? 0) > 0);

  useEffect(() => {
    if (!box.current) return;
    // Measure now as well: ResizeObserver only reports on a rendered frame, which
    // a hidden or background window may not produce for a while.
    setDims({ w: box.current.clientWidth, h: box.current.clientHeight });
    const ro = new ResizeObserver(([e]) => setDims({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, [hasTiles]);

  // Period returns are computed by the engine from the local price cache; refetched
  // whenever the metrics are recomputed (import, benchmark change, live minute).
  useEffect(() => {
    if (!hasTiles || metric !== "return") return;
    let alive = true;
    api.periodReturns(period).then((d) => { if (alive) setPeriodData(d); }).catch(() => { /* tiles stay grey */ });
    return () => { alive = false; };
  }, [portfolio, period, metric, hasTiles]);

  const totalVar = portfolio?.metrics?.var ?? null;
  const benchLive = live?.quotes[portfolio?.params.benchmark ?? ""]?.change_pct ?? null;
  const benchRet = period === "1D" && benchLive != null ? benchLive
    : periodData?.period === period ? periodData.benchmark_return : null;

  const tiles = useMemo<Tile[]>(() => {
    const rows = (portfolio?.holdings ?? []).filter((h) => (h.value ?? 0) > 0);
    return rows.map((h) => {
      const q = live?.quotes[h.symbol];
      const l = live?.portfolio?.holdings[h.symbol];
      const value = l?.value ?? h.value;
      const unrl = l?.unrealized_pnl ?? h.unrealized_pnl;
      const cost = value != null && unrl != null ? value - unrl : null;
      const fromPeriod = periodData?.period === period ? periodData.returns[h.symbol] ?? null : null;
      const ret = period === "1D" && q?.change_pct != null ? q.change_pct : fromPeriod;
      const t: Tile = {
        symbol: h.symbol, name: h.name ?? "", cls: h.asset_class ?? "equity", size: 0, metric: null, value,
        weight: h.weight, ret, unrl: cost && cost > 0 && unrl != null ? unrl / cost : null,
        xirr: h.xirr ?? null, beta: h.beta, total: h.total_return_pct ?? null,
        risk: totalVar && h.component_var != null ? h.component_var / totalVar : null,
      };
      const raw = metric === "return" ? t.ret : metric === "unrealized" ? t.unrl : metric === "total" ? t.total
        : metric === "xirr" ? t.xirr : metric === "beta" ? t.beta : t.risk;
      t.metric = metric === "return" && relative && raw != null && benchRet != null ? raw - benchRet : raw;
      t.size = size === "equal" ? 1 : size === "risk" ? Math.max(Math.abs(t.risk ?? 0), 1e-4) : Math.max(value ?? 0, 0);
      return t;
    }).sort((a, b) => b.size - a.size);
  }, [portfolio, live, metric, size, totalVar, period, periodData, relative, benchRet]);

  const meta = METRICS.find((m) => m.value === metric)!;
  const centre = metric === "beta" ? 1 : 0;
  const range = useMemo(() => {
    const d = tiles.map((t) => t.metric).filter((v): v is number => v != null && Number.isFinite(v))
      .map((v) => Math.abs(v - centre)).sort((a, b) => a - b);
    if (!d.length) return 1;
    return d[Math.min(d.length - 1, Math.floor(d.length * 0.9))] || d[d.length - 1] || 1;
  }, [tiles, centre]);

  // Layout: flat, or classes first (each class a block with a heading), or one class zoomed in.
  const HEAD = 16;
  const layout = useMemo(() => {
    const full: Rect = { x: 0, y: 0, w: dims.w, h: dims.h };
    const shown = focus ? tiles.filter((t) => t.cls === focus) : tiles;
    if (!grouped || focus) {
      return { groups: [] as { cls: string; rect: Rect; value: number; metric: number | null }[],
               rects: new Map(shown.map((t, i) => [t.symbol, squarify(shown.map((x) => x.size), full)[i]])) };
    }
    const classes = [...new Set(tiles.map((t) => t.cls))]
      .map((cls) => ({ cls, tiles: tiles.filter((t) => t.cls === cls) }))
      .map((g) => ({ ...g, size: g.tiles.reduce((s, t) => s + t.size, 0) }))
      .sort((a, b) => b.size - a.size);
    const blocks = squarify(classes.map((g) => g.size), full);
    const rects = new Map<string, Rect>();
    const groups = classes.map((g, i) => {
      const b = blocks[i];
      const inner = { x: b.x + 1, y: b.y + HEAD, w: Math.max(b.w - 2, 0), h: Math.max(b.h - HEAD - 1, 0) };
      squarify(g.tiles.map((t) => t.size), inner).forEach((r, k) => rects.set(g.tiles[k].symbol, r));
      const vals = g.tiles.filter((t) => t.metric != null);
      const wsum = vals.reduce((s, t) => s + (t.value ?? 0), 0);
      const avg = wsum > 0 ? vals.reduce((s, t) => s + (t.metric as number) * (t.value ?? 0), 0) / wsum : null;
      return { cls: g.cls, rect: b, value: g.tiles.reduce((s, t) => s + (t.value ?? 0), 0), metric: avg };
    });
    return { groups, rects };
  }, [tiles, dims, grouped, focus]);

  const fmt = (v: number | null) => (metric === "beta" ? num(v) : pct(v, metric === "return" && period === "1D" ? 2 : 1));
  const shownTiles = focus ? tiles.filter((t) => t.cls === focus) : tiles;
  const missing = shownTiles.filter((t) => t.metric == null).length;
  const portRet = (() => {
    const v = shownTiles.filter((t) => t.ret != null);
    const w = v.reduce((s, t) => s + (t.value ?? 0), 0);
    return w > 0 ? v.reduce((s, t) => s + (t.ret as number) * (t.value ?? 0), 0) / w : null;
  })();

  if (!portfolio) return <Empty title="Waiting for engine" />;
  if (!tiles.length) return <Empty title="No holdings to map" hint="Import a trade report to see your holdings as a heatmap." />;

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
        <Seg<Metric> label="COLOUR" value={metric} options={METRICS} onChange={(v) => { setMetric(v); keep("qt.heatmap.metric", v); }} />
        {metric === "return" && (
          <>
            <Seg<Period> label="OVER" value={period} options={PERIODS.map((p) => ({ value: p, label: p }))}
                         onChange={(v) => { setPeriod(v); keep("qt.heatmap.period", v); }} />
            <Seg<"abs" | "rel"> label="SHOW" value={relative ? "rel" : "abs"} hideLabel
                                options={[{ value: "abs", label: "RETURN" }, { value: "rel", label: "VS BENCHMARK" }]}
                                onChange={(v) => { setRelative(v === "rel"); keep("qt.heatmap.relative", v); }} />
          </>
        )}
        <Seg<Size> label="SIZE" value={size} options={SIZES} onChange={setSize} />
        <Seg<"flat" | "class"> label="GROUP" value={grouped ? "class" : "flat"} hideLabel
                               options={[{ value: "flat", label: "ALL" }, { value: "class", label: "BY CLASS" }]}
                               onChange={(v) => { setGrouped(v === "class"); setFocus(null); keep("qt.heatmap.grouped", v); }} />
        <span className="ml-auto flex items-center gap-1.5 text-[10px] text-dim" title={meta.title}>
          {meta.diverging ? fmt(centre - range) : fmt(0)}
          <span className="inline-block h-2 w-24"
                style={{ background: meta.diverging
                  ? `linear-gradient(90deg, ${colour(centre - range, range, true, centre)}, ${colour(centre, range, true, centre)}, ${colour(centre + range, range, true, centre)})`
                  : `linear-gradient(90deg, ${colour(0, range, false, 0)}, ${colour(range, range, false, 0)})` }} />
          {fmt(meta.diverging ? centre + range : range)}
        </span>
      </div>
      {focus && (
        <div className="flex items-center gap-2 border-b border-line px-3 py-1 text-[10.5px]">
          <button type="button" onClick={() => setFocus(null)} className="text-cyan hover:underline">ALL CLASSES</button>
          <span className="text-dim">›</span><span>{(ASSET_NAME[focus] ?? focus).toUpperCase()}</span>
        </div>
      )}
      <div ref={box} className="relative min-h-[160px] flex-1 overflow-hidden" onMouseLeave={() => setHover(null)}>
        {layout.groups.map((g) => (
          <button key={`g:${g.cls}`} type="button" onClick={() => setFocus(g.cls)} title={`Zoom into ${ASSET_NAME[g.cls] ?? g.cls}`}
                  className="tile-anim absolute flex items-center justify-between overflow-hidden border border-line bg-bg px-1.5 text-left text-[9.5px] tracking-widest text-dim hover:text-ink"
                  style={{ left: g.rect.x, top: g.rect.y, width: g.rect.w, height: HEAD }}>
            <span className="truncate">{(ASSET_NAME[g.cls] ?? g.cls).toUpperCase()} · {inr(g.value)}</span>
            {g.metric != null && <span className="ml-1 tabular-nums" style={{ color: colour(g.metric, range, meta.diverging, centre) }}>{fmt(g.metric)}</span>}
          </button>
        ))}
        {shownTiles.map((t) => {
          const r = layout.rects.get(t.symbol);
          if (!r || r.w < 1 || r.h < 1) return null;
          const big = r.w > 70 && r.h > 38;
          const mid = r.w > 42 && r.h > 22;
          return (
            <button key={t.symbol} type="button" onClick={() => select(t.symbol)} onMouseEnter={() => setHover(t)}
                    aria-label={`${t.symbol} ${meta.label} ${fmt(t.metric)}`}
                    className={`tile-anim absolute flex flex-col items-center justify-center overflow-hidden border text-center ${t.symbol === selected ? "z-10 border-amber" : "border-bg"}`}
                    style={{ left: r.x, top: r.y, width: r.w, height: r.h, backgroundColor: colour(t.metric, range, meta.diverging, centre) }}>
              {mid && <span className={`font-semibold text-white/95 ${big ? "text-[12px]" : "text-[10px]"}`}>{ticker(t.symbol)}</span>}
              {big && <span className="text-[11px] tabular-nums text-white/85">{fmt(t.metric)}</span>}
              {big && r.h > 58 && <span className="text-[9.5px] tabular-nums text-white/60">{pct(t.weight, 1)}</span>}
            </button>
          );
        })}
        {hover && (
          <div className="pointer-events-none absolute bottom-2 left-2 z-20 min-w-[180px] border border-line bg-bg/95 px-2 py-1.5 text-[10.5px] shadow-lg">
            <div className="font-semibold text-cyan">{ticker(hover.symbol)} <span className="font-normal text-dim">{hover.name}</span></div>
            <div className="mt-0.5 grid grid-cols-[auto_auto] gap-x-3 tabular-nums">
              <span className="text-dim">Value</span><span className="text-right">{inr(hover.value)} · {pct(hover.weight, 1)}</span>
              <span className="text-dim">Return {period}</span><span className="text-right">{pct(hover.ret, 2)}</span>
              {benchRet != null && hover.ret != null && <>
                <span className="text-dim">vs benchmark</span><span className="text-right">{pct(hover.ret - benchRet, 2)}</span>
              </>}
              <span className="text-dim">Unrealised</span><span className="text-right">{pct(hover.unrl, 1)}</span>
              <span className="text-dim">Total return</span><span className="text-right">{pct(hover.total, 1)}</span>
              <span className="text-dim">XIRR</span><span className="text-right">{pct(hover.xirr, 1)}</span>
              <span className="text-dim">Beta</span><span className="text-right">{num(hover.beta)}</span>
              <span className="text-dim">Risk share</span><span className="text-right">{pct(hover.risk, 1)}</span>
            </div>
          </div>
        )}
      </div>
      <div className="border-t border-line px-3 py-1 text-[10px] text-dim">
        {shownTiles.length} holdings · {meta.title.toLowerCase()}
        {metric === "return" && <> · portfolio {pct(portRet, 2)}{benchRet != null && <> vs benchmark {pct(benchRet, 2)}</>}</>}
        {metric === "return" && period !== "1D" && periodData?.from && <> · {periodData.from} to {periodData.to}</>}
        {missing > 0 && <> · {missing} without a figure (grey)</>}
        {metric === "return" && period === "1D" && live?.portfolio?.day_pnl != null && <> · day {signed(live.portfolio.day_pnl)}</>}
        {" "}· colour scale fits 90% of holdings
      </div>
    </div>
  );
}
