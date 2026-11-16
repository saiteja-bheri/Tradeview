import { useEffect } from "react";
import { api } from "../api/client";
import { useStore } from "../state/store";
import { Empty } from "../ui";
import { StockTable } from "./WatchlistPane";

/** Stocks opened from the search, newest first. Only the visit is recorded:
 *  no prices are downloaded or stored for them unless you watch or star one. */
export function HistoryPane() {
  const history = useStore((s) => s.history);
  const load = useStore((s) => s.loadHistory);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async (symbol: string) => {
    useStore.setState({ history: await api.forgetVisit(symbol) });
  };
  const clear = async () => {
    useStore.setState({ history: await api.clearHistory() });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5 text-[10.5px] text-dim">
        <span>Stocks you opened. No prices are saved for these unless you watch or star them.</span>
        {history.length > 0 && (
          <button onClick={clear} className="shrink-0 border border-line px-2 py-0.5 text-[10px] text-dim hover:border-down hover:text-down">
            CLEAR
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {!history.length ? (
          <Empty title="No history yet" hint="Every stock you open from the search appears here so you can go back to it." />
        ) : (
          <StockTable rows={history} onRemove={remove} />
        )}
      </div>
    </div>
  );
}
