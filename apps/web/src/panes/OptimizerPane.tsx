import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { FrontierPoint, OptimizeRequest, OptimizerResult, OptPortfolio } from "../api/types";
import { num, pct, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty, Seg } from "../ui";
import { ZoomHint, useZoomPan } from "../chartKit";

const LOOKBACKS = [{ value: 126, label: "6M" }, { value: 252, label: "1Y" }, { value: 504, label: "2Y" },
                   { value: 756, label: "3Y" }, { value: 1260, label: "5Y" }];
type ColKey = keyof OptimizerResult["portfolios"] | "picked";
const COLS: { key: ColKey; label: string; title: string; color: string }[] = [
  { key: "max_sharpe", label: "MAX SHARPE", title: "Best return per unit of risk (uses historical returns)", color: "var(--color-amber)" },
  { key: "target", label: "TARGET", title: "Your return or risk target", color: "#c792ea" },
  { key: "picked", label: "PICKED", title: "The frontier point you clicked", color: "var(--color-cyan)" },
  { key: "min_variance", label: "MIN RISK", title: "Lowest volatility; ignores expected returns", color: "var(--color-up)" },
  { key: "equal_weight", label: "EQUAL", title: "Same weight in every stock, for reference", color: "var(--color-ink)" },
  { key: "current", label: "YOURS", title: "Your current mix of these stocks", color: "var(--color-down)" },
];

const SCOPES = [{ value: "portfolio", label: "PORTFOLIO" }, { value: "starred", label: "★ STARRED" },
                { value: "both", label: "BOTH" }] as const;
type Scope = (typeof SCOPES)[number]["value"];
type TargetKind = "none" | "return" | "volatility";

function PctInput({ label, value, onChange, title, min = 0, max = 100, step = 1, width = "w-14" }: {
  label: string; value: number | null; onChange: (v: number | null) => void; title?: string;
  min?: number; max?: number; step?: number; width?: string;
}) {
  return (
    <label className="flex items-center gap-1 text-[10px] tracking-widest text-dim" title={title}>
      {label}
      <input type="number" min={min} max={max} step={step} value={value == null ? "" : +(value * 100).toFixed(2)}
             aria-label={`${label}, percent`}
             onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value) / 100)}
             className={`${width} border border-line bg-bg px-1 py-0.5 text-right text-ink outline-none focus:border-amber`} />%
    </label>
  );
}

/** Mean-variance (Markowitz) optimisation of the whole portfolio by default,
 *  or of the starred (★) stocks, or both. Every constraint is adjustable and,
 *  after the first run, changes re-run it automatically. */
export function OptimizerPane() {
  const starred = useStore((s) => s.watch.filter((w) => w.starred).length);
  const savedRf = useStore((s) => s.portfolio?.params.risk_free_rate ?? 0.065);
  const benchmark = useStore((s) => s.portfolio?.params.benchmark);
  const [lookback, setLookback] = useState(504);
  const [cap, setCap] = useState<number | null>(0.35);
  const [floor, setFloor] = useState<number | null>(0);
  const [rf, setRf] = useState<number | null>(null);             // null = the saved setting
  const [targetKind, setTargetKind] = useState<TargetKind>("none");
  const [targetValue, setTargetValue] = useState<number | null>(0.15);
  const [exclude, setExclude] = useState<string[]>([]);
  const [scope, setScope] = useState<Scope>("portfolio");
  const [auto, setAuto] = useState(true);
  const held = useStore((s) => (s.portfolio?.holdings ?? []).filter((h) => !h.symbol.startsWith("BOND:")).length);
  const count = (scope === "portfolio" ? held : scope === "starred" ? starred : held + starred) - exclude.length;
  const [result, setResult] = useState<OptimizerResult | null>(null);
  const [picked, setPicked] = useState<FrontierPoint | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const request = (): OptimizeRequest => ({
    scope, lookback_days: lookback, max_weight: Math.min(Math.max(cap ?? 1, 0.01), 1),
    min_weight: Math.min(Math.max(floor ?? 0, 0), 0.99), risk_free_rate: rf, exclude,
    target_return: targetKind === "return" ? targetValue : null,
    target_volatility: targetKind === "volatility" && targetValue ? targetValue : null,
  });

  const run = async () => {
    const mine = ++seq.current;
    setBusy(true);
    setError(null);
    try {
      const r = await api.optimize(request());
      if (mine !== seq.current) return;
      setResult(r);
      setPicked(null);
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message);
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  };

  // After the first run, every change re-runs (debounced), and so does a new
  // risk-free rate or benchmark saved elsewhere.
  const key = JSON.stringify([request(), savedRf, benchmark]);
  useEffect(() => {
    if (!auto || count < 2) return;
    const t = setTimeout(run, 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, auto, count >= 2]);   // also once the holdings have loaded

  const cols = COLS.filter((c) => (c.key === "picked" ? picked?.weights : result?.portfolios[c.key as keyof OptimizerResult["portfolios"]]));
  const portfolioOf = (k: ColKey): OptPortfolio | null =>
    k === "picked" ? (picked?.weights ? { ...picked, sharpe: picked.sharpe ?? null, weights: picked.weights } : null)
      : (result?.portfolios[k] ?? null);

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
        <Seg<Scope> label="OPTIMISE" value={scope} options={[...SCOPES]}
                    onChange={(v) => { setScope(v); setExclude([]); setResult(null); setError(null); }} />
        <Seg<number> label="HISTORY" value={lookback} options={LOOKBACKS} onChange={setLookback} />
        <button onClick={run} disabled={busy || count < 2}
                className="ml-auto border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-amber">
          {busy ? "OPTIMISING…" : `RUN · ${count} ${count === 1 ? "STOCK" : "STOCKS"}`}
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
        <PctInput label="MAX PER STOCK" value={cap} onChange={setCap} min={1} max={100}
                  title="No stock gets more than this. Raised to 1/n automatically if too low to be fully invested." />
        <PctInput label="MIN PER STOCK" value={floor} onChange={setFloor} min={0} max={50}
                  title="Every stock gets at least this. Lowered to 1/n automatically if too high." />
        <PctInput label="RISK-FREE" value={rf ?? savedRf} onChange={(v) => setRf(v)} step={0.1} min={0} max={30}
                  title="Annual rate used for every Sharpe ratio here. Defaults to the rate in settings." />
        {rf != null && rf !== savedRf && (
          <button onClick={() => setRf(null)} className="text-[10px] text-dim underline hover:text-ink">RESET</button>
        )}
        <Seg<TargetKind> label="TARGET" value={targetKind}
                         options={[{ value: "none", label: "NONE" }, { value: "return", label: "RETURN" }, { value: "volatility", label: "RISK" }]}
                         onChange={setTargetKind} />
        {targetKind !== "none" && (
          <PctInput label={targetKind === "return" ? "EARN" : "AT MOST"} value={targetValue} onChange={setTargetValue}
                    step={0.5} min={targetKind === "return" ? -50 : 1} max={200}
                    title={targetKind === "return" ? "Lowest-risk mix with this expected annual return"
                                                   : "Highest-return mix with at most this annual volatility"} />
        )}
        <label className="flex items-center gap-1.5 text-[10px] tracking-widest text-dim" title="Re-run automatically when a setting changes">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} className="accent-amber" />
          AUTO
        </label>
      </div>

      {error && <div role="alert" className="px-3 py-2 text-down">{error}</div>}

      {!result ? (
        <Empty title={count >= 2 ? (scope === "portfolio" ? "Optimise your whole portfolio" : "Ready to optimise")
                       : scope === "starred" ? "Star at least two stocks" : "Hold at least two stocks"}
               hint={busy ? "Optimising…" : "Finds the mix with the best return for its risk (max Sharpe) and the lowest-risk mix from cached daily prices in rupees. It runs by itself and re-runs whenever you change a setting (turn AUTO off to run only with RUN)."} />
      ) : (
        <>
          <Frontier r={result} picked={picked} onPick={setPicked} />
          <div className="overflow-x-auto">
            <table className="grid-table">
              <thead>
                <tr>
                  <th className="l">Stock</th>
                  <th className="r" title="Annualised historical return">Ret</th>
                  <th className="r" title="Annualised volatility">Vol</th>
                  <th className="r" title="The stock's own Sharpe ratio">Shrp</th>
                  {cols.map((c) => <th key={c.key} className="r" title={c.title} style={{ color: c.color }}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {result.assets.map((a) => (
                  <tr key={a.symbol}>
                    <td className="l" title={a.name || undefined}>
                      <button onClick={() => setExclude((x) => [...x, a.symbol])} title={`Leave ${a.symbol} out and re-run`}
                              aria-label={`Exclude ${a.symbol}`} className="mr-1 text-dim/50 hover:text-down">×</button>
                      <span className="text-cyan">{ticker(a.symbol)}</span>
                      {a.held && <span className="ml-1 text-[9px] tracking-widest text-up">HELD</span>}
                    </td>
                    <td className="r text-dim">{pct(a.return, 1)}</td>
                    <td className="r text-dim">{pct(a.volatility, 1)}</td>
                    <td className="r text-dim">{num(a.sharpe)}</td>
                    {cols.map((c) => {
                      const w = portfolioOf(c.key)?.weights[a.symbol] ?? 0;
                      return (
                        <td key={c.key} className="r tabular-nums">
                          {w > 0.0005 ? (
                            <span className="inline-flex items-center justify-end gap-1.5">
                              <span className="inline-block h-1.5 bg-current opacity-60" style={{ width: `${Math.round(w * 36)}px`, color: c.color }} />
                              <span className={c.key === "max_sharpe" ? "text-amber" : "text-ink"}>{pct(w, 1)}</span>
                            </span>
                          ) : <span className="text-dim/50">·</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                {(["return", "volatility", "sharpe"] as const).map((k) => (
                  <tr key={k} className="border-t border-line">
                    <td className="l text-[10px] tracking-widest text-dim" colSpan={4}>
                      {k === "return" ? "EXPECTED RETURN" : k === "volatility" ? "VOLATILITY" : "SHARPE"}
                    </td>
                    {cols.map((c) => {
                      const p = portfolioOf(c.key);
                      return <td key={c.key} className="r tabular-nums">{p ? (k === "sharpe" ? num(p[k]) : pct(p[k], 1)) : "—"}</td>;
                    })}
                  </tr>
                ))}
              </tfoot>
            </table>
          </div>
          {exclude.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-3 py-1.5 text-[10px] text-dim">
              LEFT OUT
              {exclude.map((s) => (
                <button key={s} onClick={() => setExclude((x) => x.filter((y) => y !== s))} title="Put back"
                        className="border border-line px-1.5 py-0.5 text-ink hover:border-amber">{ticker(s)} ×</button>
              ))}
            </div>
          )}
          <div className="border-t border-line px-3 py-2 text-[10px] leading-relaxed text-dim">
            {result.observations} daily returns in INR, {result.from} to {result.to} · risk-free {pct(result.risk_free_rate, 1)} ·
            covariance shrunk {pct(result.shrinkage, 0)} toward average (Ledoit-Wolf) · long-only,
            {(result.min_weight ?? 0) > 0 ? ` ${pct(result.min_weight, 1)} to` : " at most"} {pct(result.max_weight, 0)} per stock.
            Expected returns are past averages and the least reliable input; MIN RISK does not depend on them.
            This is analysis, not a recommendation to trade.
          </div>
          {result.warnings.length > 0 && (
            <ul className="border-t border-line px-3 py-2 text-[10.5px] text-amber">
              {result.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/** Efficient frontier, risk on x and return on y. The frontier is shaded by
 *  Sharpe ratio; the dashed capital market line runs from the risk-free rate
 *  through MAX SHARPE. Hover any point for its figures and mix; click a
 *  frontier point to compare it in the table. */
function Frontier({ r, picked, onPick }: { r: OptimizerResult; picked: FrontierPoint | null; onPick: (p: FrontierPoint | null) => void }) {
  const W = 560, H = 250, L = 46, R = 14, T = 14, B = 30;
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; title: string; color: string; p: { return: number; volatility: number; sharpe?: number | null; weights?: Record<string, number> } } | null>(null);
  const ms = r.portfolios.max_sharpe;

  const P = useMemo(() => ({ W, L, R }), []);
  const allPts = useMemo(() => [
    ...r.frontier.map((f) => [f.volatility, f.return]),
    ...r.assets.map((a) => [a.volatility, a.return]),
    ...Object.values(r.portfolios).filter(Boolean).map((p) => [p!.volatility, p!.return]),
    [0, r.risk_free_rate],
  ], [r]);
  const fullX = useMemo<[number, number]>(() => [0, Math.max(...allPts.map((p) => p[0])) * 1.08 || 0.1], [allPts]);
  const z = useZoomPan(svgRef, fullX, P, (fullX[1] - fullX[0]) / 20);
  const [x0, x1] = z.dom;
  // The y axis fits whatever is in view, so zooming in spreads the points out.
  const inView = allPts.filter((p) => p[0] >= x0 && p[0] <= x1);
  const ys = (inView.length >= 2 ? inView : allPts).map((p) => p[1]);
  const yPad = (Math.max(...ys) - Math.min(...ys)) * 0.1 || 0.02;
  const y0 = Math.min(z.zoomed ? Infinity : 0, Math.min(...ys) - yPad), y1 = Math.max(...ys) + yPad;
  const sx = (v: number) => L + ((v - x0) / (x1 - x0 || 1)) * (W - L - R);
  const sy = (v: number) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);

  const ticks = (a: number, b: number) => Array.from({ length: 5 }, (_, i) => a + ((b - a) * i) / 4);
  const sharpes = r.frontier.map((f) => f.sharpe ?? 0);
  const sMin = Math.min(...sharpes), sMax = Math.max(...sharpes);
  const heat = (s: number | null | undefined) => {
    const t = sMax > sMin ? ((s ?? sMin) - sMin) / (sMax - sMin) : 1;
    return `hsl(${200 - t * 160} 85% ${50 + t * 8}%)`;   // cyan (low) to amber (high)
  };
  // Capital market line: from (0, rf) through the tangency portfolio to the chart's edge.
  const cml = ms && ms.volatility > 0
    ? { x2: x1, y2: r.risk_free_rate + ((ms.return - r.risk_free_rate) / ms.volatility) * x1 } : null;

  const marks: { key: keyof OptimizerResult["portfolios"]; label: string; color: string }[] = [
    { key: "max_sharpe", label: "MAX SHARPE", color: "var(--color-amber)" },
    { key: "target", label: "TARGET", color: "#c792ea" },
    { key: "min_variance", label: "MIN RISK", color: "var(--color-up)" },
    { key: "equal_weight", label: "EQUAL", color: "var(--color-ink)" },
    { key: "current", label: "YOURS", color: "var(--color-down)" },
  ];

  const toLocal = (e: React.MouseEvent) => {
    const box = svgRef.current!.getBoundingClientRect();
    return { x: ((e.clientX - box.left) / box.width) * W, y: ((e.clientY - box.top) / box.height) * H };
  };
  const nearestFrontier = (x: number, y: number) => {
    let best: FrontierPoint | null = null, dist = Infinity;
    for (const f of r.frontier) {
      const d = Math.hypot(sx(f.volatility) - x, sy(f.return) - y);
      if (d < dist) { dist = d; best = f; }
    }
    return dist < 18 ? best : null;
  };

  const top = (w?: Record<string, number>) =>
    Object.entries(w ?? {}).filter(([, v]) => v > 0.0005).sort((a, b) => b[1] - a[1]).slice(0, 6);

  const idx = picked ? r.frontier.indexOf(picked) : -1;
  return (
    <div className="border-b border-line px-2 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 pb-1.5 text-[10px] tracking-widest text-dim">
        <label className="flex items-center gap-2" title="Slide along the frontier from the lowest-risk mix to the highest-return one; the PICKED column follows">
          RISK APPETITE
          <span className="text-up">LOW</span>
          <input type="range" min={0} max={Math.max(r.frontier.length - 1, 0)} step={1} value={idx >= 0 ? idx : 0}
                 aria-label="Risk appetite: position along the efficient frontier"
                 onChange={(e) => onPick(r.frontier[Number(e.target.value)] ?? null)}
                 className="w-40 accent-amber" />
          <span className="text-down">HIGH</span>
        </label>
        {picked && (
          <span className="normal-case tracking-normal tabular-nums">
            picked: return <span className="text-ink">{pct(picked.return, 1)}</span> · vol <span className="text-ink">{pct(picked.volatility, 1)}</span>
            {" "}· Sharpe <span className="text-amber">{num(picked.sharpe)}</span>
          </span>
        )}
        <ZoomHint zoomed={z.zoomed} reset={z.reset} />
      </div>
      <div className="relative">
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img"
           className={`h-auto w-full min-w-[420px] touch-none select-none ${z.busy ? "" : "chart-anim"}`}
           aria-label="Efficient frontier: annual return against volatility, shaded by Sharpe ratio"
           {...z.bind}
           onPointerMove={(e) => {
             z.bind.onPointerMove(e);
             const { x, y } = toLocal(e);
             const f = nearestFrontier(x, y);
             if (f) setHover({ x: sx(f.volatility), y: sy(f.return), title: "FRONTIER", color: heat(f.sharpe), p: f });
             else if (hover?.title === "FRONTIER") setHover(null);
           }}
           onPointerLeave={() => { z.bind.onPointerLeave(); setHover(null); }}
           onClick={(e) => {
             if (z.wasDrag()) return;                       // a pan is not a pick
             const { x, y } = toLocal(e); const f = nearestFrontier(x, y); onPick(f && f !== picked ? f : null);
           }}>
        <defs>
          <linearGradient id="sharpe-legend" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0" stopColor={heat(sMin)} /><stop offset="1" stopColor={heat(sMax)} />
          </linearGradient>
          <clipPath id="frontier-clip"><rect x={L} y={0} width={W - L - R} height={H - B + 4} /></clipPath>
        </defs>
        {ticks(y0, y1).map((v) => (
          <g key={`y${v}`}>
            <line x1={L} x2={W - R} y1={sy(v)} y2={sy(v)} stroke="var(--color-line)" strokeWidth="1" />
            <text x={L - 6} y={sy(v) + 3} textAnchor="end" fontSize="9" fill="var(--color-dim)">{(v * 100).toFixed(0)}%</text>
          </g>
        ))}
        {ticks(x0, x1).map((v) => (
          <text key={`x${v}`} x={sx(v)} y={H - B + 14} textAnchor="middle" fontSize="9" fill="var(--color-dim)">{(v * 100).toFixed(0)}%</text>
        ))}
        <text x={W - R} y={H - 4} textAnchor="end" fontSize="9" fill="var(--color-dim)">VOLATILITY (ANN.)</text>
        <text x={L} y={H - 4} fontSize="9" fill="var(--color-dim)">SHARPE</text>
        <rect x={L + 38} y={H - 11} width={60} height={6} fill="url(#sharpe-legend)" />
        <text x={L + 102} y={H - 4} fontSize="8" fill="var(--color-dim)">{num(sMin)}–{num(sMax)}</text>

        <g clipPath="url(#frontier-clip)">
        {cml && (
          <line className="tw" x1={sx(0)} y1={sy(r.risk_free_rate)} x2={sx(cml.x2)} y2={sy(cml.y2)}
                stroke="var(--color-amber)" strokeOpacity="0.5" strokeDasharray="4 3" strokeWidth="1" />
        )}
        <circle className="tw" cx={sx(0)} cy={sy(r.risk_free_rate)} r="2.5" fill="var(--color-amber)" opacity="0.7" />
        {r.frontier.slice(1).map((f, i) => {
          const a = r.frontier[i];
          return <line key={i} className="tw" x1={sx(a.volatility)} y1={sy(a.return)} x2={sx(f.volatility)} y2={sy(f.return)}
                       stroke={heat(((a.sharpe ?? 0) + (f.sharpe ?? 0)) / 2)} strokeWidth="2.5" strokeLinecap="round" />;
        })}
        {r.frontier.map((f, i) => (
          <circle key={`f${i}`} cx={sx(f.volatility)} cy={sy(f.return)} r={f === picked ? 5 : 2}
                  fill={f === picked ? "var(--color-cyan)" : heat(f.sharpe)} stroke="var(--color-bg)" strokeWidth={f === picked ? 1.5 : 0}
                  className="tw cursor-pointer" />
        ))}
        {r.assets.map((a) => (
          <g key={a.symbol} onMouseEnter={() => setHover({ x: sx(a.volatility), y: sy(a.return), title: ticker(a.symbol), color: "var(--color-dim)", p: a })}>
            <circle className="tw" cx={sx(a.volatility)} cy={sy(a.return)} r="3" fill="var(--color-dim)" />
            <text x={sx(a.volatility) + 4} y={sy(a.return) - 4} fontSize="9" fill="var(--color-dim)">{ticker(a.symbol)}</text>
          </g>
        ))}
        {marks.map((m) => {
          const p = r.portfolios[m.key];
          if (!p) return null;
          return (
            <g key={m.key} onMouseEnter={() => setHover({ x: sx(p.volatility), y: sy(p.return), title: m.label, color: m.color, p })}>
              <circle className="tw" cx={sx(p.volatility)} cy={sy(p.return)} r="5" fill={m.color} stroke="var(--color-bg)" strokeWidth="1.5" />
              <text x={sx(p.volatility) + 7} y={sy(p.return) + 3} fontSize="9" fontWeight="600" fill={m.color}>{m.label}</text>
            </g>
          );
        })}
        </g>
      </svg>
      {hover && (
        <div className="pointer-events-none absolute z-10 min-w-[150px] border border-line bg-bg/95 px-2 py-1.5 text-[10.5px] shadow-lg"
             style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / H) * 100}%`,
                      transform: `translate(${hover.x > W * 0.6 ? "calc(-100% - 10px)" : "10px"}, -50%)` }}>
          <div className="mb-0.5 font-semibold" style={{ color: hover.color }}>{hover.title}</div>
          <div className="tabular-nums">Return {pct(hover.p.return, 1)} · Vol {pct(hover.p.volatility, 1)}</div>
          <div className="tabular-nums">Sharpe <span className="text-amber">{num(hover.p.sharpe ??
            (hover.p.volatility > 0 ? (hover.p.return - r.risk_free_rate) / hover.p.volatility : null))}</span></div>
          {top(hover.p.weights).length > 0 && (
            <div className="mt-1 border-t border-line pt-1">
              {top(hover.p.weights).map(([s, w]) => (
                <div key={s} className="flex justify-between gap-3 tabular-nums"><span className="text-cyan">{ticker(s)}</span>{pct(w, 1)}</div>
              ))}
            </div>
          )}
          {hover.title === "FRONTIER" && <div className="mt-1 text-[9px] text-dim">click to compare in the table</div>}
        </div>
      )}
      </div>
    </div>
  );
}
