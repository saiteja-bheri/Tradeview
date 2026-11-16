import { useState } from "react";
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

  const run = async (s = shock, h = horizon) => {
    setBusy(true);
    setError(null);
    try {
      setR(await api.stress({ shock_pct: s, horizon_days: h, history }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const hz = HORIZONS.find((x) => x.value === (r?.horizon_days ?? horizon))?.label ?? `${r?.horizon_days}D`;

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-3 py-2">
        <Seg<number> label="MARKET MOVE" value={shock} options={SHOCKS} onChange={(v) => { setShock(v); if (r) run(v); }} />
        <label className="flex items-center gap-1 text-[10px] tracking-widest text-dim">
          OR
          <input type="number" min={-90} max={100} step={1} value={shock} aria-label="Custom market move, percent (negative = fall)"
                 onChange={(e) => setShock(Number(e.target.value))}
                 className="w-14 border border-line bg-bg px-1 py-0.5 text-right text-ink outline-none focus:border-amber" />%
        </label>
        <Seg<number> label="OVER" value={horizon} options={HORIZONS} onChange={(v) => { setHorizon(v); if (r) run(shock, v); }} />
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

/** Distribution of simulated P&L; losses red, gains green, with the 1-in-20 and 1-in-100 marks. */
function Histogram({ r }: { r: StressResult }) {
  const { edges, counts } = r.monte_carlo.histogram;
  const W = 520, H = 130, L = 8, R = 8, T = 8, B = 22;
  const lo = edges[0], hi = edges[edges.length - 1], max = Math.max(...counts, 1);
  const sx = (v: number) => L + ((v - lo) / (hi - lo || 1)) * (W - L - R);
  const bw = (W - L - R) / counts.length;
  const marks = [
    { v: r.monte_carlo.percentiles.p1, label: "1/100" },
    { v: r.monte_carlo.percentiles.p5, label: "1/20" },
    { v: 0, label: "0" },
    { v: r.monte_carlo.percentiles.p95, label: "1/20" },
    { v: r.monte_carlo.percentiles.p99, label: "1/100" },
  ];
  return (
    <div className="px-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[360px]" role="img"
           aria-label="Histogram of simulated portfolio profit and loss">
        {counts.map((c, i) => {
          const mid = (edges[i] + edges[i + 1]) / 2;
          const h = (c / max) * (H - T - B);
          return <rect key={i} x={L + i * bw + 0.5} y={H - B - h} width={Math.max(bw - 1, 1)} height={h}
                       fill={mid < 0 ? "var(--color-down)" : "var(--color-up)"} opacity={0.75} />;
        })}
        {marks.filter((m) => m.v >= lo && m.v <= hi).map((m) => (
          <g key={`${m.label}${m.v}`}>
            <line x1={sx(m.v)} x2={sx(m.v)} y1={T} y2={H - B} stroke="var(--color-ink)" strokeDasharray="3 3" strokeWidth="1" />
            <text x={sx(m.v) + 3} y={T + 9} fontSize="9" fill="var(--color-ink)">{m.label}</text>
          </g>
        ))}
        <text x={L} y={H - 6} fontSize="9" fill="var(--color-dim)">{signed(lo)}</text>
        <text x={W - R} y={H - 6} fontSize="9" textAnchor="end" fill="var(--color-dim)">{signed(hi)}</text>
      </svg>
    </div>
  );
}
