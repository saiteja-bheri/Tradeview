import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { ImportFormats, ImportPreview } from "../api/types";
import { useStore } from "../state/store";

const BROKER_NAME: Record<string, string> = {
  upstox: "Upstox trade book", zerodha: "Zerodha Console tradebook", groww: "Groww order report", generic: "Your own layout",
};
const btn = "border px-3 py-1 disabled:opacity-40";
const loud = `${btn} border-amber text-amber hover:bg-amber hover:text-black disabled:hover:bg-transparent disabled:hover:text-amber`;
const quiet = `${btn} border-line text-dim hover:border-amber hover:text-ink`;

/** Import trades: first what the file must contain, then what was found in it,
 *  with a chance to point each field at the right column. */
export function ImportDialog() {
  const open = useStore((s) => s.importOpen);
  const setOpen = useStore((s) => s.setImportOpen);
  const importCsv = useStore((s) => s.importCsv);
  const [formats, setFormats] = useState<ImportFormats | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setPreview(null);
    setError(null);
    if (!formats) api.importFormats().then(setFormats).catch((e) => setError((e as Error).message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen, formats]);

  if (!open) return null;

  const choose = async (f: File) => {
    setFile(f);
    setBusy(true);
    setError(null);
    try {
      const p = await api.importPreview(f);
      setPreview(p);
      setMapping(p.mapping);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const template = async () => {
    const blob = await api.importTemplate();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "trades-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const generic = preview?.broker === "generic";
  const missing = preview
    ? preview.fields.filter((f) => f.required && !mapping[f.field]
        && !(f.field === "price" && mapping.amount) && !(f.field === "side" && mapping.quantity))
    : [];
  const sample = (heading: string | null) => {
    if (!preview || !heading) return "";
    const i = preview.headings.indexOf(heading);
    return i < 0 ? "" : preview.samples.map((r) => r[i]).filter(Boolean).slice(0, 2).join(", ");
  };

  const doImport = async () => {
    if (!file) return;
    setBusy(true);
    await importCsv(file, generic ? mapping : undefined, generic ? preview?.header_row : undefined);
    setBusy(false);
    if (!useStore.getState().error) setOpen(false);
    else setError(useStore.getState().error);
  };

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 pt-12"
         onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="import-title"
           className="flex max-h-[88vh] w-[860px] max-w-[95vw] flex-col border border-amber bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 id="import-title" className="tracking-widest text-amber">IMPORT TRADES · CSV OR EXCEL</h2>
          <button onClick={() => setOpen(false)} aria-label="Close" className="text-dim hover:text-ink">✕</button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {!preview && formats && (
            <div className="space-y-4">
              <p className="text-[11px] leading-relaxed text-dim">
                Upload a broker report as it comes (Upstox, Zerodha, Groww) or any file with the headings below.
                Columns can be in any order and extra columns are ignored. Headings are matched by name, including
                common variations (Qty, Units, Ticker, Rate, Buy/Sell…), and you can fix any that are not recognised
                on the next screen.
              </p>

              <section>
                <h3 className="mb-1.5 text-[10px] tracking-widest text-ink">ANY FILE · EXACT HEADINGS</h3>
                <div className="overflow-x-auto">
                  <table className="grid-table">
                    <thead><tr><th className="l">Heading</th><th className="l">Needed</th><th className="l">Format</th></tr></thead>
                    <tbody>
                      {formats.generic.headings.map((h) => (
                        <tr key={h.heading}>
                          <td className="l font-semibold text-cyan">{h.heading}</td>
                          <td className={`l ${h.required ? "text-amber" : "text-dim"}`}>{h.required ? "required" : "optional"}</td>
                          <td className="l text-dim">{h.format}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ul className="mt-1.5 list-disc pl-4 text-[10.5px] text-dim">
                  {formats.generic.notes.map((n) => <li key={n}>{n}</li>)}
                </ul>
              </section>

              <section>
                <h3 className="mb-1.5 text-[10px] tracking-widest text-ink">BROKER REPORTS · RECOGNISED AUTOMATICALLY</h3>
                <div className="grid gap-2 sm:grid-cols-3">
                  {Object.entries(formats.brokers).map(([id, b]) => (
                    <div key={id} className="border border-line p-2 text-[10.5px]">
                      <div className="text-ink">{b.label}</div>
                      <div className="text-dim">{b.where} · {b.file}</div>
                      <div className="mt-1"><span className="text-amber">Required: </span>{b.required.join(", ")}</div>
                      <div className="text-dim"><span>Optional: </span>{b.optional.join(", ")}</div>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          )}

          {preview && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-baseline gap-x-3 text-[11px]">
                <span className="text-ink">{file?.name}</span>
                <span className="text-dim">Recognised as</span>
                <span className="text-amber">{BROKER_NAME[preview.broker] ?? preview.broker}</span>
                <span className="text-dim">· headings on row {preview.header_row + 1}</span>
              </div>

              {generic ? (
                <>
                  <p className="text-[11px] text-dim">
                    Check that each field points at the right column. Fields marked * are required.
                  </p>
                  <div className="overflow-x-auto">
                    <table className="grid-table">
                      <thead><tr><th className="l">Field</th><th className="l">Column in your file</th><th className="l">First values</th><th className="l">Expected</th></tr></thead>
                      <tbody>
                        {preview.fields.map((f) => {
                          const bad = missing.some((m) => m.field === f.field);
                          return (
                            <tr key={f.field}>
                              <td className={`l ${bad ? "text-down" : "text-ink"}`}>{f.label}{f.required ? " *" : ""}</td>
                              <td className="l">
                                <select value={mapping[f.field] ?? ""} aria-label={`Column for ${f.label}`}
                                        onChange={(e) => setMapping((m) => ({ ...m, [f.field]: e.target.value || null }))}
                                        className={`border bg-bg px-1 py-0.5 text-ink outline-none focus:border-amber ${bad ? "border-down" : "border-line"}`}>
                                  <option value="">— not in file —</option>
                                  {preview.headings.filter(Boolean).map((h) => <option key={h} value={h}>{h}</option>)}
                                </select>
                              </td>
                              <td className="l max-w-[180px] truncate text-dim">{sample(mapping[f.field] ?? null)}</td>
                              <td className="l text-[10px] text-dim">{f.format}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="overflow-x-auto">
                  <table className="grid-table">
                    <thead><tr>{preview.headings.map((h, i) => <th key={i} className="l">{h}</th>)}</tr></thead>
                    <tbody>
                      {preview.samples.map((r, i) => (
                        <tr key={i}>{preview.headings.map((_, j) => <td key={j} className="l text-dim">{r[j]}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
          {error && <div role="alert" className="mt-3 text-down">{error}</div>}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5">
          <div className="flex gap-2">
            {!preview ? (
              <button onClick={template} className={quiet}>DOWNLOAD TEMPLATE</button>
            ) : (
              <button onClick={() => { setPreview(null); setFile(null); }} className={quiet}>BACK</button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {preview && missing.length > 0 && (
              <span className="text-[11px] text-down">Choose a column for {missing.map((m) => m.label).join(", ")}</span>
            )}
            <button onClick={() => fileRef.current?.click()} disabled={busy} className={preview ? quiet : loud}>
              {preview ? "CHOOSE ANOTHER FILE" : "CHOOSE FILE"}
            </button>
            {preview && (
              <button onClick={doImport} disabled={busy || missing.length > 0} className={loud}>
                {busy ? "IMPORTING…" : "IMPORT"}
              </button>
            )}
          </div>
          <input id="qt-import" ref={fileRef} type="file" className="hidden"
                 accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                 onChange={(e) => {
                   const f = e.target.files?.[0];
                   if (f) choose(f);
                   e.target.value = "";
                 }} />
        </div>
      </div>
    </div>
  );
}
