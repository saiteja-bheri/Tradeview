import { useEffect, useState } from "react";
import { api } from "../api/client";
import { inr, num, pct, signed, ticker, tone } from "../format";
import { useStore } from "../state/store";
import { Empty, EyeIcon, Flash } from "../ui";

/** Facts about the selected stock: price, your position in it and its share of
 *  portfolio risk. Read-only by design: this is where other terminals put an
 *  order ticket, and this app has none. */
export function StockPanel() {
  const selected = useStore((s) => s.selected);
  const holding = useStore((s) => s.portfolio?.holdings.find((h) => h.symbol === s.selected));
  const totalVar = useStore((s) => s.portfolio?.metrics?.var ?? null);
  const quote = useStore((s) => (s.selected ? s.live?.quotes?.[s.selected] : undefined));
  const mark = useStore((s) => s.watch.find((w) => w.symbol === s.selected)
    ?? s.history.find((w) => w.symbol === s.selected));
  const toggleStar = useStore((s) => s.toggleStar);
  const toggleWatch = useStore((s) => s.toggleWatch);
  const [range, setRange] = useState<{ symbol: string; high: number | null; low: number | null; last: number | null } | null>(null);

  useEffect(() => {
    if (!selected) return;
    let live = true;
    api.prices(selected, 365)
      .then((r) => {
        if (!live) return;
        const closes = r.bars.map((b) => b.close);
        setRange({
          symbol: selected,
          high: closes.length ? Math.max(...closes) : null,
          low: closes.length ? Math.min(...closes) : null,
          last: closes.length ? closes[closes.length - 1] : null,
        });
      })
      .catch(() => live && setRange({ symbol: selected, high: null, low: null, last: null }));
    return () => { live = false; };
  }, [selected]);

  if (!selected) return <Empty title="No stock selected" hint="Search a stock or pick one from your holdings." />;
  const r = range?.symbol === selected ? range : null;
  const name = holding?.name || mark?.name || "";
  const price = quote?.ltp ?? holding?.last ?? mark?.last ?? r?.last ?? null;
  const change = quote?.change_pct ?? mark?.change_pct ?? null;
  const varShare = holding?.component_var != null && totalVar ? holding.component_var / totalVar : null;
  const starred = !!mark?.starred, watched = !!mark?.watched;

  const row = (label: string, value: string, cls = "") => (
    <div key={label} className="flex items-baseline justify-between border-b border-line/60 py-1.5">
      <span className="text-[10.5px] tracking-widest text-dim">{label}</span>
      <span className={`font-mono ${cls}`}>{value}</span>
    </div>
  );

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[15px] font-semibold">{ticker(selected)}</div>
          {name && <div className="truncate text-[11px] text-dim" title={name}>{name}</div>}
        </div>
        <div className="flex shrink-0 gap-1">
          <button onClick={() => toggleWatch(selected, name)} aria-pressed={watched}
                  title={watched ? "On your watchlist" : "Add to watchlist"}
                  className={`rounded-md border px-2 py-1 ${watched ? "border-accent text-accent" : "border-line text-dim hover:text-ink"}`}>
            <EyeIcon on={watched} />
          </button>
          <button onClick={() => toggleStar(selected, name)} aria-pressed={starred}
                  title={starred ? "Starred for the optimizer" : "Star for the optimizer"}
                  className={`rounded-md border px-2 py-1 ${starred ? "border-accent text-accent" : "border-line text-dim hover:text-ink"}`}>
            {starred ? "★" : "☆"}
          </button>
        </div>
      </div>

      <div className="flex items-baseline gap-3">
        <span className={`font-mono text-[26px] font-semibold ${tone(change)}`}>
          <Flash value={price}>{num(price)}</Flash>
        </span>
        <span className={`font-mono ${tone(change)}`}>{change == null ? "" : `${change > 0 ? "+" : ""}${pct(change)}`}</span>
      </div>

      <div>
        <div className="mb-1 text-[10.5px] tracking-widest text-dim">YOUR POSITION</div>
        {holding ? (
          <>
            {row("QUANTITY", num(holding.quantity, Number.isInteger(holding.quantity) ? 0 : 2))}
            {row("AVG COST", num(holding.avg_cost))}
            {row("VALUE", inr(holding.value))}
            {row("UNREALIZED", signed(holding.unrealized_pnl), tone(holding.unrealized_pnl))}
            {row("REALIZED", signed(holding.realized_pnl), tone(holding.realized_pnl))}
            {row("WEIGHT", pct(holding.weight))}
            {row("BETA", num(holding.beta))}
            {row("SHARE OF VAR", pct(varShare))}
          </>
        ) : (
          <div className="rounded-md border border-line px-3 py-2 text-dim">Not in your portfolio.</div>
        )}
      </div>

      <div>
        <div className="mb-1 text-[10.5px] tracking-widest text-dim">52 WEEKS</div>
        {row("HIGH", num(r?.high))}
        {row("LOW", num(r?.low))}
      </div>
    </div>
  );
}
