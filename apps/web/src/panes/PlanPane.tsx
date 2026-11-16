import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ProjectionResult } from "../api/types";
import { inr, num, pct } from "../format";
import { Empty, Seg } from "../ui";

type Mode = "continue" | "fresh";
type Outlook = "cautious" | "neutral" | "optimistic" | "past";
type Interval = "monthly" | "quarterly" | "yearly";

const OUTLOOKS: { value: Outlook; label: string }[] = [
  { value: "cautious", label: "CAUTIOUS" }, { value: "neutral", label: "NEUTRAL" },
  { value: "optimistic", label: "OPTIMISTIC" }, { value: "past", label: "PAST PERFORMANCE" },
];
const YEARS = [3, 5, 10, 15, 20, 25].map((y) => ({ value: y, label: `${y}Y` }));
const INTERVALS: { value: Interval; label: string }[] = [
  { value: "monthly", label: "MONTHLY" }, { value: "quarterly", label: "QUARTERLY" }, { value: "yearly", label: "YEARLY" },
];

const TAX_KEY = "qt.plan.tax";
type Tax = { gains: number; exempt: number; interest: number; renew: boolean };
// Indian equity long-term capital gains: 12.5% above ₹1.25 lakh a year. Interest tax is the user's own slab.
const TAX_DEFAULT: Tax = { gains: 12.5, exempt: 125000, interest: 0, renew: true };

function savedTax(): Tax {
  try {
    return { ...TAX_DEFAULT, ...JSON.parse(localStorage.getItem(TAX_KEY) ?? "{}") };
  } catch {
    return TAX_DEFAULT;
  }
}

/** What the portfolio could be worth with a SIP, at equal intervals, under a
 *  market outlook or the portfolio's own past performance, before and after tax. */
export function PlanPane() {
  const [tax, setTax] = useState<Tax>(savedTax);
  const [mode, setMode] = useState<Mode>("continue");
  const [sip, setSip] = useState(10000);
  const [stepUp, setStepUp] = useState(0);
  const [years, setYears] = useState(10);
  const [interval, setInterval] = useState<Interval>("yearly");
  const [outlook, setOutlook] = useState<Outlook>("neutral");
  const [withWealth, setWithWealth] = useState(true);
  const [r, setR] = useState<ProjectionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    try {
      localStorage.setItem(TAX_KEY, JSON.stringify(tax));   // your tax inputs are remembered on this computer
    } catch {
      /* optional */
    }
  }, [tax]);

  useEffect(() => {
    const mine = ++seq.current;
    const t = setTimeout(() => {
      api.projection({ mode, monthly_sip: sip, step_up_pct: stepUp, years, interval, outlook, include_wealth: withWealth,
                       tax_gains_pct: tax.gains, gains_exemption: tax.exempt, tax_interest_pct: tax.interest,
                       renew_deposits: tax.renew })
        .then((res) => { if (mine === seq.current) { setR(res); setError(null); } })
        .catch((e) => { if (mine === seq.current) setError((e as Error).message); });
    }, 250);
    return () => clearTimeout(t);
  }, [mode, sip, stepUp, years, interval, outlook, withWealth, tax]);

  const a = r?.assumptions, s = r?.summary;
  const hasOther = (r?.points[r.points.length - 1]?.other ?? 0) > 0;

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="space-y-2 border-b border-line px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Seg<Mode> label="PLAN" value={mode} onChange={setMode}
                     options={[{ value: "continue", label: "CONTINUE MY PORTFOLIO + SIP" }, { value: "fresh", label: "START A NEW SIP" }]} />
          <label className="flex items-center gap-1.5 text-[10px] tracking-widest text-dim">
            SIP / MONTH ₹
            <input type="number" min={0} step={500} value={sip} onChange={(e) => setSip(Math.max(0, Number(e.target.value)))}
                   aria-label="Monthly SIP in rupees"
                   className="w-24 border border-line bg-bg px-1.5 py-0.5 text-right text-ink outline-none focus:border-amber" />
          </label>
          <label className="flex items-center gap-1.5 text-[10px] tracking-widest text-dim"
                 title="Raise the SIP by this much every year (a step-up SIP)">
            STEP-UP %/YR
            <input type="number" min={0} max={50} step={1} value={stepUp} onChange={(e) => setStepUp(Math.max(0, Number(e.target.value)))}
                   aria-label="Yearly step-up in percent"
                   className="w-14 border border-line bg-bg px-1.5 py-0.5 text-right text-ink outline-none focus:border-amber" />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Seg<Outlook> label="OUTLOOK" value={outlook} options={OUTLOOKS} onChange={setOutlook} />
          <Seg<number> label="FOR" value={years} options={YEARS} onChange={setYears} />
          <Seg<Interval> label="EVERY" value={interval} options={INTERVALS} onChange={setInterval} />
          <label className="flex items-center gap-1.5 text-[10px] tracking-widest text-dim"
                 title="Grow deposits, PPF/EPF/NPS, pension and insurance values alongside, at their own rates">
            <input type="checkbox" checked={withWealth} onChange={(e) => setWithWealth(e.target.checked)} className="accent-amber" />
            INCLUDE DEPOSITS, PENSION, INSURANCE
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Num label="TAX ON GAINS %" value={tax.gains} max={50} step={0.5} width="w-14"
               title="Tax on market gains if sold. Indian equity long-term gains: 12.5%. Use your own rate for short-term gains or other assets."
               onChange={(v) => setTax({ ...tax, gains: v })} />
          <Num label="TAX-FREE GAIN ₹" value={tax.exempt} max={1e9} step={5000} width="w-24"
               title="Gain that is not taxed. ₹1.25 lakh a year for Indian equity long-term gains."
               onChange={(v) => setTax({ ...tax, exempt: v })} />
          <Num label="YOUR SLAB ON INTEREST %" value={tax.interest} max={50} step={1} width="w-14"
               title="Your income-tax slab (e.g. 5, 20 or 30). Taken out of FD, RD and savings interest as it is earned. PPF, EPF, NPS, pension and insurance are left untaxed."
               onChange={(v) => setTax({ ...tax, interest: v })} />
          <Seg<"renew" | "cash"> label="FD AT MATURITY" value={tax.renew ? "renew" : "cash"}
                                 options={[{ value: "renew", label: "RENEW" }, { value: "cash", label: "TO SAVINGS" }]}
                                 onChange={(v) => setTax({ ...tax, renew: v === "renew" })} />
        </div>
      </div>

      {error && <div role="alert" className="px-3 py-2 text-down">{error}</div>}
      {!r || !a || !s ? (
        <Empty title="Working out the projection…" />
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] border-b border-line">
            <Tile label={`LIKELY VALUE IN ${a.years}Y`} value={inr(s.median)} cls="text-amber" big />
            <Tile label="LIKELY, AFTER TAX IF SOLD" value={inr(s.median_after_tax)} cls="text-amber" big />
            <Tile label="YOU WILL HAVE PUT IN" value={inr(s.invested_total)} />
            <Tile label="BAD CASE (1 IN 10)" value={inr(s.bad_case)} cls="text-down" />
            <Tile label="GOOD CASE (1 IN 10)" value={inr(s.good_case)} cls="text-up" />
            <Tile label="RETURN ON THE LIKELY PATH" value={s.median_annual_return == null ? "—"
              : `${pct(s.median_annual_return, 1)} / yr · ${pct(s.median_annual_return_after_tax, 1)} after tax`} />
            <Tile label="TAX ON THE LIKELY GAIN" value={inr(s.tax_on_median)} cls="text-down" />
            <Tile label="CHANCE OF ENDING BELOW WHAT YOU PUT IN" value={pct(s.chance_below_invested, 1)} />
            {hasOther ? (
              <>
                <Tile label="DEPOSITS, PENSION, INSURANCE THEN" value={inr(s.other_assets)} />
                <Tile label="TOTAL WEALTH (LIKELY)" value={inr(s.total_median)} cls="text-amber" />
                <Tile label="TOTAL WEALTH, AFTER TAX" value={inr(s.total_median_after_tax)} cls="text-amber" />
              </>
            ) : (
              <>
                <Tile label="EXPECTED (AVERAGE) VALUE" value={inr(s.expected)} />
                <Tile label="SIP ADDS" value={inr(s.added_by_sip)} />
              </>
            )}
          </div>

          <FanChart r={r} />

          <div className="overflow-x-auto">
            <table className="grid-table">
              <thead>
                <tr>
                  <th className="l">When</th><th className="r">Put in</th><th className="r">Bad case</th>
                  <th className="r">Likely</th><th className="r" title="Likely value if sold then, after tax on the gain">After tax</th>
                  <th className="r">Good case</th>
                  {hasOther && <><th className="r">Other assets</th><th className="r">Total (likely)</th></>}
                </tr>
              </thead>
              <tbody>
                {r.points.map((p) => (
                  <tr key={p.month}>
                    <td className="l text-dim">{p.month === 0 ? "Today" : p.date.slice(0, 7)}</td>
                    <td className="r tabular-nums text-dim">{inr(p.invested)}</td>
                    <td className="r tabular-nums text-down">{inr(p.p10)}</td>
                    <td className="r tabular-nums">{inr(p.p50)}</td>
                    <td className="r tabular-nums text-dim">{inr(p.p50_after_tax)}</td>
                    <td className="r tabular-nums text-up">{inr(p.p90)}</td>
                    {hasOther && <><td className="r tabular-nums text-dim">{inr(p.other)}</td>
                      <td className="r tabular-nums text-amber">{inr(p.total_p50)}</td></>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="border-t border-line px-3 py-2 text-[10px] leading-relaxed text-dim">
            {a.source === "past"
              ? `Uses your portfolio's own past return of ${pct(a.expected_return, 1)} a year and volatility of ${pct(a.volatility, 1)}.`
              : `${a.source[0].toUpperCase()}${a.source.slice(1)} outlook: expected ${pct(a.expected_return, 1)} a year for your mix
                 (${Object.entries(a.per_class ?? {}).map(([k, v]) => `${k} ${num(v.expected_return * 100, 1)}%`).join(", ")}),
                 volatility ${pct(a.volatility, 1)} from ${a.volatility_source}.`}{" "}
            {mode === "fresh" ? "A new SIP is assumed to be invested in the same mix as your portfolio (all equity if you hold none). " : ""}
            Each month's SIP is invested, then that month's return applied; {a.simulations.toLocaleString("en-IN")} simulated paths give
            the likely (median) value and the 1-in-10 bad and good cases. Deposits, pension and insurance grow at their own rates.
            Tax: {num(a.tax_gains_pct, 1)}% on market gains above {inr(a.gains_exemption)} if sold (gain measured from what you
            actually paid{a.start_cost ? `, today ${inr(a.start_cost)}` : ""}, plus each SIP)
            {a.tax_interest_pct ? `; ${num(a.tax_interest_pct, 0)}% taken out of deposit and savings interest` : "; deposit interest untaxed (set your slab above)"};
            PPF, EPF, NPS, pension and insurance left untaxed. FDs and RDs {a.renew_deposits ? "are renewed at the same rate when they mature"
            : "move to savings at 3% when they mature"}. Brokerage and fees are not included. These are assumptions, not a forecast.
          </p>
          {r.warnings.length > 0 && (
            <ul className="border-t border-line px-3 py-2 text-[10.5px] text-amber">{r.warnings.map((w, i) => <li key={i}>⚠ {w}</li>)}</ul>
          )}
        </>
      )}
    </div>
  );
}

function Num({ label, value, onChange, max, step, width, title }: {
  label: string; value: number; onChange: (v: number) => void; max: number; step: number; width: string; title: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[10px] tracking-widest text-dim" title={title}>
      {label}
      <input type="number" min={0} max={max} step={step} value={value} aria-label={label}
             onChange={(e) => onChange(Math.min(max, Math.max(0, Number(e.target.value) || 0)))}
             className={`${width} border border-line bg-bg px-1.5 py-0.5 text-right text-ink outline-none focus:border-amber`} />
    </label>
  );
}

function Tile({ label, value, cls = "", big = false }: { label: string; value: string; cls?: string; big?: boolean }) {
  return (
    <div className="min-w-0 border-b border-r border-line px-3 py-2">
      <div className="break-words text-[9px] tracking-widest text-dim">{label}</div>
      <div className={`tabular-nums ${big ? "text-lg font-semibold" : ""} ${cls}`}>{value}</div>
    </div>
  );
}

/** Likely path with the bad-to-good band, and the amount put in. */
function FanChart({ r }: { r: ProjectionResult }) {
  const pts = r.points;
  const W = 620, H = 220, L = 70, R = 12, T = 12, B = 24;
  const hasOther = pts[pts.length - 1].other > 0;
  const top = (p: (typeof pts)[number]) => (hasOther ? p.total_p90 : p.p90);
  const maxV = Math.max(...pts.map(top), 1);
  const lastM = pts[pts.length - 1].month || 1;
  const sx = (m: number) => L + (m / lastM) * (W - L - R);
  const sy = (v: number) => T + (1 - v / maxV) * (H - T - B);
  const off = (p: (typeof pts)[number]) => (hasOther ? p.other : 0);
  const path = (f: (p: (typeof pts)[number]) => number) => pts.map((p, i) => `${i ? "L" : "M"}${sx(p.month).toFixed(1)},${sy(f(p)).toFixed(1)}`).join(" ");
  const band = `${path((p) => p.p90 + off(p))} ${[...pts].reverse().map((p) => `L${sx(p.month).toFixed(1)},${sy(p.p10 + off(p)).toFixed(1)}`).join(" ")} Z`;
  const ticks = Array.from({ length: 5 }, (_, i) => (maxV * i) / 4);
  const years = pts.filter((p) => p.month % 12 === 0);
  const yearStep = Math.ceil(years.length / 8);
  return (
    <div className="overflow-x-auto border-b border-line px-2 py-2">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full min-w-[420px]" role="img"
           aria-label="Projected value: likely path, bad-to-good range and amount invested">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={sy(v)} y2={sy(v)} stroke="var(--color-line)" strokeWidth="1" />
            <text x={L - 6} y={sy(v) + 3} textAnchor="end" fontSize="9" fill="var(--color-dim)">{inr(v)}</text>
          </g>
        ))}
        {years.filter((_, i) => i % yearStep === 0).map((p) => (
          <text key={p.month} x={sx(p.month)} y={H - 6} textAnchor="middle" fontSize="9" fill="var(--color-dim)">
            {p.month === 0 ? "now" : `${p.month / 12}y`}
          </text>
        ))}
        <path d={band} fill="var(--color-cyan)" opacity="0.15" />
        {hasOther && <path d={path((p) => p.other)} fill="none" stroke="#e07bd0" strokeWidth="1.2" strokeDasharray="2 3" />}
        <path d={path((p) => p.invested + (hasOther ? p.other_invested : 0))} fill="none" stroke="var(--color-dim)" strokeWidth="1.4" strokeDasharray="4 3" />
        <path d={path((p) => p.p50 + off(p))} fill="none" stroke="var(--color-cyan)" strokeWidth="2" />
      </svg>
      <div className="flex flex-wrap gap-x-4 px-1 text-[10px] text-dim">
        <span><i className="mr-1 inline-block h-0.5 w-3 align-middle" style={{ background: "var(--color-cyan)" }} />likely</span>
        <span><i className="mr-1 inline-block h-2 w-3 align-middle opacity-30" style={{ background: "var(--color-cyan)" }} />bad to good (1 in 10)</span>
        <span><i className="mr-1 inline-block h-0.5 w-3 align-middle" style={{ background: "var(--color-dim)" }} />put in</span>
        {hasOther && <span><i className="mr-1 inline-block h-0.5 w-3 align-middle" style={{ background: "#e07bd0" }} />deposits, pension, insurance</span>}
      </div>
    </div>
  );
}
