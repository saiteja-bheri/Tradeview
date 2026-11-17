import { useState } from "react";
import { num, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty, Seg } from "../ui";

type View = "matrix" | "annualized" | "correlation";

/** Holding period of each return, in trading days. */
const HORIZONS = [
  { value: 1, label: "1D" }, { value: 5, label: "1W" }, { value: 10, label: "2W" }, { value: 21, label: "1M" },
  { value: 63, label: "3M" }, { value: 126, label: "6M" }, { value: 252, label: "1Y" },
];
/** How much history the matrix is estimated from (0 = the RISK tab's lookback). */
const WINDOWS = [
  { value: 0, label: "= RISK" }, { value: 252, label: "1Y" }, { value: 504, label: "2Y" }, { value: 756, label: "3Y" },
  { value: 1260, label: "5Y" }, { value: 2520, label: "10Y" },
];
/** A sensible data window for each horizon: enough for ~10 independent periods. */
const SUGGESTED: Record<number, number> = { 21: 252, 63: 756, 126: 1260, 252: 2520 };

function horizonLabel(h: number): string {
  return HORIZONS.find((x) => x.value === h)?.label ?? `${h}D`;
}
const VIEWS: { value: View; label: string }[] = [
  { value: "matrix", label: "PERIOD" },
  { value: "annualized", label: "ANNUAL" },
  { value: "correlation", label: "CORR" },
];

export function CovariancePane() {
  const cov = useStore((s) => s.portfolio?.covariance);
  const horizon = useStore((s) => s.portfolio?.params.cov_horizon_days);
  const window_ = useStore((s) => s.portfolio?.params.cov_lookback_days ?? 0);
  const riskLookback = useStore((s) => s.portfolio?.params.lookback_days ?? 252);
  const setParam = useStore((s) => s.setParam);
  const [view, setView] = useState<View>("matrix");

  // A long horizon on a short window has few independent periods: widen the
  // window with it unless you already chose a longer one.
  const pickHorizon = (h: number) => {
    const effective = window_ || riskLookback;
    const want = SUGGESTED[h];
    setParam(want && effective < want ? { cov_horizon_days: h, cov_lookback_days: want } : { cov_horizon_days: h });
  };

  const controls = (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
      <Seg<number> label="HORIZON" value={horizon} options={HORIZONS} onChange={pickHorizon} />
      <Seg<number> label="DATA" value={window_} options={WINDOWS}
                   onChange={(v) => setParam({ cov_lookback_days: v })} />
      <Seg<View> label="SHOW" value={view} options={VIEWS} onChange={setView} />
    </div>
  );

  if (!cov) {
    return (
      <div className="flex h-full flex-col p-3">
        {controls}
        <Empty title="Covariance matrix unavailable"
               hint="Needs at least 30 overlapping returns at this horizon. Pick a longer DATA window (up to 10Y) or a shorter horizon." />
      </div>
    );
  }

  const data = cov[view];
  const h = cov.horizon_days;
  const unit = h === 1 ? "DAILY" : `${horizonLabel(h)} (${h}-DAY)`;
  const title =
    view === "matrix" ? `COVARIANCE OF ${unit} RETURNS`
    : view === "annualized" ? `COVARIANCE OF ${unit} RETURNS, ANNUALIZED`
    : `CORRELATION OF ${unit} RETURNS`;
  const flat = data.flat().filter((v): v is number => v != null);
  const max = view === "correlation" ? 1 : Math.max(...flat.map(Math.abs), 1e-12);
  const digits = view === "matrix" ? 6 : view === "annualized" ? 4 : 2;

  return (
    <div className="p-3">
      {controls}
      <div className="mb-2 text-[10px] tracking-widest text-dim">
        {title} · {cov.observations} {h > 1 ? "OVERLAPPING " : ""}OBSERVATIONS
        {cov.from && <> · {cov.from} TO {cov.to}</>}
        {h > 1 && cov.independent_periods != null && (
          <span className={cov.independent_periods < 10 ? "text-amber" : ""}
                title="Overlapping windows reuse the same days; this is how many separate periods the data really holds">
            {" "}· ~{cov.independent_periods} INDEPENDENT
          </span>
        )}
      </div>
      <table className="grid-table w-auto">
        <thead>
          <tr>
            <th className="l" />
            {cov.symbols.map((s) => <th key={s} className="r">{ticker(s)}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={cov.symbols[i]}>
              <td className="l text-cyan">{ticker(cov.symbols[i])}</td>
              {row.map((v, j) => (
                <td key={j} className="r"
                    style={{
                      background: v == null ? undefined
                        : `rgb(${v < 0 ? "64 156 255" : "255 176 0"} / ${(Math.abs(v) / max) * 0.45})`,
                    }}>
                  {num(v, digits)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
