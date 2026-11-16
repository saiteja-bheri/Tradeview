import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CacheStatus, WatchItem } from "../api/types";
import { ASSET_TAG, num, signedPct, ticker, tone } from "../format";
import { useStore } from "../state/store";
import { Empty, EyeIcon } from "../ui";

/** Stocks you watch (eye) and stocks starred for the optimizer (star). Their
 *  daily prices are kept in the local database; stocks you only looked at are
 *  in the HISTORY tab instead and cost no downloads. */
export function WatchlistPane() {
  const watch = useStore((s) => s.watch);
  const load = useStore((s) => s.loadWatchlist);
  const [cache, setCache] = useState<CacheStatus | null>(null);

  useEffect(() => {
    load();
    api.cache().then(setCache).catch(() => {});
  }, [load, watch.length]);

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        {!watch.length ? (
          <Empty title="Nothing on the watchlist yet"
                 hint="In the search, press the eye to watch a stock, or ☆ to star it for the OPTIMIZER. Stocks you only open go to HISTORY." />
        ) : (
          <StockTable rows={watch} showCache />
        )}
      </div>
      {cache && (
        <div className="border-t border-line bg-bg px-3 py-2 text-[10.5px] text-dim">
          <div className="flex flex-wrap gap-x-4 gap-y-0.5">
            <span><span className="tracking-widest">CACHE</span> {cache.symbols.length} symbols · {cache.bars.toLocaleString("en-IN")} bars</span>
            <span title="Requests answered locally with no download">served locally {cache.served_from_cache}</span>
            <span title="Only the days since the last download were fetched">top-ups {cache.incremental_updates}</span>
            <span title="Whole history fetched: first time, or after a new split or dividend">full {cache.full_downloads}</span>
          </div>
          <div className="mt-0.5 truncate" title={cache.database}>{cache.database}</div>
        </div>
      )}
    </div>
  );
}

/** Rows of stocks with watch and star toggles. Shared by WATCHLIST and HISTORY. */
export function StockTable({ rows, showCache = false, onRemove }: {
  rows: WatchItem[]; showCache?: boolean; onRemove?: (symbol: string) => void;
}) {
  const toggleStar = useStore((s) => s.toggleStar);
  const toggleWatch = useStore((s) => s.toggleWatch);
  const openSymbol = useStore((s) => s.openSymbol);
  const selected = useStore((s) => s.selected);
  const watch = useStore((s) => s.watch);
  const marks = new Map(watch.map((w) => [w.symbol, w]));

  const exportCsv = async (symbol: string) => {
    try {
      const blob = await api.pricesCsv(symbol);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${symbol.replace(/[^A-Za-z0-9._-]/g, "_")}-prices.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      useStore.setState({ error: (e as Error).message });
    }
  };

  return (
    <table className="grid-table">
      <thead>
        <tr>
          <th className="l" aria-label="Watch and star" />
          <th className="l">Symbol</th>
          <th className="r">Last</th>
          <th className="r">Day</th>
          {showCache ? <th className="r" title="Daily bars stored locally">Cached</th> : <th className="r">Viewed</th>}
          <th className="l" />
        </tr>
      </thead>
      <tbody>
        {rows.map((w) => {
          const m = marks.get(w.symbol) ?? w;
          return (
            <tr key={w.symbol} className={`hover:bg-raise ${w.symbol === selected ? "bg-raise" : ""}`}>
              <td className="l whitespace-nowrap">
                <button onClick={() => toggleWatch(w.symbol, w.name)} aria-pressed={m.watched}
                        aria-label={m.watched ? `Stop watching ${w.symbol}` : `Watch ${w.symbol}`}
                        title={m.watched ? "On the watchlist (prices cached)" : "Add to watchlist"}
                        className={m.watched ? "text-cyan" : "text-dim hover:text-cyan"}>
                  <EyeIcon on={m.watched} />
                </button>
                <button onClick={() => toggleStar(w.symbol, w.name)} aria-pressed={m.starred}
                        aria-label={m.starred ? `Unstar ${w.symbol}` : `Star ${w.symbol}`}
                        title={m.starred ? "Starred for the optimizer" : "Star for the optimizer"}
                        className={`ml-1.5 ${m.starred ? "text-amber" : "text-dim hover:text-amber"}`}>
                  {m.starred ? "★" : "☆"}
                </button>
              </td>
              <td className="l cursor-pointer" onClick={() => openSymbol(w.symbol, w.name, w.exchange || undefined)}
                  title={w.name || undefined}>
                <span className="font-semibold text-cyan">{ticker(w.symbol)}</span>
                {w.asset_class !== "equity" && (
                  <span className={`ml-1.5 text-[9px] tracking-widest ${ASSET_TAG[w.asset_class]?.cls ?? "text-dim"}`}>
                    {ASSET_TAG[w.asset_class]?.label}
                  </span>
                )}
                {w.held && <span className="ml-1.5 text-[9px] tracking-widest text-up">HELD</span>}
                <div className="max-w-[180px] truncate text-[10px] text-dim">{w.name}</div>
              </td>
              <td className="r tabular-nums">
                {num(w.last)}{w.last != null && w.currency !== "INR" && <span className="ml-1 text-[9px] text-dim">{w.currency}</span>}
              </td>
              <td className={`r ${tone(w.change_pct)}`}>{w.change_pct == null ? "—" : signedPct(w.change_pct)}</td>
              {showCache ? (
                <td className="r text-dim tabular-nums" title={w.as_of ? `Latest bar ${w.as_of}` : undefined}>{w.cached_bars}</td>
              ) : (
                <td className="r text-dim tabular-nums" title={w.viewed_at ?? undefined}>{ago(w.viewed_at)}</td>
              )}
              <td className="l whitespace-nowrap">
                {showCache && w.cached_bars > 0 && (
                  <button onClick={() => exportCsv(w.symbol)} className="text-[10px] text-dim underline hover:text-ink">csv</button>
                )}
                {onRemove && (
                  <button onClick={() => onRemove(w.symbol)} aria-label={`Remove ${w.symbol} from history`}
                          className="text-dim hover:text-down">✕</button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ago(iso: string | null): string {
  if (!iso) return "—";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h`;
  return `${Math.round(mins / 1440)}d`;
}
