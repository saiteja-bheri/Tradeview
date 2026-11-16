import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Bond, BondInput } from "../api/types";
import { num } from "../format";
import { useStore } from "../state/store";

const field = "w-full border border-line bg-bg px-2 py-1 text-ink outline-none placeholder:text-dim/60 focus:border-amber";
const FREQ: { value: Bond["frequency"]; label: string }[] = [
  { value: 2, label: "Half-yearly" }, { value: 1, label: "Yearly" }, { value: 4, label: "Quarterly" },
  { value: 12, label: "Monthly" }, { value: 0, label: "Zero coupon" },
];

const blank = { id: "", name: "", isin: "", face_value: "1000", coupon_rate: "", frequency: 2 as Bond["frequency"],
                maturity: "", price: "" };

/** Terms of bonds tracked by hand. Coupons become income on their payment
 *  dates; buys and the redemption are recorded as trades on BOND:<ID>. */
export function BondsDialog() {
  const open = useStore((s) => s.bondsOpen);
  const setOpen = useStore((s) => s.setBondsOpen);
  const reload = useStore((s) => s.reload);
  const [bonds, setBonds] = useState<Bond[]>([]);
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setNotice(null);
    api.bonds().then(setBonds).catch((e) => setError((e as Error).message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  if (!open) return null;

  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: k === "frequency" ? Number(e.target.value) : e.target.value }));

  const edit = (b: Bond) => setForm({
    id: b.symbol.replace(/^BOND:/, ""), name: b.name, isin: b.isin, face_value: String(b.face_value),
    coupon_rate: String(b.coupon_rate), frequency: b.frequency, maturity: b.maturity, price: b.price ? String(b.price) : "",
  });

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const body: BondInput = {
        name: form.name.trim(), isin: form.isin.trim(), face_value: Number(form.face_value) || 1000,
        coupon_rate: Number(form.coupon_rate) || 0, frequency: form.frequency, maturity: form.maturity,
        price: Number(form.price) || 0,
      };
      const saved = await api.saveBond(form.id.trim(), body);
      setBonds(await api.bonds());
      setNotice(`Saved ${saved.symbol}. Record purchases as BUY trades on ${saved.symbol}.`);
      setForm(blank);
      await reload(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (symbol: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.deleteBond(symbol);
      setBonds(await api.bonds());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 pt-16"
         onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="bonds-title"
           className="flex max-h-[84vh] w-[720px] max-w-[94vw] flex-col border border-amber bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 id="bonds-title" className="tracking-widest text-amber">BONDS</h2>
          <button onClick={() => setOpen(false)} aria-label="Close" className="text-dim hover:text-ink">✕</button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <p className="mb-3 text-[11px] leading-relaxed text-dim">
            For G-secs, corporate bonds, NCDs and tax-free bonds. Each bond is valued at the price you set
            (face value if left blank) and its coupons are booked as income on their payment dates. Record what
            you bought as a BUY on <span className="text-ink">BOND:&lt;ID&gt;</span> and the redemption as a SELL at
            face value. Sovereign Gold Bonds trade on NSE: add them as stocks (for example SGBAUG28V).
          </p>

          {bonds.length > 0 && (
            <div className="mb-4 overflow-x-auto">
              <table className="grid-table">
                <thead>
                  <tr><th className="l">Bond</th><th className="r">Coupon</th><th className="l">Paid</th>
                    <th className="l">Maturity</th><th className="r">Price</th><th className="l" /></tr>
                </thead>
                <tbody>
                  {bonds.map((b) => (
                    <tr key={b.symbol}>
                      <td className="l text-cyan" title={b.isin || undefined}>
                        {b.symbol.replace(/^BOND:/, "")} <span className="text-dim">{b.name}</span>
                      </td>
                      <td className="r">{num(b.coupon_rate)}%</td>
                      <td className="l text-dim">{FREQ.find((f) => f.value === b.frequency)?.label}</td>
                      <td className="l">{b.maturity}</td>
                      <td className="r">{num(b.price || b.face_value)}</td>
                      <td className="l whitespace-nowrap">
                        <button onClick={() => edit(b)} className="text-[11px] text-dim underline hover:text-ink">edit</button>
                        <button onClick={() => remove(b.symbol)} disabled={busy}
                                className="ml-2 text-[11px] text-dim underline hover:text-down disabled:opacity-40">remove</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <form onSubmit={save} className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-4">
            <label className="col-span-1">
              <span className="text-[10px] tracking-widest text-dim">ID</span>
              <input value={form.id} onChange={set("id")} required placeholder="GOI2033" pattern="[A-Za-z0-9-]{1,30}"
                     className={field} spellCheck={false} />
            </label>
            <label className="col-span-1 sm:col-span-3">
              <span className="text-[10px] tracking-widest text-dim">NAME</span>
              <input value={form.name} onChange={set("name")} placeholder="7.18% GS 2033" className={field} />
            </label>
            <label>
              <span className="text-[10px] tracking-widest text-dim">COUPON % / YR</span>
              <input value={form.coupon_rate} onChange={set("coupon_rate")} inputMode="decimal" placeholder="7.18"
                     className={`${field} text-right`} />
            </label>
            <label>
              <span className="text-[10px] tracking-widest text-dim">PAID</span>
              <select value={form.frequency} onChange={set("frequency")} className={field}>
                {FREQ.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
              </select>
            </label>
            <label>
              <span className="text-[10px] tracking-widest text-dim">MATURITY</span>
              <input type="date" value={form.maturity} onChange={set("maturity")} required className={field} />
            </label>
            <label>
              <span className="text-[10px] tracking-widest text-dim">FACE VALUE</span>
              <input value={form.face_value} onChange={set("face_value")} inputMode="decimal" className={`${field} text-right`} />
            </label>
            <label>
              <span className="text-[10px] tracking-widest text-dim">PRICE NOW</span>
              <input value={form.price} onChange={set("price")} inputMode="decimal" placeholder="face value"
                     className={`${field} text-right`} />
            </label>
            <label className="sm:col-span-2">
              <span className="text-[10px] tracking-widest text-dim">ISIN (OPTIONAL)</span>
              <input value={form.isin} onChange={set("isin")} placeholder="IN0020230085" className={field} spellCheck={false} />
            </label>
            <div className="flex items-end">
              <button type="submit" disabled={busy || !form.id.trim() || !form.maturity}
                      className="w-full border border-amber px-3 py-1 text-amber hover:bg-amber hover:text-black disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-amber">
                SAVE BOND
              </button>
            </div>
          </form>
          {notice && <div role="status" className="mt-3 text-up">{notice}</div>}
          {error && <div role="alert" className="mt-3 text-down">{error}</div>}
        </div>
      </div>
    </div>
  );
}
