import { num } from "../format";
import { Empty } from "../ui";

/** Shown by every Markets card when the data could not be loaded. */
export function MarketsOffline({ error, retry, loading }: { error: string | null; retry: () => void; loading: boolean }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
      <div className="text-dim">Market data is offline</div>
      <div className="max-w-xs text-[11px] text-dim/70">
        {error ?? "Yahoo Finance could not be reached. The rest of the terminal works from your saved data."}
      </div>
      <button onClick={retry} disabled={loading}
              className="rounded-md border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-black disabled:opacity-40">
        {loading ? "LOADING…" : "RETRY"}
      </button>
    </div>
  );
}

export function MarketsLoading() {
  return <Empty title="Loading market data…" />;
}

/** "+1.23%" / "−0.45%" with the sign spelled out. */
export function changeText(v: number | null): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${num(Math.abs(v) * 100)}%`;
}

export function changeTone(v: number | null): string {
  return v == null || v === 0 ? "text-dim" : v > 0 ? "text-up" : "text-down";
}

export function cssVar(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}
