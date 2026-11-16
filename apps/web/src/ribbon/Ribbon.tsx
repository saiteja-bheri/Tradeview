import { feedLabel, isRealtime } from "../format";
import { useStore } from "../state/store";
import { Seg } from "../ui";
import { BenchmarkPicker } from "./BenchmarkPicker";
import { SearchBox } from "./SearchBox";

const CURRENCIES = ["AUTO", "INR", "USD", "EUR", "GBP", "JPY", "AED", "SGD", "AUD", "CAD", "CHF", "HKD"];

export function Ribbon() {
  const status = useStore((s) => s.status);
  const busy = useStore((s) => s.busy);
  const params = useStore((s) => s.portfolio?.params);
  const setParam = useStore((s) => s.setParam);
  const setImportOpen = useStore((s) => s.setImportOpen);
  const display = useStore((s) => s.portfolio?.display);
  const refreshPrices = useStore((s) => s.refreshPrices);
  const setPalette = useStore((s) => s.setPalette);
  const setConnectOpen = useStore((s) => s.setConnectOpen);
  const feed = useStore((s) => s.live?.status);
  const pendingReviews = useStore((s) => s.portfolio?.pending_reviews ?? 0);
  const setReviewOpen = useStore((s) => s.setReviewOpen);

  const mod = navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl+";
  const live = feed?.state === "live";
  const dot =
    status === "down" || feed?.state === "error" ? "bg-down"
    : status === "ok" && live && isRealtime(feed) ? "bg-up"
    : "bg-amber";
  const label =
    busy ? "CALC" : status === "down" ? "DOWN" : status !== "ok" ? "INIT" : feedLabel(feed);

  return (
    <header className="flex h-10 shrink-0 items-center gap-3 whitespace-nowrap border-b border-line bg-panel px-3 xl:gap-4">
      <div className="flex items-center gap-2">
        <span className="bg-amber px-1.5 py-0.5 text-[11px] font-bold tracking-widest text-black">QT</span>
        <span className="hidden text-[10px] tracking-widest text-dim 2xl:inline">READ-ONLY</span>
      </div>

      <SearchBox />

      <BenchmarkPicker />
      <Seg<number>
        label="VAR" value={params?.confidence}
        options={[{ value: 0.95, label: "95%" }, { value: 0.99, label: "99%" }]}
        onChange={(v) => setParam({ confidence: v })}
      />
      <Seg<number>
        label="VAR HORIZON" value={params?.horizon_days}
        options={[1, 2, 3, 5, 10].map((d) => ({ value: d, label: `${d}D` }))}
        onChange={(v) => setParam({ horizon_days: v })}
      />

      <div className="ml-auto flex shrink-0 items-center gap-2 whitespace-nowrap">
        {pendingReviews > 0 && (
          <button onClick={() => setReviewOpen(true)}
                  title="Splits or bonus issues that may already be in your uploaded trades"
                  className="border border-amber px-2 py-1 text-amber hover:bg-amber hover:text-black">
            CHECK SPLITS · {pendingReviews}
          </button>
        )}
        <button onClick={() => setPalette(true)}
                className="border border-line px-2 py-1 text-dim hover:border-amber hover:text-ink">
          COMMANDS <span className="text-dim/60">{mod}K</span>
        </button>
        <button onClick={() => setConnectOpen(true)}
                title="Brokers and price sources"
                className="border border-line px-2 py-1 text-dim hover:border-amber hover:text-ink">
          CONNECT
        </button>
        <button onClick={() => refreshPrices()} disabled={busy}
                className="border border-line px-2 py-1 text-dim hover:border-amber hover:text-ink disabled:opacity-40">
          REFRESH
        </button>
        <label className="flex items-center gap-1 text-[10px] tracking-widest text-dim"
               title={display?.choice === "AUTO" ? `AUTO: showing ${display.currency}, the currency most of your portfolio is in`
                 : "Currency money is shown in. Calculations stay in rupees."}>
          CCY
          <select value={params?.display_currency ?? "INR"} aria-label="Display currency"
                  onChange={(e) => setParam({ display_currency: e.target.value })}
                  className="border border-line bg-bg px-1 py-0.5 text-[11px] text-ink outline-none focus:border-amber">
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>{c === "AUTO" && display?.choice === "AUTO" ? `AUTO (${display.currency})` : c}</option>
            ))}
          </select>
        </label>
        <button onClick={() => setImportOpen(true)}
                title="Upstox, Zerodha, Groww or any trade file (CSV or Excel)"
                className="border border-amber px-2 py-1 text-amber hover:bg-amber hover:text-black">
          IMPORT CSV / EXCEL
        </button>
        <span className="flex items-center gap-1.5 pl-1 text-[10px] tracking-widest text-dim"
              title={feed?.detail || `Engine ${status}`}>
          <span className={`h-2 w-2 rounded-full ${dot} ${busy ? "animate-pulse" : ""}`} />
          {label}
        </span>
      </div>
    </header>
  );
}
