import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PortfolioCash, WealthInput, WealthItemRow, WealthKind, WealthOverview } from "../api/types";
import { inr, num, pct, ticker } from "../format";
import { useStore } from "../state/store";
import { Empty } from "../ui";

const GROUP_COLOR: Record<string, string> = {
  Equity: "var(--color-cyan)", "Mutual funds": "#6aa8ff", Gold: "var(--color-amber)", Commodities: "#c98a3b",
  Bonds: "#9b8cff", Cash: "var(--color-up)", Deposits: "#5fd3a8", Retirement: "#e07bd0", Insurance: "#ff8f6b",
};

// Which fields each kind needs, so the form only asks for what matters.
const FIELDS: Record<WealthKind, { amount: string; rate?: boolean; dates?: boolean; monthly?: boolean; cover?: boolean }> = {
  cash: { amount: "Balance" },
  fixed_deposit: { amount: "Principal", rate: true, dates: true },
  recurring_deposit: { amount: "Balance so far", rate: true, dates: true, monthly: true },
  ppf: { amount: "Balance", rate: true, monthly: true, dates: true },
  epf: { amount: "Balance", rate: true, monthly: true },
  nps: { amount: "Fund value", rate: true, monthly: true },
  pension: { amount: "Fund value", rate: true, monthly: true },
  life_insurance: { amount: "Fund / surrender value", rate: true, dates: true, cover: true },
  term_insurance: { amount: "", dates: true, cover: true },
};

const blank = (kind: WealthKind): WealthInput => ({
  kind, name: "", institution: "", amount: 0, rate: 0, start_date: null, maturity_date: null,
  monthly_contribution: 0, cover: 0, premium: 0, notes: "",
});

const field = "w-full border border-line bg-bg px-2 py-1 text-ink outline-none placeholder:text-dim/60 focus:border-amber";

/** Net worth beyond the market portfolio: cash, deposits, pension and insurance. */
export function WealthPane() {
  const reload = useStore((s) => s.reload);
  const [w, setW] = useState<WealthOverview | null>(null);
  const [form, setForm] = useState<(WealthInput & { id?: number }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.wealth().then(setW).catch((e) => setError((e as Error).message));
  useEffect(() => {
    load();
  }, []);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      const { id, ...body } = form;
      if (id) await api.editWealth(id, body);
      else await api.addWealth(body);
      setForm(null);
      await load();
      reload(false);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    await api.deleteWealth(id);
    await load();
    reload(false);
  };

  if (!w) return error ? <Empty title="Could not load wealth" hint={error} /> : <Empty title="Loading…" />;
  const spec = form ? FIELDS[form.kind] : null;
  const set = (k: keyof WealthInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => f && ({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : (e.target.value || (k.endsWith("date") ? null : "")) }));

  return (
    <div className="flex h-full flex-col overflow-auto">
      <div className="border-b border-line px-3 py-3">
        <div className="text-[10px] tracking-widest text-dim">TOTAL NET WORTH</div>
        <div className="text-2xl font-semibold text-amber">{inr(w.net_worth)}</div>
        <div className="mt-0.5 text-[10.5px] text-dim">
          Market portfolio {inr(w.market_value)} · portfolio cash {inr(w.portfolio_cash)} · other assets {inr(w.other_assets - w.portfolio_cash)}
        </div>
        {w.net_worth > 0 && (
          <>
            <div className="mt-2 flex h-2.5 overflow-hidden" role="img" aria-label="Net worth by type">
              {w.groups.map((g) => (
                <div key={g.group} title={`${g.group} ${pct(g.weight, 1)}`}
                     style={{ width: `${(g.weight ?? 0) * 100}%`, background: GROUP_COLOR[g.group] ?? "var(--color-dim)" }} />
              ))}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10.5px]">
              {w.groups.map((g) => (
                <span key={g.group} className="flex items-center gap-1">
                  <i className="inline-block h-2 w-2" style={{ background: GROUP_COLOR[g.group] ?? "var(--color-dim)" }} />
                  {g.group} <span className="text-dim">{pct(g.weight, 1)}</span>
                </span>
              ))}
            </div>
          </>
        )}
      </div>

      <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] border-b border-line text-[10.5px]">
        <Tile label="CASH (NOW)" value={inr(w.liquidity.cash)} />
        <Tile label="MARKET (DAYS)" value={inr(w.liquidity.market)} />
        <Tile label="DEPOSITS (BREAKABLE)" value={inr(w.liquidity.deposits)} />
        <Tile label="LOCKED (PENSION, POLICIES)" value={inr(w.liquidity.locked)} />
        <Tile label="LIFE COVER" value={inr(w.protection.life_cover)} />
        <Tile label="PREMIUMS / YEAR" value={inr(w.protection.annual_premium)} />
        <Tile label="MONTHLY CONTRIBUTIONS" value={inr(w.monthly_contributions)} />
        <Tile label="MATURING IN 90 DAYS" value={String(w.maturing_within_90_days.length)} />
      </div>

      <PortfolioCashCard onChange={() => { load(); reload(false); }} />

      <div className="flex items-center justify-between px-3 pb-1 pt-2.5">
        <span className="text-[10px] tracking-widest text-dim">CASH, DEPOSITS, PENSION AND INSURANCE</span>
        <select value="" aria-label="Add an item" disabled={busy}
                onChange={(e) => e.target.value && setForm(blank(e.target.value as WealthKind))}
                className="border border-amber bg-bg px-1.5 py-0.5 text-[11px] text-amber outline-none">
          <option value="">+ ADD…</option>
          {w.kinds.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
        </select>
      </div>

      {form && spec && (
        <form onSubmit={save} className="mx-3 mb-2 grid grid-cols-2 gap-x-3 gap-y-2 border border-line p-2.5 sm:grid-cols-3">
          <div className="col-span-full text-[11px] text-amber">
            {form.id ? "Edit" : "Add"} {w.kinds.find((k) => k.kind === form.kind)?.label}
          </div>
          <Label text="NAME"><input value={form.name} onChange={set("name")} placeholder="e.g. Salary account" className={field} /></Label>
          <Label text="BANK / PROVIDER"><input value={form.institution} onChange={set("institution")} className={field} /></Label>
          {spec.amount && (
            <Label text={`${spec.amount.toUpperCase()} (₹)`}>
              <input type="number" min={0} step="any" value={form.amount || ""} onChange={set("amount")} className={`${field} text-right`} />
            </Label>
          )}
          {spec.rate && (
            <Label text={`RATE % / YEAR (blank = ${w.kinds.find((k) => k.kind === form.kind)?.rate}%)`}>
              <input type="number" min={0} step="0.01" value={form.rate || ""} onChange={set("rate")} className={`${field} text-right`} />
            </Label>
          )}
          {spec.monthly && (
            <Label text="MONTHLY CONTRIBUTION (₹)">
              <input type="number" min={0} step="any" value={form.monthly_contribution || ""} onChange={set("monthly_contribution")} className={`${field} text-right`} />
            </Label>
          )}
          {spec.cover && (
            <>
              <Label text="SUM ASSURED (₹)">
                <input type="number" min={0} step="any" value={form.cover || ""} onChange={set("cover")} className={`${field} text-right`} />
              </Label>
              <Label text="PREMIUM / YEAR (₹)">
                <input type="number" min={0} step="any" value={form.premium || ""} onChange={set("premium")} className={`${field} text-right`} />
              </Label>
            </>
          )}
          {spec.dates && (
            <>
              <Label text={form.kind === "fixed_deposit" ? "START DATE (required)" : "START DATE"}>
                <input type="date" value={form.start_date ?? ""} onChange={set("start_date")} className={field} />
              </Label>
              <Label text="MATURITY / END">
                <input type="date" value={form.maturity_date ?? ""} onChange={set("maturity_date")} className={field} />
              </Label>
            </>
          )}
          <div className="col-span-full flex gap-2">
            <button type="submit" disabled={busy} className="border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40">
              {form.id ? "SAVE" : "ADD"}
            </button>
            <button type="button" onClick={() => setForm(null)} className="border border-line px-3 py-1 text-dim hover:text-ink">CANCEL</button>
          </div>
        </form>
      )}
      {error && <div role="alert" className="px-3 pb-2 text-down">{error}</div>}

      {!w.items.length ? (
        <p className="px-3 pb-3 text-[11px] text-dim">
          Add your bank balances, FDs and RDs, PPF / EPF / NPS, pension and insurance policies to see your whole net worth.
          Values stay on this computer.
        </p>
      ) : (
        <table className="grid-table">
          <thead>
            <tr><th className="l">Item</th><th className="l">Type</th><th className="r">Value</th><th className="r">Rate</th>
              <th className="r">Monthly</th><th className="l">Note</th><th className="l" /></tr>
          </thead>
          <tbody>
            {w.items.map((it: WealthItemRow) => (
              <tr key={it.id}>
                <td className="l">{it.name || it.kind_label}<div className="text-[10px] text-dim">{it.institution}</div></td>
                <td className="l text-dim">{it.kind_label}</td>
                <td className="r tabular-nums">{it.kind === "term_insurance" ? "—" : inr(it.value)}</td>
                <td className="r text-dim">{it.effective_rate ? `${num(it.effective_rate)}%` : "—"}</td>
                <td className="r text-dim">{it.monthly_contribution ? inr(it.monthly_contribution) : "—"}</td>
                <td className="l text-[10.5px] text-dim">
                  {it.cover ? `cover ${inr(it.cover)} · ` : ""}
                  {it.matures_in_days != null ? (it.matures_in_days < 0 ? "matured" : `matures in ${it.matures_in_days}d`) : ""}
                </td>
                <td className="l whitespace-nowrap">
                  <button onClick={() => setForm({ ...it })} className="text-[10.5px] text-dim underline hover:text-ink">edit</button>
                  <button onClick={() => remove(it.id)} aria-label={`Delete ${it.name || it.kind_label}`}
                          className="ml-2 text-dim hover:text-down">✕</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-b border-r border-line px-3 py-2">
      <div className="break-words text-[9px] tracking-widest text-dim">{label}</div>
      <div className="tabular-nums">{value}</div>
    </div>
  );
}

function Label({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[9.5px] tracking-widest text-dim">{text}</span>
      {children}
    </label>
  );
}

const KIND_LABEL: Record<string, { text: string; cls: string }> = {
  dividend: { text: "DIVIDEND", cls: "text-up" }, sale: { text: "SALE", cls: "text-up" },
  purchase: { text: "PURCHASE", cls: "text-down" }, withdrawal: { text: "WITHDRAWN", cls: "text-amber" },
};

/** Cash held in the portfolio: dividends, coupons and sale proceeds stay here until a
 *  purchase uses them or a withdrawal is recorded. */
function PortfolioCashCard({ onChange }: { onChange: () => void }) {
  const [c, setC] = useState<PortfolioCash | null>(null);
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.portfolioCash().then(setC).catch(() => {});
  }, []);
  if (!c || !c.movements.length) return null;

  const withdraw = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      setC(await api.withdraw(date, Number(amount), note));
      setAmount("");
      setNote("");
      onChange();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const undo = async (id: number) => {
    setC(await api.deleteWithdrawal(id));
    onChange();
  };

  return (
    <div className="border-b border-line px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-[10px] tracking-widest text-dim">PORTFOLIO CASH</span>
        <span className="text-up tabular-nums">{inr(c.balance)}</span>
        <span className="text-[10.5px] text-dim">
          dividends {inr(c.dividends)} + sales {inr(c.sale_proceeds)} − used for purchases {inr(c.spent_from_cash)}
          {" "}− withdrawn {inr(c.withdrawn)}
        </span>
        <button onClick={() => setOpen(!open)} className="ml-auto text-[10.5px] text-dim underline hover:text-ink">
          {open ? "close" : "record a withdrawal / movements"}
        </button>
      </div>
      <p className="mt-0.5 text-[10px] text-dim">
        Dividends, coupons and sale proceeds stay here, counted in your net worth, until you record a withdrawal.
        Purchases are paid from this cash first; the rest is new money ({inr(c.new_money)} so far, {inr(c.money_in)} net
        of withdrawals).
      </p>
      {open && (
        <div className="mt-2 space-y-2">
          <form onSubmit={withdraw} className="flex flex-wrap items-end gap-2 text-[11px]">
            <label className="block"><span className="block text-[9.5px] tracking-widest text-dim">DATE</span>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className={field} /></label>
            <label className="block"><span className="block text-[9.5px] tracking-widest text-dim">AMOUNT ₹</span>
              <input type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)}
                     className={`${field} w-28 text-right`} /></label>
            <label className="block min-w-0 flex-1"><span className="block text-[9.5px] tracking-widest text-dim">NOTE</span>
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. moved to savings account" className={field} /></label>
            <button type="submit" disabled={!(Number(amount) > 0)}
                    className="border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40">
              RECORD WITHDRAWAL
            </button>
            <button type="button" onClick={() => setAmount(String(Math.round(c.balance * 100) / 100))}
                    className="border border-line px-2 py-1 text-dim hover:text-ink">ALL</button>
          </form>
          {error && <div role="alert" className="text-down">{error}</div>}
          <div>
            <div className="text-[9.5px] tracking-widest text-dim">MOVEMENTS (LATEST FIRST)</div>
            <div className="max-h-40 overflow-auto">
              <table className="grid-table">
                <thead><tr><th className="l">Date</th><th className="l">Type</th><th className="l">Stock / note</th>
                  <th className="r">Amount</th><th className="r" title="For purchases: how much the portfolio cash paid">From cash</th>
                  <th className="r">Cash after</th><th className="l" /></tr></thead>
                <tbody>
                  {c.movements.map((m, i) => (
                    <tr key={i}>
                      <td className="l text-dim">{m.date}</td>
                      <td className={`l text-[9.5px] tracking-widest ${KIND_LABEL[m.kind]?.cls}`}>{KIND_LABEL[m.kind]?.text}</td>
                      <td className="l max-w-[160px] truncate">{m.symbol ? ticker(m.symbol) : <span className="text-dim">{m.note}</span>}</td>
                      <td className="r tabular-nums">{inr(m.amount)}</td>
                      <td className="r tabular-nums text-dim">{m.kind === "purchase" ? inr(m.from_cash) : ""}</td>
                      <td className="r tabular-nums">{inr(m.cash)}</td>
                      <td className="l">
                        {m.kind === "withdrawal" && m.id != null && (
                          <button onClick={() => undo(m.id!)} aria-label="Remove this withdrawal"
                                  className="text-dim hover:text-down">✕</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
