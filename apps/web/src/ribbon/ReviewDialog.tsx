import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ActionReview } from "../api/types";
import { num, ticker } from "../format";
import { useStore } from "../state/store";

const btn = "border px-2.5 py-1 text-[11px] disabled:opacity-40";

function ratio(a: ActionReview): string {
  if (a.kind === "bonus") {
    // value is the share multiplier: 2 = 1:1 bonus, 1.5 = 1:2 bonus
    const extra = a.value - 1;
    return extra > 0 ? `${num(extra, extra % 1 ? 2 : 0)} new for every 1 held (×${num(a.value)})` : `×${num(a.value)}`;
  }
  return `1 share became ${num(a.value, a.value % 1 ? 2 : 0)} (×${num(a.value)})`;
}

/** Asks, once per split or bonus, whether the uploaded trades already include it.
 *  Until answered, the action is applied (the usual case) and flagged. */
export function ReviewDialog() {
  const open = useStore((s) => s.reviewOpen);
  const setOpen = useStore((s) => s.setReviewOpen);
  const reload = useStore((s) => s.reload);
  const [items, setItems] = useState<ActionReview[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    api.reviews().then(setItems).catch((e) => setError((e as Error).message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  if (!open) return null;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      const next = await api.reviews();
      setItems(next);
      await reload(false);
      if (!next.length) setOpen(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const suggested = (items ?? []).filter((i) => i.suggestion.answer).length;

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 pt-16"
         onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="review-title"
           className="flex max-h-[84vh] w-[760px] max-w-[94vw] flex-col border border-amber bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 id="review-title" className="tracking-widest text-amber">CHECK SPLITS AND BONUS ISSUES</h2>
          <button onClick={() => setOpen(false)} aria-label="Close" className="text-dim hover:text-ink">✕</button>
        </div>

        <div className="border-b border-line px-4 py-3 text-[11px] leading-relaxed text-dim">
          These happened between the trade dates and the day the trades were uploaded. Some brokers restate old
          trades after a split, and applying it again would double-count the shares. For each one, say whether
          your file lists the trades <span className="text-ink">as originally traded</span> (apply it) or
          <span className="text-ink"> already adjusted</span> (skip it). Until you answer, it is applied.
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {items == null && !error && <div className="text-dim">…</div>}
          {items?.length === 0 && <div className="text-up">Nothing to check. Every split and bonus is settled.</div>}
          <ul className="space-y-3">
            {items?.map((a) => (
              <li key={a.id} className="border border-line p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <div>
                    <span className="font-semibold text-cyan">{ticker(a.symbol)}</span>
                    <span className="ml-2 text-amber">{a.kind.toUpperCase()}</span>
                    <span className="ml-2">{ratio(a)}</span>
                  </div>
                  <span className="text-[11px] text-dim">
                    ex-date {a.ex_date} · {a.trades_before} trade{a.trades_before === 1 ? "" : "s"} before it
                    {a.uploaded_on ? ` · uploaded ${a.uploaded_on}` : ""} · source {a.source}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] tabular-nums sm:grid-cols-3">
                  <span><span className="text-dim">Holding if applied </span>{num(a.quantity_if_applied, 0)}</span>
                  <span><span className="text-dim">Holding if skipped </span>{num(a.quantity_if_skipped, 0)}</span>
                  {a.broker_quantity != null && (
                    <span><span className="text-dim">Broker says </span><span className="text-ink">{num(a.broker_quantity, 0)}</span></span>
                  )}
                </div>
                <p className={`mt-2 text-[11px] ${a.suggestion.answer ? "text-ink" : "text-dim"}`}>
                  {a.suggestion.answer && (
                    <span className="mr-1 text-amber">
                      Suggested: {a.suggestion.answer === "apply" ? "apply it" : "skip it"}.
                    </span>
                  )}
                  {a.suggestion.reason}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button disabled={busy} onClick={() => act(() => api.decideReview(a.id, "apply"))}
                          className={`${btn} ${a.suggestion.answer === "apply" ? "border-amber text-amber hover:bg-amber hover:text-black" : "border-line text-dim hover:text-ink"}`}>
                    FILE IS AS TRADED · APPLY
                  </button>
                  <button disabled={busy} onClick={() => act(() => api.decideReview(a.id, "skip"))}
                          className={`${btn} ${a.suggestion.answer === "skip" ? "border-amber text-amber hover:bg-amber hover:text-black" : "border-line text-dim hover:text-ink"}`}>
                    FILE ALREADY ADJUSTED · SKIP
                  </button>
                </div>
              </li>
            ))}
          </ul>
          {error && <div role="alert" className="mt-3 text-down">{error}</div>}
        </div>

        {(items?.length ?? 0) > 0 && (
          <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2.5">
            <span className="text-[11px] text-dim">
              {suggested ? `${suggested} of ${items!.length} have a suggested answer` : "Answer each one above"}
            </span>
            <div className="flex gap-2">
              <button onClick={() => setOpen(false)} className={`${btn} border-line text-dim hover:text-ink`}>
                ASK ME LATER
              </button>
              {suggested > 0 && (
                <button disabled={busy} onClick={() => act(() => api.acceptSuggestions())}
                        className={`${btn} border-amber text-amber hover:bg-amber hover:text-black`}>
                  ACCEPT SUGGESTIONS
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
