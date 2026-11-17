import { useEffect, useMemo, useRef, useState } from "react";
import { ChartTip, ZoomHint, plotFrac, useZoomPan } from "../chartKit";
import { api } from "../api/client";
import type { ProjectionPoint, ProjectionResult } from "../api/types";
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

type Freq = "daily" | "weekly" | "monthly" | "bimonthly" | "quarterly" | "halfyearly" | "yearly";
/** How often the SIP is paid, instalments a year, and the word for one period. */
const FREQS: { value: Freq; label: string; per: number; unit: string }[] = [
  { value: "daily", label: "DAILY", per: 250, unit: "DAY" },
  { value: "weekly", label: "WEEKLY", per: 52, unit: "WEEK" },
  { value: "monthly", label: "MONTHLY", per: 12, unit: "MONTH" },
  { value: "bimonthly", label: "BI-MONTHLY", per: 6, unit: "2 MONTHS" },
  { value: "quarterly", label: "QUARTERLY", per: 4, unit: "QUARTER" },
  { value: "halfyearly", label: "HALF-YEARLY", per: 2, unit: "HALF-YEAR" },
  { value: "yearly", label: "ANNUALLY", per: 1, unit: "YEAR" },
];
const freqOf = (f: Freq) => FREQS.find((x) => x.value === f) ?? FREQS[2];
/** A tidy amount: to the nearest ₹1 below ₹100, ₹10 below ₹10,000, else ₹100. */
const tidy = (v: number) => (v < 100 ? Math.round(v) : v < 10_000 ? Math.round(v / 10) * 10 : Math.round(v / 100) * 100);
const SIP_KEY = "qt.plan.sip";

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
  const [sipPlan, setSipPlan] = useState<{ amount: number; freq: Freq }>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(SIP_KEY) ?? "null");
      return v && typeof v.amount === "number" && FREQS.some((f) => f.value === v.freq) ? v : { amount: 10000, freq: "monthly" };
    } catch {
      return { amount: 10000, freq: "monthly" };
    }
  });
  const { amount: sip, freq } = sipPlan;
  const fq = freqOf(freq);
  // Switching how often you pay keeps the money per year the same: ₹10,000 a month
  // becomes ₹30,000 a quarter or about ₹480 a market day.
  const changeFreq = (next: Freq) => {
    const per = freqOf(next).per;
    setSipPlan({ freq: next, amount: tidy((sip * fq.per) / per) });
  };
  useEffect(() => {
    try { localStorage.setItem(SIP_KEY, JSON.stringify(sipPlan)); } catch { /* optional */ }
  }, [sipPlan]);
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
      api.projection({ mode, monthly_sip: (sip * fq.per) / 12, sip_amount: sip, sip_frequency: freq, step_up_pct: stepUp, years, interval, outlook, include_wealth: withWealth,
                       tax_gains_pct: tax.gains, gains_exemption: tax.exempt, tax_interest_pct: tax.interest,
                       renew_deposits: tax.renew })
        .then((res) => { if (mine === seq.current) { setR(res); setError(null); } })
        .catch((e) => { if (mine === seq.current) setError((e as Error).message); });
    }, 250);
    return () => clearTimeout(t);
  }, [mode, sip, freq, stepUp, years, interval, outlook, withWealth, tax]);

  const a = r?.assumptions, s = r?.summary;
  const hasOther = (r?.points[r.points.length - 1]?.other ?? 0) > 0;

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="space-y-2 border-b border-line px-3 py-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Seg<Mode> label="PLAN" value={mode} onChange={setMode}
                     options={[{ value: "continue", label: "CONTINUE MY PORTFOLIO + SIP" }, { value: "fresh", label: "START A NEW SIP" }]} />
          <Seg<Freq> label="PAID" value={freq} options={FREQS} onChange={changeFreq} />
          <label className="flex items-center gap-1.5 text-[10px] tracking-widest text-dim"
                 title={`Amount paid every ${fq.unit.toLowerCase()}${freq === "daily" ? " (market days, about 250 a year)" : ""}`}>
            SIP ₹ / {fq.unit}
            <input type="number" min={0} step={freq === "daily" ? 10 : freq === "weekly" ? 100 : 500} value={sip}
                   onChange={(e) => setSipPlan({ freq, amount: Math.max(0, Number(e.target.value)) })}
                   aria-label={`SIP amount per ${fq.unit.toLowerCase()} in rupees`}
                   className="w-24 border border-line bg-bg px-1.5 py-0.5 text-right text-ink outline-none focus:border-amber" />
          </label>
          <span className="text-[10px] text-dim tabular-nums" title="The same money expressed per month and per year (first year)">
            = {inr((sip * fq.per) / 12)} / month · {inr(sip * fq.per)} / year{freq === "daily" ? " (250 market days)" : ""}
          </span>
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
          <Seg<Interval> label="SHOW EVERY" value={interval} options={INTERVALS} onChange={setInterval} />
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
              ? `Uses your portfolio's own past growth of ${pct(a.past_compound_return ?? a.expected_return, 1)} a year (compound) and volatility of ${pct(a.volatility, 1)}; the likely path grows at that rate, which means an average (expected) return of ${pct(a.expected_return, 1)}.`
              : `${a.source[0].toUpperCase()}${a.source.slice(1)} outlook: expected ${pct(a.expected_return, 1)} a year for your mix
                 (${Object.entries(a.per_class ?? {}).map(([k, v]) => `${k} ${num(v.expected_return * 100, 1)}%`).join(", ")}),
                 volatility ${pct(a.volatility, 1)} from ${a.volatility_source}.`}{" "}
            {mode === "fresh" ? "A new SIP is assumed to be invested in the same mix as your portfolio (all equity if you hold none). " : ""}
            The SIP ({inr(sip)} {fq.label.toLowerCase()}{freq === "daily" ? ", on market days" : ""}) is invested on its date and earns
            returns from then on; {a.simulations.toLocaleString("en-IN")} simulated paths give
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

/** The projection over time: likely path, bad-to-good band, after-tax value and
 *  money put in. Hover for the figures at any date, scroll to zoom, drag to
 *  pan, click a legend item to show or hide it, and set a goal to see when the
 *  likely and bad cases reach it. */
function FanChart({ r }: { r: ProjectionResult }) {
  const pts = r.points;
  const W = 640, H = 240, L = 72, R = 14, T = 12, B = 26;
  const P = useMemo(() => ({ W, L, R }), []);
  const svgRef = useRef<SVGSVGElement>(null);
  const lastM = pts[pts.length - 1].month || 1;
  const full = useMemo<[number, number]>(() => [0, lastM], [lastM]);
  const z = useZoomPan(svgRef, full, P, Math.max(1, lastM / 40));
  const hasOther = pts[pts.length - 1].other > 0;
  const [show, setShow] = useState({ band: true, likely: true, after: true, putin: true, other: true });
  const [log, setLog] = useState(false);
  const [goal, setGoal] = useState<number>(() => {
    try { return Number(localStorage.getItem("qt.plan.goal")) || 0; } catch { return 0; }
  });
  const [hover, setHover] = useState<number | null>(null);   // index into pts

  const off = (p: ProjectionPoint) => (hasOther && show.other ? p.other : 0);
  const series: { key: keyof typeof show; label: string; color: string; get: (p: ProjectionPoint) => number; dash?: string }[] = [
    { key: "likely", label: "likely", color: "var(--color-cyan)", get: (p) => p.p50 + off(p) },
    { key: "after", label: "likely after tax", color: "var(--color-amber)", get: (p) => p.p50_after_tax + off(p), dash: "5 3" },
    { key: "putin", label: "put in", color: "var(--color-dim)", get: (p) => p.invested + (hasOther && show.other ? p.other_invested : 0), dash: "4 3" },
    ...(hasOther ? [{ key: "other" as const, label: "deposits, pension, insurance", color: "#e07bd0", get: (p: ProjectionPoint) => p.other, dash: "2 3" }] : []),
  ];

  const [a, b] = z.dom;
  const visible = pts.filter((p) => p.month >= a - 1e-9 && p.month <= b + 1e-9);
  const inView = visible.length >= 2 ? visible : pts;
  const vals = inView.flatMap((p) => [
    ...(show.band ? [p.p10 + off(p), p.p90 + off(p)] : []),
    ...series.filter((s) => show[s.key]).map((s) => s.get(p)),
    ...(goal > 0 ? [goal] : []),
  ]).filter((v) => v > 0);
  const vMax = Math.max(...vals, 1) * 1.05;
  const vMin = log ? Math.max(Math.min(...vals) * 0.9, 1) : 0;
  const sx = (m: number) => L + ((m - a) / (b - a || 1)) * (W - L - R);
  const sy = (v: number) => {
    const t = log ? (Math.log(Math.max(v, vMin)) - Math.log(vMin)) / (Math.log(vMax) - Math.log(vMin) || 1)
                  : (v - vMin) / (vMax - vMin || 1);
    return T + (1 - t) * (H - T - B);
  };
  const path = (f: (p: ProjectionPoint) => number) =>
    pts.map((p, i) => `${i ? "L" : "M"}${sx(p.month).toFixed(1)},${sy(f(p)).toFixed(1)}`).join(" ");
  const band = `${path((p) => p.p90 + off(p))} ${[...pts].reverse().map((p) => `L${sx(p.month).toFixed(1)},${sy(p.p10 + off(p)).toFixed(1)}`).join(" ")} Z`;
  const ticks = log
    ? Array.from({ length: 5 }, (_, i) => Math.exp(Math.log(vMin) + ((Math.log(vMax) - Math.log(vMin)) * i) / 4))
    : Array.from({ length: 5 }, (_, i) => vMin + ((vMax - vMin) * i) / 4);
  const span = b - a;
  const stepM = span > 120 ? 24 : span > 60 ? 12 : span > 24 ? 6 : span > 12 ? 3 : 1;
  const xTicks = Array.from({ length: Math.floor(lastM / stepM) + 1 }, (_, i) => i * stepM).filter((m) => m >= a && m <= b);
  const label = (m: number) => (m === 0 ? "now" : m % 12 === 0 ? `${m / 12}y` : `${Math.floor(m / 12)}y${m % 12}m`);

  // When the likely and the bad case first reach the goal.
  const reach = (f: (p: ProjectionPoint) => number) => pts.find((p) => f(p) >= goal);
  const likelyHit = goal > 0 ? reach((p) => p.p50 + off(p)) : undefined;
  const badHit = goal > 0 ? reach((p) => p.p10 + off(p)) : undefined;

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    z.bind.onPointerMove(e);
    const f = plotFrac(svgRef.current, e.clientX, P);
    const m = a + f * (b - a);
    let best = 0;
    pts.forEach((p, i) => { if (Math.abs(p.month - m) < Math.abs(pts[best].month - m)) best = i; });
    setHover(best);
  };
  const hp = hover != null ? pts[hover] : null;
  const toggle = (k: keyof typeof show) => setShow((s) => ({ ...s, [k]: !s[k] }));

  return (
    <div className="border-b border-line px-2 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-1 pb-1.5 text-[10px] tracking-widest text-dim">
        <Seg<"lin" | "log"> label="SCALE" value={log ? "log" : "lin"} hideLabel
                            options={[{ value: "lin", label: "LINEAR" }, { value: "log", label: "LOG" }]}
                            onChange={(v) => setLog(v === "log")} />
        <label className="flex items-center gap-1" title="A target amount: the chart marks when the likely and the bad case reach it">
          GOAL ₹
          <input type="number" min={0} step={100000} value={goal || ""} placeholder="none" aria-label="Goal amount in rupees"
                 onChange={(e) => { const v = Math.max(0, Number(e.target.value) || 0); setGoal(v);
                                    try { localStorage.setItem("qt.plan.goal", String(v)); } catch { /* optional */ } }}
                 className="w-28 border border-line bg-bg px-1 py-0.5 text-right text-ink outline-none focus:border-amber" />
        </label>
        {goal > 0 && (
          <span className="normal-case tracking-normal">
            likely by <span className="text-cyan">{likelyHit ? label(likelyHit.month) : "—"}</span> ·
            bad case by <span className="text-down">{badHit ? label(badHit.month) : "not within the plan"}</span>
          </span>
        )}
        <ZoomHint zoomed={z.zoomed} reset={z.reset} />
      </div>
      <div className="relative overflow-x-auto">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img"
             className={`h-auto w-full min-w-[420px] cursor-crosshair touch-none select-none ${z.busy ? "" : "chart-anim"}`}
             aria-label="Projected value over time: likely path, bad-to-good range, after-tax value and amount invested"
             {...z.bind} onPointerMove={onMove} onPointerLeave={() => { z.bind.onPointerLeave(); setHover(null); }}>
          <defs><clipPath id="fan-clip"><rect x={L} y={0} width={W - L - R} height={H} /></clipPath></defs>
          {ticks.map((v, i) => (
            <g key={i}>
              <line x1={L} x2={W - R} y1={sy(v)} y2={sy(v)} stroke="var(--color-line)" strokeWidth="1" />
              <text x={L - 6} y={sy(v) + 3} textAnchor="end" fontSize="9" fill="var(--color-dim)">{inr(v)}</text>
            </g>
          ))}
          {xTicks.map((m) => (
            <text key={m} x={sx(m)} y={H - 8} textAnchor="middle" fontSize="9" fill="var(--color-dim)">{label(m)}</text>
          ))}
          <g clipPath="url(#fan-clip)">
            {show.band && <path className="tw" d={band} fill="var(--color-cyan)" opacity="0.15" />}
            {series.filter((s) => show[s.key]).map((s) => (
              <path key={s.key} className="tw" d={path(s.get)} fill="none" stroke={s.color}
                    strokeWidth={s.key === "likely" ? 2 : 1.3} strokeDasharray={s.dash} />
            ))}
            {goal > 0 && (
              <g>
                <line x1={L} x2={W - R} y1={sy(goal)} y2={sy(goal)} stroke="#c792ea" strokeDasharray="6 3" />
                <text x={W - R - 4} y={sy(goal) - 4} textAnchor="end" fontSize="9" fill="#c792ea">GOAL {inr(goal)}</text>
                {likelyHit && <circle className="tw" cx={sx(likelyHit.month)} cy={sy(goal)} r={4} fill="var(--color-cyan)" />}
                {badHit && <circle className="tw" cx={sx(badHit.month)} cy={sy(goal)} r={4} fill="var(--color-down)" />}
              </g>
            )}
            {hp && (
              <g>
                <line x1={sx(hp.month)} x2={sx(hp.month)} y1={T} y2={H - B} stroke="var(--color-dim)" strokeDasharray="2 2" />
                {show.band && <circle cx={sx(hp.month)} cy={sy(hp.p90 + off(hp))} r={3} fill="var(--color-up)" />}
                {show.band && <circle cx={sx(hp.month)} cy={sy(hp.p10 + off(hp))} r={3} fill="var(--color-down)" />}
                {series.filter((s) => show[s.key]).map((s) => (
                  <circle key={s.key} cx={sx(hp.month)} cy={sy(s.get(hp))} r={3} fill={s.color} />
                ))}
              </g>
            )}
          </g>
        </svg>
        {hp && (
          <ChartTip x={sx(hp.month)} y={sy(hp.p50 + off(hp))} W={W} H={H}>
            <div className="mb-0.5 text-dim">{hp.month === 0 ? "Today" : `${hp.date.slice(0, 7)} · ${label(hp.month)}`}</div>
            <div className="grid grid-cols-[auto_auto] gap-x-3 tabular-nums">
              <span className="text-up">Good case</span><span className="text-right">{inr(hp.p90 + off(hp))}</span>
              <span className="text-cyan">Likely</span><span className="text-right">{inr(hp.p50 + off(hp))}</span>
              <span className="text-amber">After tax</span><span className="text-right">{inr(hp.p50_after_tax + off(hp))}</span>
              <span className="text-down">Bad case</span><span className="text-right">{inr(hp.p10 + off(hp))}</span>
              <span className="text-dim">Put in</span><span className="text-right">{inr(hp.invested + (hasOther ? hp.other_invested : 0))}</span>
              {hasOther && <><span style={{ color: "#e07bd0" }}>Other assets</span><span className="text-right">{inr(hp.other)}</span></>}
            </div>
          </ChartTip>
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 pt-1 text-[10px]" role="group" aria-label="Lines shown">
        <button type="button" onClick={() => toggle("band")} aria-pressed={show.band}
                className={show.band ? "text-ink" : "text-dim/50 line-through"}>
          <i className="mr-1 inline-block h-2 w-3 align-middle opacity-30" style={{ background: "var(--color-cyan)" }} />bad to good (1 in 10)
        </button>
        {series.map((s) => (
          <button key={s.key} type="button" onClick={() => toggle(s.key)} aria-pressed={show[s.key]}
                  className={show[s.key] ? "text-ink" : "text-dim/50 line-through"}>
            <i className="mr-1 inline-block h-0.5 w-3 align-middle" style={{ background: s.color }} />{s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
