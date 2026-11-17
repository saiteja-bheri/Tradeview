import { useEffect, useMemo, useRef, useState } from "react";
import { ChartTip, ZoomHint, plotFrac, useZoomPan } from "../chartKit";
import { api } from "../api/client";
import type { StressResult } from "../api/types";
import { inr, num, pct, signed, ticker, tone } from "../format";
import { useStore } from "../state/store";
import { Empty, Seg } from "../ui";

const SHOCKS = [-40, -30, -20, -10, 10, 20, 30, 40].map((v) => ({ value: v, label: `${v > 0 ? "+" : ""}${v}%` }));
const HORIZONS = [{ value: 5, label: "1W" }, { value: 21, label: "1M" }, { value: 63, label: "3M" }];

/** What a market downturn would do to the portfolio, from the holdings'
 *  betas, covariance and correlations, plus past crises and Monte Carlo. */
export function StressPane() {
  const hasHoldings = useStore((s) => (s.portfolio?.holdings.length ?? 0) > 0);
  const [shock, setShock] = useState(-20);
  const [horizon, setHorizon] = useState(21);
  const [history, setHistory] = useState(true);
  const [r, setR] = useState<StressResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (s = shock, h = horizon, hist = history) => {
    setBusy(true);
    setError(null);
    try {
      setR(await api.stress({ shock_pct: s, horizon_days: h, history: hist }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // Once a result is on screen, any change (preset, typed %, horizon, history) re-runs it.
  useEffect(() => {
    if (!r) return;
    const t = setTimeout(() => run(shock, horizon, history), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shock, horizon, history]);

  // Runs by itself the first time the tab has holdings to test; RUN re-runs on demand.
  const started = useRef(false);
  useEffect(() => {
    if (hasHoldings && !started.current) {
      started.current = true;
      run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasHoldings]);

  // A new benchmark or lookback changes every beta: re-run a result already on screen.
  const bench = useStore((s) => `${s.portfolio?.params.benchmark}|${s.portfolio?.params.lookback_days}`);
  const shown = useRef(bench);
  useEffect(() => {
    if (shown.current === bench) return;
    shown.current = bench;
    if (r) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bench]);

  const hz = HORIZONS.find((x) => x.value === (r?.horizon_days ?? horizon))?.label ?? `${r?.horizon_days}D`;

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
        <Seg<number> label="MARKET MOVE" value={shock} options={SHOCKS} onChange={setShock} />
        <label className="flex items-center gap-1 text-[10px] tracking-widest text-dim">
          OR
          <input type="number" min={-90} max={100} step={1} value={shock} aria-label="Custom market move, percent (negative = fall)"
                 onChange={(e) => setShock(Number(e.target.value))}
                 className="w-14 border border-line bg-bg px-1 py-0.5 text-right text-ink outline-none focus:border-amber" />%
        </label>
        <Seg<number> label="OVER" value={horizon} options={HORIZONS} onChange={setHorizon} />
        <label className="flex items-center gap-1.5 text-[10px] tracking-widest text-dim"
               title="Replays crashes (2008, 2013, 2015-16, 2020, 2022) and rallies (2009, 2014, 2020-21, 2023-24). The first run downloads long price history once; it is cached after that.">
          <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} className="accent-amber" />
          PAST CRASHES & RALLIES
        </label>
        <button onClick={() => run()} disabled={busy || !hasHoldings}
                className="ml-auto border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-amber">
          {busy ? "SIMULATING…" : "RUN STRESS TEST"}
        </button>
      </div>

      {error && <div role="alert" className="px-3 py-2 text-down">{error}</div>}

      {!r ? (
        <Empty title={hasHoldings ? "Test the portfolio against a downturn" : "No holdings yet"}
               hint="Uses each holding's beta, the covariance and correlations behind the risk metrics, past crashes, and 10,000 simulated months." />
      ) : (
        <>
          <div className="border-b border-line px-3 py-3">
            <div className="text-[10px] tracking-widest text-dim">
              IF {r.benchmark_name.toUpperCase()} {r.custom.shock >= 0 ? "RISES" : "FALLS"} {num(Math.abs(r.custom.shock) * 100, 0)}% OVER {hz}
            </div>
            <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
              <span className={`text-2xl font-semibold ${tone(r.custom.pnl)}`}>{signed(r.custom.pnl)}</span>
              <span className={tone(r.custom.pnl)}>{pct(r.custom.pnl_pct, 1)}</span>
              <span className="text-dim">likely between {signed(r.custom.low)} and {signed(r.custom.high)}</span>
            </div>
            <div className="mt-1 text-[10.5px] text-dim">
              Portfolio beta {num(r.portfolio_beta)} · value {inr(r.portfolio_value)} · {r.observations} days of history to {r.as_of}
            </div>
          </div>

          <Section title="MARKET FALLS">
            <table className="grid-table">
              <thead><tr><th className="l">Market</th><th className="r">Your P&amp;L</th><th className="r">%</th><th className="r">90% range</th></tr></thead>
              <tbody>
                {r.shocks.map((s) => (
                  <tr key={s.shock} className={Math.abs(s.shock - r.custom.shock) < 1e-9 ? "bg-raise" : ""}>
                    <td className="l">{num(s.shock * 100, 0)}%</td>
                    <td className={`r ${tone(s.pnl)}`}>{signed(s.pnl)}</td>
                    <td className={`r ${tone(s.pnl)}`}>{pct(s.pnl_pct, 1)}</td>
                    <td className="r text-dim">{signed(s.low)} to {signed(s.high)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          {r.crises.length > 0 && (
            <Section title="PAST CRASHES AND RALLIES REPLAYED ON TODAY'S HOLDINGS">
              <table className="grid-table">
                <thead><tr><th className="l">Event</th><th className="r">Market</th><th className="r">Your P&amp;L</th><th className="r">%</th>
                  <th className="r" title="Share of holdings priced from their own history in that period; the rest use beta">Own data</th></tr></thead>
                <tbody>
                  {[...r.crises].sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "crash" ? -1 : 1)).map((c) => (
                    <tr key={c.id} title={`${c.start} to ${c.end}`}>
                      <td className="l">
                        <span className={`mr-1.5 text-[9px] tracking-widest ${c.kind === "rally" ? "text-up" : "text-down"}`}>
                          {c.kind === "rally" ? "RALLY" : "CRASH"}
                        </span>
                        {c.label}
                      </td>
                      {c.available ? (
                        <>
                          <td className={`r ${tone(c.market_move)}`}>{pct(c.market_move, 1)}</td>
                          <td className={`r ${tone(c.pnl)}`}>{signed(c.pnl)}</td>
                          <td className={`r ${tone(c.pnl)}`}>{pct(c.pnl_pct, 1)}</td>
                          <td className="r text-dim">{pct(c.actual_share, 0)}</td>
                        </>
                      ) : (
                        <td className="r text-dim" colSpan={4}>no index history for this period</td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          )}

          <Section title={`SIMULATED ${hz} OUTCOMES · ${r.monte_carlo.simulations.toLocaleString("en-IN")} RUNS`}>
            <Histogram r={r} />
            <div className="grid grid-cols-2 gap-x-6 px-3 pb-2 text-[10.5px]">
              <div className="space-y-1">
                <div className="text-[9px] tracking-widest text-down">DOWNSIDE</div>
                <Stat label="1-IN-20 LOSS" value={signed(r.monte_carlo.percentiles.p5)} />
                <Stat label="1-IN-100 LOSS" value={signed(r.monte_carlo.percentiles.p1)} />
                <Stat label="AVG WORST 5%" value={signed(r.monte_carlo.expected_shortfall_95)} />
                {Object.entries(r.monte_carlo.prob_loss).map(([k, v]) => (
                  <Stat key={k} label={`CHANCE OF −${k}% OR WORSE`} value={pct(v, 1)} />
                ))}
              </div>
              <div className="space-y-1">
                <div className="text-[9px] tracking-widest text-up">UPSIDE</div>
                <Stat label="1-IN-20 GAIN" value={signed(r.monte_carlo.percentiles.p95)} cls="text-up" />
                <Stat label="1-IN-100 GAIN" value={signed(r.monte_carlo.percentiles.p99)} cls="text-up" />
                <Stat label="AVG BEST 5%" value={signed(r.monte_carlo.expected_gain_95)} cls="text-up" />
                {Object.entries(r.monte_carlo.prob_gain).map(([k, v]) => (
                  <Stat key={k} label={`CHANCE OF +${k}% OR BETTER`} value={pct(v, 1)} />
                ))}
              </div>
            </div>
            <div className="px-3 pb-2 text-[10.5px] text-dim">
              Median outcome {signed(r.monte_carlo.percentiles.p50)} · half of all runs between{" "}
              {signed(r.monte_carlo.percentiles.p25)} and {signed(r.monte_carlo.percentiles.p75)}
            </div>
          </Section>

          <Section title="WHEN CORRELATIONS RISE">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 px-3 py-2 text-[10.5px]">
              <Stat label={`VAR ${num(r.correlation.confidence * 100, 0)}% · ${hz}`} value={inr(r.correlation.var_normal)} />
              <Stat label="WITH CRISIS CORRELATIONS" value={inr(r.correlation.var_stressed)} cls="text-down" />
              <Stat label="AVERAGE CORRELATION" value={num(r.correlation.avg_correlation)} />
              <Stat label="IN A CRISIS (ASSUMED)" value={num(r.correlation.avg_correlation_stressed)} />
            </div>
            <p className="px-3 pb-2 text-[10px] text-dim">
              In sell-offs, stocks tend to fall together. Here every correlation is moved halfway to 1 and VaR recomputed.
            </p>
          </Section>

          <Section title={`BY HOLDING · MARKET ${num(r.custom.shock * 100, 0)}%`}>
            <table className="grid-table">
              <thead><tr><th className="l">Holding</th><th className="r">Beta</th><th className="r">Move</th><th className="r">P&amp;L</th></tr></thead>
              <tbody>
                {[...r.custom.holdings].sort((a, b) => a.pnl - b.pnl).map((h) => (
                  <tr key={h.symbol}>
                    <td className="l text-cyan" title={h.name || undefined}>{ticker(h.symbol)}</td>
                    <td className="r">{num(h.beta)}</td>
                    <td className={`r ${tone(h.move)}`}>{pct(h.move, 1)}</td>
                    <td className={`r ${tone(h.pnl)}`}>{signed(h.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <p className="border-t border-line px-3 py-2 text-[10px] leading-relaxed text-dim">
            Built from past relationships between your holdings and {r.benchmark_name}: each move is beta × the market move,
            with the remaining covariance setting the range. Simulations use fat tails (Student t) and assume no drift. Not a
            forecast: future crises can differ from past ones.
            {r.unpriced.length > 0 && ` Not included (no prices): ${r.unpriced.join(", ")}.`}
          </p>
          {r.warnings.length > 0 && (
            <ul className="border-t border-line px-3 py-2 text-[10.5px] text-amber">
              {r.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-line">
      <div className="px-3 pb-1 pt-2.5 text-[10px] tracking-widest text-dim">{title}</div>
      <div className="overflow-x-auto">{children}</div>
    </section>
  );
}

function Stat({ label, value, cls = "" }: { label: string; value: string; cls?: string }) {
  return (
    <div>
      <div className="tracking-widest text-dim">{label}</div>
      <div className={`tabular-nums ${cls}`}>{value}</div>
    </div>
  );
}

/** Share of simulations at or below `x` (or at or above, for gains), from the
 *  histogram, interpolating linearly inside the bin that contains `x`. */
function tailShare(edges: number[], counts: number[], x: number, below: boolean): number {
  const n = counts.reduce((s, c) => s + c, 0) || 1;
  let acc = 0;
  for (let i = 0; i < counts.length; i++) {
    const lo = edges[i], hi = edges[i + 1];
    if (x >= hi) { acc += counts[i]; continue; }
    if (x > lo) acc += counts[i] * (x - lo) / (hi - lo || 1);
    break;
  }
  const atOrBelow = acc / n;
  return below ? atOrBelow : 1 - atOrBelow;
}

/** Distribution of simulated P&L, losses red and gains green, with the 1-in-20
 *  and 1-in-100 marks. Hover a bar for its range and how often it happened;
 *  click or drag to set a threshold and read the chance of doing worse (or
 *  better); scroll to zoom, drag with the threshold off to pan. */
function Histogram({ r }: { r: StressResult }) {
  const { edges, counts } = r.monte_carlo.histogram;
  const W = 560, H = 170, L = 10, R = 10, T = 14, B = 26;
  const P = useMemo(() => ({ W, L, R }), []);
  const svgRef = useRef<SVGSVGElement>(null);
  const full = useMemo<[number, number]>(() => [edges[0], edges[edges.length - 1]], [edges]);
  const z = useZoomPan(svgRef, full, P, (full[1] - full[0]) / 20);
  const [threshold, setThreshold] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const [lo, hi] = z.dom;
  const total = r.portfolio_value || 1;
  const n = counts.reduce((s, c) => s + c, 0) || 1;
  const max = Math.max(...counts, 1);
  const sx = (v: number) => L + ((v - lo) / (hi - lo || 1)) * (W - L - R);
  const valueAt = (clientX: number) => lo + plotFrac(svgRef.current, clientX, P) * (hi - lo);
  const marks = [
    { v: r.monte_carlo.percentiles.p1, label: "1/100" },
    { v: r.monte_carlo.percentiles.p5, label: "1/20" },
    { v: 0, label: "0" },
    { v: r.monte_carlo.percentiles.p95, label: "1/20" },
    { v: r.monte_carlo.percentiles.p99, label: "1/100" },
  ];
  const below = threshold != null && threshold < 0;
  const share = threshold != null ? tailShare(edges, counts, threshold, below) : null;

  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.shiftKey || threshold == null) { z.bind.onPointerDown(e); }
    if (!e.shiftKey) {
      setDragging(true);
      setThreshold(valueAt(e.clientX));
      svgRef.current?.setPointerCapture(e.pointerId);
    }
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const v = valueAt(e.clientX);
    if (dragging) setThreshold(v);
    else z.bind.onPointerMove(e);
    const i = edges.findIndex((x, k) => k < counts.length && v >= x && v < edges[k + 1]);
    setHover(i >= 0 ? i : null);
  };

  return (
    <div className="px-2">
      <div className="flex flex-wrap items-center gap-x-3 px-1 pb-1 text-[10.5px]">
        {threshold != null ? (
          <>
            <span className="tabular-nums">
              {below ? "Lose" : "Gain"} <span className={below ? "text-down" : "text-up"}>{signed(threshold)}</span>
              {" "}({pct(threshold / total, 1)}) or {below ? "worse" : "better"}:{" "}
              <span className="font-semibold text-amber">{pct(share, 1)}</span> of runs
              <span className="text-dim"> · about 1 in {share && share > 0 ? Math.max(1, Math.round(1 / share)).toLocaleString("en-IN") : "—"}</span>
            </span>
            <button type="button" onClick={() => setThreshold(null)} className="text-[10px] text-dim underline hover:text-ink">CLEAR</button>
          </>
        ) : <span className="text-dim">Click or drag on the chart to set a loss or gain and read its chance</span>}
        <ZoomHint zoomed={z.zoomed} reset={z.reset} extra="shift-drag pans when zoomed ·" />
      </div>
      <div className="relative overflow-x-auto">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img"
             className={`h-auto w-full min-w-[360px] cursor-crosshair touch-none select-none ${z.busy ? "" : "chart-anim"}`}
             aria-label="Histogram of simulated portfolio profit and loss"
             onPointerDown={onDown} onPointerMove={onMove}
             onPointerUp={() => { setDragging(false); z.bind.onPointerUp(); }}
             onPointerLeave={() => { setDragging(false); setHover(null); z.bind.onPointerLeave(); }}
             onDoubleClick={z.bind.onDoubleClick}>
          <defs><clipPath id="hist-clip"><rect x={L} y={0} width={W - L - R} height={H} /></clipPath></defs>
          <g clipPath="url(#hist-clip)">
            {counts.map((c, i) => {
              const x0 = sx(edges[i]), x1 = sx(edges[i + 1]);
              const h = (c / max) * (H - T - B);
              const mid = (edges[i] + edges[i + 1]) / 2;
              const inTail = threshold != null && (below ? mid <= threshold : mid >= threshold);
              return (
                <path key={i} className="tw"
                      d={`M${(x0 + 0.5).toFixed(1)},${H - B} V${(H - B - h).toFixed(1)} H${Math.max(x1 - 0.5, x0 + 1).toFixed(1)} V${H - B} Z`}
                      fill={mid < 0 ? "var(--color-down)" : "var(--color-up)"}
                      opacity={hover === i ? 1 : threshold == null || inTail ? 0.8 : 0.25} />
              );
            })}
            {marks.filter((m) => m.v >= lo && m.v <= hi).map((m) => (
              <g key={`${m.label}${m.v}`}>
                <line className="tw" x1={sx(m.v)} x2={sx(m.v)} y1={T} y2={H - B} stroke="var(--color-ink)" strokeDasharray="3 3" strokeWidth="1" />
                <text x={sx(m.v) + 3} y={T + 2} fontSize="9" fill="var(--color-ink)">{m.label}</text>
              </g>
            ))}
            {threshold != null && threshold >= lo && threshold <= hi && (
              <line x1={sx(threshold)} x2={sx(threshold)} y1={T - 6} y2={H - B} stroke="var(--color-amber)" strokeWidth="2" />
            )}
          </g>
          <text x={L} y={H - 8} fontSize="9" fill="var(--color-dim)">{signed(lo)}</text>
          <text x={W / 2} y={H - 8} fontSize="9" textAnchor="middle" fill="var(--color-dim)">{signed((lo + hi) / 2)}</text>
          <text x={W - R} y={H - 8} fontSize="9" textAnchor="end" fill="var(--color-dim)">{signed(hi)}</text>
        </svg>
        {hover != null && !dragging && (
          <ChartTip x={sx((edges[hover] + edges[hover + 1]) / 2)} y={T + 10} W={W} H={H}>
            <div className="tabular-nums">{signed(edges[hover])} to {signed(edges[hover + 1])}</div>
            <div className="text-dim tabular-nums">{pct(edges[hover] / total, 1)} to {pct(edges[hover + 1] / total, 1)}</div>
            <div className="mt-0.5 tabular-nums">{pct(counts[hover] / n, 2)} of runs ({counts[hover].toLocaleString("en-IN")})</div>
            <div className="text-dim tabular-nums">
              {edges[hover + 1] <= 0
                ? `${pct(tailShare(edges, counts, edges[hover + 1], true), 1)} this bad or worse`
                : `${pct(tailShare(edges, counts, edges[hover], false), 1)} this good or better`}
            </div>
          </ChartTip>
        )}
      </div>
    </div>
  );
}
