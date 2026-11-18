import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { FactorAnalysis, FactorFit, FactorLoading } from "../api/types";
import { num, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty, Seg } from "../ui";

type Window = 252 | 756 | 1260;
type Key = keyof FactorFit["loadings"];
const WINDOWS: { value: Window; label: string }[] = [{ value: 252, label: "1Y" }, { value: 756, label: "3Y" }, { value: 1260, label: "5Y" }];
const SIG = 2;   // |t| at or above this counts as a clear tilt (about 95% confidence)

const FACTORS: { key: Key; label: string; what: string }[] = [
  { key: "market", label: "Market", what: "Sensitivity to the whole Indian market (above the T-bill rate)" },
  { key: "size", label: "Size (SMB)", what: "Small companies minus big companies" },
  { key: "value", label: "Value (HML)", what: "Cheap on book value minus expensive" },
  { key: "momentum", label: "Momentum (WML)", what: "Last year's winners minus losers" },
];

function reading(key: Key, l: FactorLoading): string {
  const clear = Math.abs(l.t) >= SIG;
  if (key === "market") return l.coef > 1.1 ? "Moves more than the market" : l.coef < 0.9 ? "Moves less than the market" : "Moves with the market";
  if (!clear) return key === "size" ? "No clear size tilt" : key === "value" ? "No clear value or growth tilt" : "No clear momentum tilt";
  if (key === "size") return l.coef > 0 ? "Tilts to smaller companies" : "Tilts to larger companies";
  if (key === "value") return l.coef > 0 ? "Tilts to value stocks" : "Tilts to growth stocks";
  return l.coef > 0 ? "Leans to recent winners" : "Leans to recent losers";
}

const fmt = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v))}`;

function cell(key: Key, l: FactorLoading) {
  const clear = Math.abs(l.t) >= SIG;
  const tone = key === "market" ? "" : clear ? (l.coef > 0 ? "text-up" : "text-down") : "text-dim";
  return (
    <td key={key} className={`r ${tone}`} title={`t = ${num(l.t)}`}>{fmt(l.coef)}</td>
  );
}

/** Carhart four-factor analysis: how much of the portfolio's movement is explained
 *  by the market, size, value and momentum, and what is left over (alpha). */
export function FactorsPane() {
  const [window, setWindow] = useState<Window>(756);
  const [data, setData] = useState<FactorAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const ledgerKey = useStore((s) => s.portfolio?.holdings.map((h) => `${h.symbol}:${h.quantity}`).join(",") ?? "");
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const d = await api.factors(window);
      if (mine === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message);
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [window]);

  useEffect(() => { load(); }, [load, ledgerKey]);

  const head = (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
      <div className="text-[10.5px] tracking-widest text-dim">FOUR-FACTOR ANALYSIS · CARHART · INDIA</div>
      <Seg<Window> label="WINDOW" value={window} options={WINDOWS} onChange={setWindow} />
    </div>
  );

  if (error) return <div className="flex h-full flex-col">{head}<Empty title="Factor analysis unavailable" hint={error} /></div>;
  if (!data) return <div className="flex h-full flex-col">{head}<Empty title="Loading factor data…" hint="The first run downloads IIM Ahmedabad's factor file and longer price history." /></div>;

  const p = data.portfolio;
  return (
    <div className={`flex h-full flex-col ${loading ? "opacity-60" : ""}`}>
      {head}
      <div className="min-h-0 flex-1 overflow-auto">
        {!p ? (
          <Empty title="No holdings to analyse" hint={data.notes.slice(1).join(" ") || "Add Indian stocks or funds to your ledger."} />
        ) : (
          <>
            <div className="grid grid-cols-3 gap-px border-b border-line bg-line">
              <div className="bg-panel px-3 py-2">
                <div className="text-[10px] tracking-widest text-dim">ALPHA (ANNUAL)</div>
                <div className={`font-mono text-[16px] ${Math.abs(p.alpha.t) >= SIG ? (p.alpha.annual > 0 ? "text-up" : "text-down") : ""}`}>
                  {fmt(p.alpha.annual * 100)}%
                </div>
                <div className="text-[10.5px] text-dim">
                  t = {num(p.alpha.t)} · {Math.abs(p.alpha.t) >= SIG ? "clearly different from zero" : "not distinguishable from zero"}
                </div>
              </div>
              <div className="bg-panel px-3 py-2">
                <div className="text-[10px] tracking-widest text-dim">EXPLAINED (R²)</div>
                <div className="font-mono text-[16px]">{num(p.r2 * 100, 0)}%</div>
                <div className="text-[10.5px] text-dim">of daily moves explained by the four factors</div>
              </div>
              <div className="bg-panel px-3 py-2">
                <div className="text-[10px] tracking-widest text-dim">PERIOD</div>
                <div className="font-mono text-[13px]">{data.data_from} → {data.data_to}</div>
                <div className="text-[10.5px] text-dim">{data.observations} trading days · today's weights</div>
              </div>
            </div>

            <table className="grid-table">
              <thead>
                <tr><th className="l">Factor</th><th className="r">Loading</th><th className="r">t</th><th className="l">Reading</th></tr>
              </thead>
              <tbody>
                {FACTORS.map((f) => {
                  const l = p.loadings[f.key];
                  return (
                    <tr key={f.key}>
                      <td className="l" title={f.what}>{f.label}</td>
                      {cell(f.key, l)}
                      <td className={`r ${Math.abs(l.t) >= SIG ? "" : "text-dim"}`}>{num(l.t, 1)}</td>
                      <td className="l text-dim" style={{ fontFamily: "var(--font-sans)" }}>{reading(f.key, l)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className="px-3 pb-1 pt-3 text-[10.5px] tracking-widest text-dim">BY HOLDING</div>
            <table className="grid-table">
              <thead>
                <tr>
                  <th className="l">Symbol</th><th className="r">Weight</th><th className="r">Market</th><th className="r">Size</th>
                  <th className="r">Value</th><th className="r">Mom.</th><th className="r">Alpha/yr</th><th className="r">R²</th>
                </tr>
              </thead>
              <tbody>
                {data.holdings.map((h) => (
                  <tr key={h.symbol}>
                    <td className="l text-cyan" title={h.name}>{ticker(h.symbol)}</td>
                    <td className="r">{num(h.weight * 100, 1)}%</td>
                    {FACTORS.map((f) => cell(f.key, h.loadings[f.key]))}
                    <td className={`r ${Math.abs(h.alpha.t) >= SIG ? (h.alpha.annual > 0 ? "text-up" : "text-down") : "text-dim"}`}
                        title={`t = ${num(h.alpha.t)}`}>{fmt(h.alpha.annual * 100)}%</td>
                    <td className="r">{num(h.r2 * 100, 0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <div className="space-y-1 border-t border-line px-3 py-2 text-[10.5px] text-dim" style={{ fontFamily: "var(--font-sans)" }}>
          {data.notes.map((n, i) => <div key={i} className={i === 0 ? "text-amber" : ""}>{i === 0 ? "⚠ " : ""}{n}</div>)}
          <div>Coloured loadings are clear tilts (|t| ≥ 2, about 95% confidence); grey ones could be chance.</div>
          <div>
            Data:{" "}
            <a href={data.source} target="_blank" rel="noreferrer noopener" className="underline hover:text-ink">
              IIM Ahmedabad Fama-French and Momentum factors for India
            </a>
            , release {data.release}. {data.citation}
          </div>
        </div>
      </div>
    </div>
  );
}
