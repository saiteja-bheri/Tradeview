import { useState } from "react";
import { api } from "../api/client";
import { num, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty } from "../ui";

const SOURCE: Record<string, string> = { yfinance: "Yahoo", bse: "BSE", manual: "Manual", coupon: "Coupon" };

export function ActionsPane() {
  const actions = useStore((s) => s.actions);
  const reload = useStore((s) => s.reload);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);

  const syncBse = async () => {
    setBusy(true);
    setNote(null);
    try {
      const r = await api.bseSync();
      const parts = [`${r.added.length} added from BSE`, `${r.already_recorded} already recorded`];
      if (r.failed.length) parts.push(`${r.failed.length} not found`);
      setNote({ text: parts.join(" · ") });
      await reload(false);
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-1.5">
        <button onClick={syncBse} disabled={busy}
                title="Pull dividends, bonus issues and splits for your stocks from BSE (experimental)"
                className="border border-line px-2 py-0.5 text-[11px] text-dim hover:border-amber hover:text-ink disabled:opacity-40">
          {busy ? "SYNCING…" : "SYNC FROM BSE"}
        </button>
        {note && <span role="status" className={`text-[11px] ${note.bad ? "text-down" : "text-dim"}`}>{note.text}</span>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {!actions.length ? (
          <Empty title="No corporate actions"
                 hint="Splits, bonuses, dividends and bond coupons appear here after prices are refreshed. SYNC FROM BSE adds the exchange's own records." />
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th className="l">Ex-date</th>
                <th className="l">Symbol</th>
                <th className="l">Type</th>
                <th className="r">Value</th>
                <th className="l">Source</th>
              </tr>
            </thead>
            <tbody>
              {actions.map((a) => (
                <tr key={a.id}>
                  <td className="l text-dim">{a.ex_date}</td>
                  <td className="l text-cyan">{ticker(a.symbol)}</td>
                  <td className={`l ${a.kind === "dividend" ? "text-ink" : "text-amber"}`}>
                    {a.source === "coupon" ? "COUPON" : a.kind.toUpperCase()}
                  </td>
                  <td className="r">{a.kind === "dividend" ? `₹${num(a.value)}` : `×${num(a.value)}`}</td>
                  <td className="l text-dim">{SOURCE[a.source] ?? a.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
