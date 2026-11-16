import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { SearchResult, Trade, TradeInput } from "../api/types";
import { num, ticker } from "../format";
import { useStore } from "../state/store";
import { Seg } from "../ui";

const field =
  "w-full border border-line bg-bg px-2 py-1 text-ink outline-none placeholder:text-dim/60 focus:border-amber";
const ghost = "border border-line px-2 py-1 text-dim hover:border-amber hover:text-ink disabled:opacity-40";

function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

/** Form for writing down a trade made elsewhere. It only edits the local ledger. */
const INDIAN = new Set(["NSE", "BSE", "MF", "CMDTY", "BOND"]);

function TradeForm({ trade, onDone }: { trade: Trade | null; onDone: () => void }) {
  const saveTrade = useStore((s) => s.saveTrade);
  const [symbol, setSymbol] = useState(trade?.symbol ?? "");
  const [side, setSide] = useState<"BUY" | "SELL">(trade?.side ?? "BUY");
  const [date, setDate] = useState(trade?.traded_at.slice(0, 10) ?? today());
  const [time, setTime] = useState(trade?.traded_at.slice(11, 16) || "09:15");
  const [quantity, setQuantity] = useState(trade ? String(trade.quantity) : "");
  const [price, setPrice] = useState(trade ? String(trade.price) : "");
  const [matches, setMatches] = useState<SearchResult[]>([]);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const seq = useRef(0);

  // company-name suggestions for the symbol field
  useEffect(() => {
    const q = symbol.trim();
    const mine = ++seq.current;
    if (q.length < 2) return;
    const timer = setTimeout(async () => {
      try {
        const r = await api.search(q);
        if (mine === seq.current) setMatches(r.results);
      } catch {
        /* suggestions are optional */
      }
    }, 200);
    return () => clearTimeout(timer);
  }, [symbol]);

  const qty = Number(quantity);
  const px = Number(price);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const sym = symbol.trim().toUpperCase();
    if (!sym) return setProblem("Enter the stock's ticker.");
    if (!date) return setProblem("Enter the trade date.");
    if (!(qty > 0)) return setProblem("Quantity must be more than zero.");
    if (!(px > 0)) return setProblem("Price must be more than zero.");
    setProblem(null);
    setSaving(true);
    const input: TradeInput = {
      symbol: sym, side, quantity: qty, price: px,
      traded_at: `${date}T${time || "00:00"}:00`,
      name: matches.find((m) => m.symbol === sym)?.name || undefined,
      // Picked from an international search result (AAPL, VOD.L): keep it, price in its own currency.
      market: INDIAN.has(matches.find((m) => m.symbol === sym)?.exchange ?? "NSE") ? undefined : "INTL",
    };
    const ok = await saveTrade(input, trade?.id);
    setSaving(false);
    if (ok) onDone();
  };

  return (
    <form onSubmit={submit} className="border-b border-line bg-raise/40 p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <span className="text-[10px] tracking-widest text-amber">
          {trade ? "EDIT LEDGER ENTRY" : "RECORD A TRADE MADE ELSEWHERE"}
        </span>
        <span className="text-[10px] text-dim">Saved to your ledger only. Nothing is sent to a broker.</span>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="min-w-44 flex-[2]">
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">STOCK</span>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} list="qt-trade-symbols"
                 placeholder="Stock, ETF, fund or GOLD, e.g. INFY" spellCheck={false} autoComplete="off" autoFocus
                 className={`${field} uppercase`} />
          <datalist id="qt-trade-symbols">
            {matches.map((m) => <option key={m.symbol} value={m.symbol}>{m.name}</option>)}
          </datalist>
        </label>
        <div>
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">I</span>
          <Seg<"BUY" | "SELL"> label="Side" value={side} hideLabel
                               options={[{ value: "BUY", label: "BOUGHT" }, { value: "SELL", label: "SOLD" }]}
                               onChange={setSide} />
        </div>
        <label className="min-w-32 flex-1">
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">DATE</span>
          <input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} className={field} />
        </label>
        <label className="min-w-28 flex-1">
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">TIME</span>
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className={field} />
        </label>
        <label className="min-w-24 flex-1">
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">QUANTITY</span>
          <input type="number" min="0" step="any" value={quantity} onChange={(e) => setQuantity(e.target.value)}
                 placeholder="0" className={`${field} text-right`} />
        </label>
        <label className="min-w-24 flex-1">
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">PRICE (₹)</span>
          <input type="number" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)}
                 placeholder="0.00" className={`${field} text-right`} />
        </label>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button type="submit" disabled={saving}
                className="border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40">
          {saving ? "SAVING…" : trade ? "SAVE CHANGES" : "ADD TO LEDGER"}
        </button>
        <button type="button" onClick={onDone} className={ghost}>CANCEL</button>
        {qty > 0 && px > 0 && <span className="text-dim">Amount ₹{num(qty * px)}</span>}
        {problem && <span role="alert" className="text-down">{problem}</span>}
      </div>
    </form>
  );
}

export function TradesPane() {
  const trades = useStore((s) => s.trades);
  const exportCsv = useStore((s) => s.exportCsv);
  const removeTrade = useStore((s) => s.removeTrade);
  // "new" = blank form, a number = editing that trade, null = form closed
  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const current = typeof editing === "number" ? trades.find((t) => t.id === editing) ?? null : null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 whitespace-nowrap border-b border-line px-3 py-1.5">
        <button onClick={() => setEditing("new")}
                className="border border-amber px-2 py-1 text-amber hover:bg-amber hover:text-black">
          + ADD TRADE
        </button>
        <button onClick={() => exportCsv()} disabled={!trades.length} className={ghost}>EXPORT CSV</button>
        <span className="ml-auto text-[10px] text-dim">{trades.length} trades · records only</span>
      </div>

      {editing !== null && (
        <TradeForm key={String(editing)} trade={current} onDone={() => setEditing(null)} />
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {!trades.length ? (
          <div className="flex h-full flex-col items-center justify-center gap-1 p-6 text-center">
            <div className="text-dim">No trades in the ledger</div>
            <div className="max-w-xs text-[10.5px] text-dim/70">
              Import an Upstox, Zerodha or Groww trade report from the ribbon, or add a trade by hand.
            </div>
          </div>
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th className="l">Date</th>
                <th className="l">Symbol</th>
                <th className="l">Side</th>
                <th className="r">Qty</th>
                <th className="r">Price</th>
                <th className="l">Source</th>
                <th className="r sticky right-0" />
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} className={editing === t.id ? "bg-raise" : undefined}>
                  <td className="l text-dim">{t.traded_at.slice(0, 10)}</td>
                  <td className="l text-cyan" title={t.name || undefined}>{ticker(t.symbol)}</td>
                  <td className={`l ${t.side === "BUY" ? "text-up" : "text-down"}`}>{t.side}</td>
                  <td className="r">{num(t.quantity, Number.isInteger(t.quantity) ? 0 : 2)}</td>
                  <td className="r">{num(t.price)}</td>
                  <td className="l text-dim">{t.broker}</td>
                  <td className="r sticky right-0 bg-panel">
                    {confirming === t.id ? (
                      <span className="text-[10px]">
                        <span className="mr-2 text-dim">Remove?</span>
                        <button className="mr-2 text-down hover:underline"
                                onClick={() => { setConfirming(null); removeTrade(t.id); }}>YES</button>
                        <button className="text-dim hover:text-ink" onClick={() => setConfirming(null)}>NO</button>
                      </span>
                    ) : (
                      <span className="text-[10px]">
                        <button className="mr-3 text-dim hover:text-amber" aria-label={`Edit trade ${t.id}`}
                                onClick={() => setEditing(t.id)}>EDIT</button>
                        <button className="text-dim hover:text-down" aria-label={`Remove trade ${t.id}`}
                                onClick={() => setConfirming(t.id)}>REMOVE</button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
