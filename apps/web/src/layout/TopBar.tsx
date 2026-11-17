import { feedLabel, inr, isRealtime, signed, tone } from "../format";
import { SearchBox } from "../ribbon/SearchBox";
import { useStore } from "../state/store";
import { Flash } from "../ui";

function Figure({ label, value, text, cls = "" }: { label: string; value: number | null | undefined; text: string; cls?: string }) {
  return (
    <div className="min-w-0 leading-tight">
      <div className="text-[10px] tracking-widest text-dim">{label}</div>
      <div className={`font-mono text-[13.5px] font-semibold ${cls}`}><Flash value={value}>{text}</Flash></div>
    </div>
  );
}

/** Portfolio figures, search, feed status and the two everyday actions. */
export function TopBar() {
  const status = useStore((s) => s.status);
  const busy = useStore((s) => s.busy);
  const portfolio = useStore((s) => s.portfolio);
  const lp = useStore((s) => s.live?.portfolio);
  const feed = useStore((s) => s.live?.status);
  const pendingReviews = useStore((s) => s.portfolio?.pending_reviews ?? 0);
  const setReviewOpen = useStore((s) => s.setReviewOpen);
  const refreshPrices = useStore((s) => s.refreshPrices);
  const setImportOpen = useStore((s) => s.setImportOpen);
  const openSettings = useStore((s) => s.openSettings);

  // Live totals replace the close-based ones only when every holding has a live quote.
  const full = lp != null && lp.held > 0 && lp.priced === lp.held;
  const value = full ? lp.value : portfolio?.portfolio_value;
  const unrealized = full ? lp.unrealized_pnl : portfolio?.unrealized_pnl;
  const day = full ? lp.day_pnl : null;
  const dayPct = day != null && value ? day / (value - day) : null;

  const live = feed?.state === "live";
  const dot =
    status === "down" || feed?.state === "error" ? "bg-down"
    : status === "ok" && live && isRealtime(feed) ? "bg-up"
    : "bg-amber";
  const label = busy ? "CALC" : status === "down" ? "DOWN" : status !== "ok" ? "INIT" : feedLabel(feed);
  const btn = "rounded-md border border-line px-2.5 py-1 text-dim hover:border-accent hover:text-ink disabled:opacity-40";

  return (
    <header className="flex h-14 shrink-0 items-center gap-5 whitespace-nowrap border-b border-line bg-panel px-3">
      <div className="flex w-[34px] shrink-0 justify-center">
        <span className="rounded-md bg-accent px-1.5 py-0.5 text-[11px] font-bold tracking-widest text-black">QT</span>
      </div>
      <span className="hidden rounded-full border border-line px-2 py-0.5 text-[10px] tracking-widest text-dim xl:inline"
            title="This terminal cannot place, change or cancel orders">READ-ONLY</span>

      <div className="flex items-center gap-6">
        <Figure label="PORTFOLIO VALUE" value={value} text={inr(value)} />
        <Figure label="DAY P&L" value={day}
                text={day == null ? "—" : `${signed(day)}${dayPct != null ? `  ${dayPct > 0 ? "+" : ""}${(dayPct * 100).toFixed(2)}%` : ""}`}
                cls={tone(day)} />
        <Figure label="UNREALIZED" value={unrealized} text={signed(unrealized)} cls={tone(unrealized)} />
      </div>

      <div className="ml-auto flex min-w-0 items-center gap-2">
        <SearchBox />
        {pendingReviews > 0 && (
          <button onClick={() => setReviewOpen(true)}
                  title="Splits or bonus issues that may already be in your uploaded trades"
                  className="rounded-md border border-amber px-2.5 py-1 text-amber hover:bg-amber hover:text-black">
            CHECK SPLITS · {pendingReviews}
          </button>
        )}
        <button onClick={() => openSettings("connections")} title={feed?.detail || `Engine ${status}`}
                className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[10.5px] tracking-widest text-dim hover:bg-raise">
          <span className={`h-2 w-2 rounded-full ${dot} ${busy ? "animate-pulse" : ""}`} />
          {label}
        </button>
        <button onClick={() => refreshPrices()} disabled={busy} className={btn}>REFRESH</button>
        <button onClick={() => setImportOpen(true)} title="Upstox, Zerodha, Groww or any trade file (CSV or Excel)"
                className="rounded-md border border-accent px-2.5 py-1 text-accent hover:bg-accent hover:text-black">
          IMPORT
        </button>
      </div>
    </header>
  );
}
