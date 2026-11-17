import { num } from "../format";
import { useMarkets } from "../state/markets";
import { MarketsLoading, MarketsOffline, changeText } from "./marketsShared";

const REGIONS = ["India", "US", "UK", "Europe", "Asia"];

/** Tint for a day's change: teal up, pink down, strongest at ±3%. */
function tint(v: number | null): string {
  if (v == null || v === 0) return "transparent";
  const a = Math.min(Math.abs(v) / 0.03, 1) * 0.35 + 0.08;
  return v > 0 ? `rgb(20 217 165 / ${a})` : `rgb(255 77 109 / ${a})`;
}

/** World indices grouped by region, each tile tinted by the day's move. */
export function GlobalMarketsCard() {
  const { data, loading, error, retry } = useMarkets();
  if (!data) return error ? <MarketsOffline error={error} retry={retry} loading={loading} /> : <MarketsLoading />;
  if (!data.online) return <MarketsOffline error={null} retry={retry} loading={loading} />;

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto p-3">
      {REGIONS.map((region) => {
        const rows = data.global.filter((g) => g.region === region);
        if (!rows.length) return null;
        return (
          <div key={region}>
            <div className="mb-1 text-[10.5px] tracking-widest text-dim">{region.toUpperCase()}</div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(130px,1fr))] gap-2">
              {rows.map((g) => (
                <div key={g.symbol} className="rounded-lg border border-line px-2.5 py-2"
                     style={{ background: tint(g.change_pct) }} title={g.symbol}>
                  <div className="truncate text-[11px] text-ink/80">{g.name}</div>
                  <div className="font-mono text-[13px]">{num(g.last)}</div>
                  <div className="font-mono text-[11.5px]">{changeText(g.change_pct)}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
