import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { CorporateAction } from "../api/types";
import { num, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty, Seg } from "../ui";

const SOURCE: Record<string, string> = { yfinance: "Yahoo", bse: "BSE", manual: "Manual", coupon: "Coupon" };
type Kind = "split" | "bonus" | "dividend" | "demerger";
const KINDS: { value: Kind; label: string }[] = [
  { value: "split", label: "SPLIT" }, { value: "bonus", label: "BONUS" },
  { value: "dividend", label: "DIVIDEND" }, { value: "demerger", label: "DEMERGER" },
];
const field = "rounded-md border border-line bg-bg px-2 py-1 text-ink outline-none placeholder:text-dim/60 focus:border-accent";
const small = `${field} w-16 text-right`;

function today(): string {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function typeLabel(a: CorporateAction): string {
  if (a.source === "coupon") return "COUPON";
  if (a.kind === "demerger") return `DEMERGER → ${ticker(a.target ?? "")}`;
  if (a.kind === "rename") return `RENAMED → ${ticker(a.target ?? "")}`;
  return a.kind.toUpperCase();
}

function valueLabel(a: CorporateAction): string {
  if (a.kind === "dividend") return `₹${num(a.value)}`;
  if (a.kind === "demerger") return `×${num(a.value, 4).replace(/\.?0+$/, "")} · ${num((a.cost_share ?? 0) * 100)}% of cost`;
  if (a.kind === "rename") return "same holding";
  return `×${num(a.value, 4).replace(/\.?0+$/, "")}`;
}

/** Records a split, bonus, dividend or demerger the price sources missed. Bookkeeping only. */
function ActionForm({ symbols, onDone }: { symbols: string[]; onDone: (msg: string) => void }) {
  const reload = useStore((s) => s.reload);
  const holdings = useStore((s) => s.portfolio?.holdings ?? []);
  const [kind, setKind] = useState<Kind>("split");
  const [symbol, setSymbol] = useState(symbols[0] ? ticker(symbols[0]) : "");
  const [exDate, setExDate] = useState(today());
  const [a, setA] = useState("1");          // split: old shares · bonus/demerger: shares held
  const [b, setB] = useState("2");          // split: new shares · bonus: bonus shares · demerger: new-company shares
  const [dividend, setDividend] = useState("");
  const [newSymbol, setNewSymbol] = useState("");
  const [newName, setNewName] = useState("");
  const [costPct, setCostPct] = useState("");
  const [continuesAs, setContinuesAs] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const pick = (k: Kind) => {
    setKind(k);
    setProblem(null);
    if (k === "split") { setA("1"); setB("2"); }
    if (k === "bonus" || k === "demerger") { setA("1"); setB("1"); }
  };

  const na = Number(a), nb = Number(b);
  const ratioOk = na > 0 && nb > 0;
  const multiplier = kind === "split" ? nb / na : kind === "bonus" ? (na + nb) / na : nb / na;
  const sym = symbol.trim().toUpperCase();
  const held = holdings.find((h) => ticker(h.symbol) === ticker(sym) || h.symbol === sym)?.quantity;

  const preview = !ratioOk ? "" :
    kind === "split" ? `Each share becomes ${num(multiplier, 4).replace(/\.?0+$/, "")}; cost per share ÷ ${num(multiplier, 4).replace(/\.?0+$/, "")}.`
    : kind === "bonus" ? `Shares × ${num(multiplier, 4).replace(/\.?0+$/, "")}; total cost unchanged.`
    : kind === "demerger" && Number(costPct) > 0 ? `${held != null ? `${num(held, 0)} shares held → ${num(held * multiplier, 2)} ${newSymbol.toUpperCase() || "new"} shares; ` : ""}${costPct}% of your cost moves to them.`
    : "";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sym) return setProblem("Enter the stock.");
    setProblem(null);
    setBusy(true);
    try {
      if (kind === "demerger") {
        if (!newSymbol.trim()) throw new Error("Enter the new company's ticker.");
        const pct = Number(costPct);
        if (!(pct > 0 && pct < 100)) throw new Error("The share of cost must be between 0 and 100%.");
        if (!ratioOk) throw new Error("Enter how many new shares you get for how many held.");
        await api.addDemerger({ symbol: sym, ex_date: exDate, new_symbol: newSymbol.trim(), new_name: newName.trim() || undefined,
                                new_shares_per_share: multiplier, cost_to_new_pct: pct,
                                continues_as: continuesAs.trim() || undefined });
      } else if (kind === "dividend") {
        const v = Number(dividend);
        if (!(v > 0)) throw new Error("Enter the dividend per share.");
        await api.addAction({ symbol: sym.includes(".") ? sym : `${sym}.NS`, ex_date: exDate, kind, value: v });
      } else {
        if (!ratioOk) throw new Error("Enter both numbers of the ratio.");
        if (!(multiplier > 0) || multiplier === 1) throw new Error("That ratio changes nothing.");
        await api.addAction({ symbol: sym.includes(".") ? sym : `${sym}.NS`, ex_date: exDate, kind, value: multiplier });
      }
      await reload(true);
      onDone(`${kind === "demerger" ? "Demerger" : kind[0].toUpperCase() + kind.slice(1)} recorded for ${ticker(sym)}`);
    } catch (err) {
      setProblem((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-2 border-b border-line bg-raise/40 p-3 text-[11.5px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Seg<Kind> label="Type" hideLabel value={kind} options={KINDS} onChange={pick} />
        <span className="text-[10.5px] text-dim">Recorded in your ledger only. Nothing is sent to a broker.</span>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label>
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">STOCK</span>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} list="qt-action-symbols" spellCheck={false}
                 placeholder="e.g. TATAMOTORS" className={`${field} w-36 uppercase`} />
          <datalist id="qt-action-symbols">{symbols.map((s) => <option key={s} value={ticker(s)} />)}</datalist>
        </label>
        <label>
          <span className="mb-0.5 block text-[10px] tracking-widest text-dim">EX-DATE</span>
          <input type="date" value={exDate} max={today()} onChange={(e) => setExDate(e.target.value)} className={field} />
        </label>

        {kind === "split" && (
          <div className="flex items-center gap-1.5 pb-1">
            <input value={a} onChange={(e) => setA(e.target.value)} inputMode="decimal" aria-label="Old shares" className={small} />
            <span className="text-dim">share(s) become</span>
            <input value={b} onChange={(e) => setB(e.target.value)} inputMode="decimal" aria-label="New shares" className={small} />
            <span className="text-dim">shares</span>
          </div>
        )}
        {kind === "bonus" && (
          <div className="flex items-center gap-1.5 pb-1">
            <input value={b} onChange={(e) => setB(e.target.value)} inputMode="decimal" aria-label="Bonus shares" className={small} />
            <span className="text-dim">bonus share(s) for every</span>
            <input value={a} onChange={(e) => setA(e.target.value)} inputMode="decimal" aria-label="Shares held" className={small} />
            <span className="text-dim">held</span>
          </div>
        )}
        {kind === "dividend" && (
          <label>
            <span className="mb-0.5 block text-[10px] tracking-widest text-dim">₹ PER SHARE</span>
            <input value={dividend} onChange={(e) => setDividend(e.target.value)} inputMode="decimal" placeholder="0.00"
                   className={`${field} w-24 text-right`} />
          </label>
        )}
      </div>

      {kind === "demerger" && (
        <div className="flex flex-wrap items-end gap-3">
          <label>
            <span className="mb-0.5 block text-[10px] tracking-widest text-dim">NEW COMPANY</span>
            <input value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)} spellCheck={false} placeholder="e.g. TMCV"
                   className={`${field} w-28 uppercase`} />
          </label>
          <label>
            <span className="mb-0.5 block text-[10px] tracking-widest text-dim">ITS NAME (OPTIONAL)</span>
            <input value={newName} onChange={(e) => setNewName(e.target.value)} className={`${field} w-44`} />
          </label>
          <div className="flex items-center gap-1.5 pb-1">
            <input value={b} onChange={(e) => setB(e.target.value)} inputMode="decimal" aria-label="New-company shares" className={small} />
            <span className="text-dim">new share(s) for every</span>
            <input value={a} onChange={(e) => setA(e.target.value)} inputMode="decimal" aria-label="Shares held" className={small} />
            <span className="text-dim">held</span>
          </div>
          <label title="From the company's cost-of-acquisition notice, e.g. 31.65 for TMCV">
            <span className="mb-0.5 block text-[10px] tracking-widest text-dim">% OF COST TO NEW COMPANY</span>
            <input value={costPct} onChange={(e) => setCostPct(e.target.value)} inputMode="decimal" placeholder="e.g. 31.65"
                   className={`${field} w-24 text-right`} />
          </label>
          <label title="If the original company now trades under a different ticker (Tata Motors → TMPV)">
            <span className="mb-0.5 block text-[10px] tracking-widest text-dim">ORIGINAL NOW TRADES AS (OPTIONAL)</span>
            <input value={continuesAs} onChange={(e) => setContinuesAs(e.target.value)} spellCheck={false} placeholder="e.g. TMPV"
                   className={`${field} w-28 uppercase`} />
          </label>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy}
                className="rounded-md border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-black disabled:opacity-40">
          {busy ? "SAVING…" : "ADD"}
        </button>
        <button type="button" onClick={() => onDone("")}
                className="rounded-md border border-line px-3 py-1 text-dim hover:text-ink">CANCEL</button>
        {preview && <span className="text-dim">{preview}</span>}
        {problem && <span role="alert" className="text-down">{problem}</span>}
      </div>
    </form>
  );
}

export function ActionsPane() {
  const actions = useStore((s) => s.actions);
  const trades = useStore((s) => s.trades);
  const holdings = useStore((s) => s.portfolio?.holdings);
  const reload = useStore((s) => s.reload);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);
  const symbols = useMemo(
    () => [...new Set([...(holdings ?? []).map((h) => h.symbol), ...trades.map((t) => t.symbol)])].sort(),
    [holdings, trades]);

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

  const remove = async (a: CorporateAction) => {
    setConfirming(null);
    try {
      await api.removeAction(a.id);
      setNote({ text: `Removed the ${a.kind} for ${ticker(a.symbol)}` });
      await reload(true);
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-line px-3 py-1.5">
        <button onClick={() => setAdding((v) => !v)}
                title="Record a split, bonus issue, dividend or demerger"
                className="rounded-md border border-accent px-2 py-0.5 text-[11px] text-accent hover:bg-accent hover:text-black">
          + ADD
        </button>
        <button onClick={syncBse} disabled={busy}
                title="Pull dividends, bonus issues and splits for your stocks from BSE (experimental)"
                className="rounded-md border border-line px-2 py-0.5 text-[11px] text-dim hover:border-accent hover:text-ink disabled:opacity-40">
          {busy ? "SYNCING…" : "SYNC FROM BSE"}
        </button>
        {note && <span role="status" className={`text-[11px] ${note.bad ? "text-down" : "text-dim"}`}>{note.text}</span>}
      </div>
      {adding && <ActionForm symbols={symbols} onDone={(msg) => { setAdding(false); if (msg) setNote({ text: msg }); }} />}
      <div className="min-h-0 flex-1 overflow-auto">
        {!actions.length ? (
          <Empty title="No corporate actions"
                 hint="Splits, bonuses, dividends and bond coupons appear here after prices are refreshed. + ADD records one yourself, including a demerger." />
        ) : (
          <table className="grid-table">
            <thead>
              <tr>
                <th className="l">Ex-date</th>
                <th className="l">Symbol</th>
                <th className="l">Type</th>
                <th className="r">Value</th>
                <th className="l">Source</th>
                <th className="r" />
              </tr>
            </thead>
            <tbody>
              {actions.map((a) => (
                <tr key={a.id}>
                  <td className="l text-dim">{a.ex_date}</td>
                  <td className="l text-cyan">{ticker(a.symbol)}</td>
                  <td className={`l ${a.kind === "dividend" ? "text-ink" : "text-accent"}`}>{typeLabel(a)}</td>
                  <td className="r">{valueLabel(a)}</td>
                  <td className="l text-dim">{SOURCE[a.source] ?? a.source}</td>
                  <td className="r text-[10px]">
                    {a.source === "manual" && a.kind !== "rename" && (confirming === a.id ? (
                      <span>
                        <button className="mr-2 text-down hover:underline" onClick={() => remove(a)}>YES</button>
                        <button className="text-dim hover:text-ink" onClick={() => setConfirming(null)}>NO</button>
                      </span>
                    ) : (
                      <button className="text-dim hover:text-down" onClick={() => setConfirming(a.id)}
                              title={a.kind === "demerger" ? "Removes the demerger and its rename" : undefined}>
                        REMOVE
                      </button>
                    ))}
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
