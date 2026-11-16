import { useState } from "react";
import { api } from "../api/client";
import type { OptimizerResult, OptPortfolio } from "../api/types";
import { num, pct, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty, Seg } from "../ui";

const LOOKBACKS = [{ value: 252, label: "1Y" }, { value: 504, label: "2Y" }, { value: 756, label: "3Y" }];
const CAPS = [{ value: 0.2, label: "20%" }, { value: 0.35, label: "35%" }, { value: 0.5, label: "50%" }, { value: 1, label: "NONE" }];
const COLS: { key: keyof OptimizerResult["portfolios"]; label: string; title: string }[] = [
  { key: "max_sharpe", label: "MAX SHARPE", title: "Best return per unit of risk (uses historical returns)" },
  { key: "min_variance", label: "MIN RISK", title: "Lowest volatility; ignores expected returns" },
  { key: "equal_weight", label: "EQUAL", title: "Same weight in every stock, for reference" },
  { key: "current", label: "YOURS", title: "Your current mix of these stocks" },
];

const SCOPES = [{ value: "portfolio", label: "PORTFOLIO" }, { value: "starred", label: "★ STARRED" },
                { value: "both", label: "BOTH" }] as const;
type Scope = (typeof SCOPES)[number]["value"];

/** Mean-variance (Markowitz) optimisation of the whole portfolio by default,
 *  or of the starred (★) stocks, or both. */
export function OptimizerPane() {
  const starred = useStore((s) => s.watch.filter((w) => w.starred).length);
  const [lookback, setLookback] = useState(504);
  const [cap, setCap] = useState(0.35);
  const [scope, setScope] = useState<Scope>("portfolio");
  const held = useStore((s) => (s.portfolio?.holdings ?? []).filter((h) => !h.symbol.startsWith("BOND:")).length);
  const count = scope === "portfolio" ? held : scope === "starred" ? starred : held + starred;
  const [result, setResult] = useState<OptimizerResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await api.optimize({ scope, lookback_days: lookback, max_weight: cap }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cols = COLS.filter((c) => result?.portfolios[c.key]);

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
        <Seg<number> label="HISTORY" value={lookback} options={LOOKBACKS} onChange={setLookback} />
        <Seg<number> label="MAX PER STOCK" value={cap} options={CAPS} onChange={setCap} />
        <Seg<Scope> label="OPTIMISE" value={scope} options={[...SCOPES]} onChange={(v) => { setScope(v); setResult(null); }} />
        <button onClick={run} disabled={busy || count < 2}
                className="ml-auto border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-amber">
          {busy ? "OPTIMISING…" : `RUN · ${count} ${count === 1 ? "STOCK" : "STOCKS"}`}
        </button>
      </div>

      {error && <div role="alert" className="px-3 py-2 text-down">{error}</div>}

      {!result ? (
        <Empty title={count >= 2 ? (scope === "portfolio" ? "Optimise your whole portfolio" : "Ready to optimise")
                       : scope === "starred" ? "Star at least two stocks" : "Hold at least two stocks"}
               hint="By default the whole portfolio is optimised. Switch to ★ STARRED for stocks you are considering, or BOTH. Uses cached daily prices in rupees to find the best return for its risk (max Sharpe) and the lowest-risk mix, compared with your current weights." />
      ) : (
        <>
          <Frontier r={result} />
          <div className="overflow-x-auto">
            <table className="grid-table">
              <thead>
                <tr>
                  <th className="l">Stock</th>
                  <th className="r" title="Annualised historical return">Ret</th>
                  <th className="r" title="Annualised volatility">Vol</th>
                  {cols.map((c) => <th key={c.key} className="r" title={c.title}>{c.label}</th>)}
                </tr>
              </thead>
              <tbody>
                {result.assets.map((a) => (
                  <tr key={a.symbol}>
                    <td className="l" title={a.name || undefined}>
                      <span className="text-cyan">{ticker(a.symbol)}</span>
                      {a.held && <span className="ml-1 text-[9px] tracking-widest text-up">HELD</span>}
                    </td>
                    <td className="r text-dim">{pct(a.return, 1)}</td>
                    <td className="r text-dim">{pct(a.volatility, 1)}</td>
                    {cols.map((c) => {
                      const w = result.portfolios[c.key]?.weights[a.symbol] ?? 0;
                      return (
                        <td key={c.key} className={`r tabular-nums ${w > 0.0005 ? (c.key === "max_sharpe" ? "text-amber" : "text-ink") : "text-dim/50"}`}>
                          {w > 0.0005 ? pct(w, 1) : "·"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                {(["return", "volatility", "sharpe"] as const).map((k) => (
                  <tr key={k} className="border-t border-line">
                    <td className="l text-[10px] tracking-widest text-dim" colSpan={3}>
                      {k === "return" ? "EXPECTED RETURN" : k === "volatility" ? "VOLATILITY" : "SHARPE"}
                    </td>
                    {cols.map((c) => {
                      const p = result.portfolios[c.key] as OptPortfolio;
                      return <td key={c.key} className="r tabular-nums">{k === "sharpe" ? num(p[k]) : pct(p[k], 1)}</td>;
                    })}
                  </tr>
                ))}
              </tfoot>
            </table>
          </div>
          <div className="border-t border-line px-3 py-2 text-[10px] leading-relaxed text-dim">
            {result.observations} daily returns in INR, {result.from} to {result.to} · risk-free {pct(result.risk_free_rate, 1)} ·
            covariance shrunk {pct(result.shrinkage, 0)} toward average (Ledoit-Wolf) · long-only, at most {pct(result.max_weight, 0)} per stock.
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

/** Efficient frontier with each stock and each portfolio, risk on x, return on y. */
function Frontier({ r }: { r: OptimizerResult }) {
  const W = 520, H = 220, L = 46, R = 12, T = 12, B = 30;
  const pts = [
    ...r.frontier.map((f) => [f.volatility, f.return]),
    ...r.assets.map((a) => [a.volatility, a.return]),
    ...Object.values(r.portfolios).filter(Boolean).map((p) => [p!.volatility, p!.return]),
  ];
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = 0, x1 = Math.max(...xs) * 1.08 || 0.1;
  const yPad = (Math.max(...ys) - Math.min(...ys)) * 0.1 || 0.02;
  const y0 = Math.min(0, Math.min(...ys) - yPad), y1 = Math.max(...ys) + yPad;
  const sx = (v: number) => L + ((v - x0) / (x1 - x0)) * (W - L - R);
  const sy = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const ticks = (a: number, b: number) => Array.from({ length: 5 }, (_, i) => a + ((b - a) * i) / 4);
  const line = r.frontier.map((f, i) => `${i ? "L" : "M"}${sx(f.volatility).toFixed(1)},${sy(f.return).toFixed(1)}`).join(" ");
  const marks: { key: string; label: string; color: string }[] = [
    { key: "max_sharpe", label: "MAX SHARPE", color: "var(--color-amber)" },
    { key: "min_variance", label: "MIN RISK", color: "var(--color-up)" },
    { key: "current", label: "YOURS", color: "var(--color-down)" },
  ];
  return (
    <div className="overflow-x-auto border-b border-line px-2 py-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[420px]" role="img"
           aria-label="Efficient frontier: annual return against volatility">
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
        <path d={line} fill="none" stroke="var(--color-cyan)" strokeWidth="1.75" />
        {r.assets.map((a) => (
          <g key={a.symbol}>
            <circle cx={sx(a.volatility)} cy={sy(a.return)} r="2.5" fill="var(--color-dim)" />
            <text x={sx(a.volatility) + 4} y={sy(a.return) - 4} fontSize="9" fill="var(--color-dim)">{ticker(a.symbol)}</text>
          </g>
        ))}
        {marks.map((m) => {
          const p = r.portfolios[m.key as keyof OptimizerResult["portfolios"]];
          if (!p) return null;
          return (
            <g key={m.key}>
              <circle cx={sx(p.volatility)} cy={sy(p.return)} r="4.5" fill={m.color} stroke="var(--color-bg)" strokeWidth="1.5" />
              <text x={sx(p.volatility) + 7} y={sy(p.return) + 3} fontSize="9" fontWeight="600" fill={m.color}>{m.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
