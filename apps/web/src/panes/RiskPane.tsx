import { ASSET_NAME, inr, num, pct, signed, ticker, tone } from "../format";
import { useStore } from "../state/store";
import { Empty, Flash, Seg } from "../ui";
import { RollingChart } from "./RollingChart";

export function RiskPane() {
  const p = useStore((s) => s.portfolio);
  const setParam = useStore((s) => s.setParam);
  if (!p) return <Empty title="Waiting for engine" />;
  const m = p.metrics;
  const conf = Math.round(p.params.confidence * 100);
  const bench = (p.params.benchmark_name || p.params.benchmark).toUpperCase();
  const withVar = p.holdings.filter((h) => h.component_var != null);
  const maxVar = Math.max(...withVar.map((h) => Math.abs(h.component_var!)), 1e-9);

  return (
    <div className="flex flex-col">
      <div className="border-b border-line px-3 py-3">
        <div className="text-[10px] tracking-widest text-dim">
          PARAMETRIC VAR · {conf}% · {p.params.horizon_days}D
          {p.live && <span className="ml-2 text-up" title="Every figure below counts today's live prices as a provisional day; recomputed about once a minute">● LIVE</span>}
        </div>
        <div className="mt-1 flex items-baseline gap-2">
          <span className="text-2xl font-semibold text-amber">
            <Flash value={m?.var}>{inr(m?.var)}</Flash>
          </span>
          <span className="text-dim">{pct(m?.var_pct)} of value</span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <Seg<number>
          label="LOOKBACK" value={p.params.lookback_days}
          options={LOOKBACKS}
          onChange={(v) => setParam({ lookback_days: v })}
        />
        <span className="text-[10px] text-dim" title="Trading days of daily returns behind every ratio below">
          {p.observations} of {p.params.lookback_days} days
        </span>
      </div>

      <div className="grid grid-cols-2">
        <Tile label={`BETA vs ${bench}`} value={m?.beta} text={num(m?.beta)} />
        <Tile label="JENSEN'S ALPHA (ANN.)" value={m?.jensens_alpha_annualized}
              text={pct(m?.jensens_alpha_annualized)} cls={tone(m?.jensens_alpha_annualized)} />
        <Tile label="SHARPE" value={m?.sharpe} text={num(m?.sharpe)} cls={tone(m?.sharpe)} />
        <Tile label="SORTINO" value={m?.sortino} text={num(m?.sortino)} cls={tone(m?.sortino)} />
        <Tile label="MAX DRAWDOWN" value={m?.max_drawdown} text={pct(m?.max_drawdown)} cls="text-down" />
        <Tile label="VOLATILITY (ANN.)" value={m?.volatility_annualized} text={pct(m?.volatility_annualized)} />
        <Tile label="PORTFOLIO VALUE" value={p.portfolio_value} text={inr(p.portfolio_value)} />
        <Tile label="DIVIDENDS & COUPONS" value={p.dividends} text={inr(p.dividends)} />
        <Tile label="TOTAL RETURN" value={p.returns?.total_return}
              text={p.returns?.total_return == null ? "—" : `${signed(p.returns.total_return)} · ${pct(p.returns.total_return_pct, 1)}`}
              cls={tone(p.returns?.total_return)} />
        <Tile label="XIRR (ANN.)" value={p.returns?.xirr} text={pct(p.returns?.xirr)} cls={tone(p.returns?.xirr)} />
      </div>

      <RollingChart />

      {(p.allocation?.length ?? 0) > 0 && (
        <div className="border-t border-line px-3 py-3">
          <div className="mb-2 text-[10px] tracking-widest text-dim">ALLOCATION</div>
          {p.allocation!.map((a) => (
            <div key={a.asset_class} className="mb-1.5 grid grid-cols-[96px_1fr_128px] items-center gap-2">
              <span className="truncate">{ASSET_NAME[a.asset_class] ?? a.asset_class}</span>
              <div className="h-1.5 bg-raise">
                <div className="h-full bg-cyan" style={{ width: `${(a.weight ?? 0) * 100}%` }} />
              </div>
              <span className="text-right tabular-nums">
                {pct(a.weight, 1)} <span className="text-dim">{inr(a.value)}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {withVar.length > 0 && (
        <div className="border-t border-line px-3 py-3">
          <div className="mb-2 text-[10px] tracking-widest text-dim">VAR CONTRIBUTION</div>
          {withVar.map((h) => (
            <div key={h.symbol} className="mb-1.5 grid grid-cols-[72px_1fr_64px] items-center gap-2">
              <span className="truncate text-cyan">{ticker(h.symbol)}</span>
              <div className="h-1.5 bg-raise">
                <div className="h-full bg-amber"
                     style={{ width: `${(Math.abs(h.component_var!) / maxVar) * 100}%` }} />
              </div>
              <span className="text-right">{signed(h.component_var)}</span>
            </div>
          ))}
        </div>
      )}

      <div className="border-t border-line px-3 py-2 text-[10px] text-dim">
        {p.observations} daily returns · as of {p.as_of ?? "—"} · risk-free {pct(p.params.risk_free_rate, 1)}
      </div>

      {p.warnings.length > 0 && (
        <ul className="border-t border-line px-3 py-2 text-[10.5px] text-amber">
          {p.warnings.map((w, i) => (
            <li key={i} className="mb-1">⚠ {w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Trading days of history used for beta, alpha, Sharpe, Sortino, drawdown, volatility and VaR. */
const LOOKBACKS = [
  { value: 21, label: "1M" }, { value: 63, label: "3M" }, { value: 126, label: "6M" },
  { value: 252, label: "1Y" }, { value: 504, label: "2Y" }, { value: 756, label: "3Y" },
  { value: 1260, label: "5Y" },
];

function Tile({ label, value, text, cls = "" }: {
  label: string; value: number | null | undefined; text: string; cls?: string;
}) {
  return (
    <div className="border-b border-r border-line px-3 py-2.5 even:border-r-0">
      <div className="text-[10px] tracking-widest text-dim">{label}</div>
      <div className={`mt-0.5 text-[15px] ${cls}`}>
        <Flash value={value}>{text}</Flash>
      </div>
    </div>
  );
}
