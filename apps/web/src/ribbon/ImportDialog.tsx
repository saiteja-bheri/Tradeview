import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { EverythingPreview, EverythingSheet, ImportFormats, ImportPreview } from "../api/types";
import { useStore } from "../state/store";

const BROKER_NAME: Record<string, string> = {
  upstox: "Upstox trade book", zerodha: "Zerodha Console tradebook", groww: "Groww order report",
  export: "This app's own trade export", generic: "A trade file in your own layout",
};
const btn = "border px-3 py-1 disabled:opacity-40";
const loud = `${btn} border-amber text-amber hover:bg-amber hover:text-black disabled:hover:bg-transparent disabled:hover:text-amber`;
const quiet = `${btn} border-line text-dim hover:border-amber hover:text-ink`;
const HOLDS: Record<string, string> = {
  trades: "Stocks, ETFs, mutual funds, commodities (trades)",
  bonds: "Bonds (terms, and holdings when Quantity is given)",
  wealth: "FD, RD, PPF, EPF, NPS, pension, cash, insurance",
  mixed: "Every row goes where its Instrument type says",
  skip: "Not imported",
};

/** What the user says the file is. "auto" lets the app decide from the headings. */
type Kind = "auto" | "broker" | "holdings";
/** How the chosen file is being read. */
type Flow = "trades" | "holdings";
type BrokerChoice = "auto" | "zerodha" | "groww" | "upstox";

const KINDS: { id: Kind; title: string; text: string }[] = [
  { id: "auto", title: "LET THE APP DECIDE", text: "Reads the headings: a broker report goes to trades, a holdings file is split by Instrument type." },
  { id: "broker", title: "BROKER TRADE REPORT", text: "Zerodha, Groww or Upstox tradebook as downloaded, or any list of buys and sells." },
  { id: "holdings", title: "MY HOLDINGS FILE", text: "Stocks, funds, gold, bonds, FD, RD, PPF, EPF, NPS, pension, insurance, cash: one row each, with an Instrument type." },
];

async function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** True when the file is more than one trade list: an Instrument type column, several sheets, bonds or wealth. */
function isEverything(wb: EverythingPreview | null): boolean {
  if (!wb) return false;
  const used = wb.sheets.filter((s) => s.kind !== "skip");
  return used.some((s) => s.kind !== "trades") || used.length > 1;
}

function holds(s: EverythingSheet): string {
  if (s.kind !== "mixed" || !s.routes) return HOLDS[s.kind];
  return "By Instrument type: " + Object.entries(s.routes).map(([to, n]) => `${n} → ${to.toLowerCase()}`).join(", ");
}

/** Import: first what kind of file it is and what it must contain, then what was found in it. */
export function ImportDialog() {
  const open = useStore((s) => s.importOpen);
  const setOpen = useStore((s) => s.setImportOpen);
  const importCsv = useStore((s) => s.importCsv);
  const importEverything = useStore((s) => s.importEverything);
  const [kind, setKind] = useState<Kind>("auto");
  const [brokerChoice, setBrokerChoice] = useState<BrokerChoice>("auto");
  const [flow, setFlow] = useState<Flow | null>(null);
  const [wb, setWb] = useState<EverythingPreview | null>(null);
  const [wbError, setWbError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [formats, setFormats] = useState<ImportFormats | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setFile(null);
    setFlow(null);
    setPreview(null);
    setPreviewError(null);
    setWb(null);
    setWbError(null);
    setSkipped([]);
    setError(null);
  };

  useEffect(() => {
    if (!open) return;
    reset();
    if (!formats) api.importFormats().then(setFormats).catch((e) => setError((e as Error).message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen, formats]);

  if (!open) return null;

  const choose = async (f: File) => {
    reset();
    setFile(f);
    setBusy(true);
    const [all, trades] = await Promise.all([
      api.everythingPreview(f).catch((e: Error) => e),
      api.importPreview(f).catch((e: Error) => e),
    ]);
    const okAll = all instanceof Error ? null : all;
    const okTrades = trades instanceof Error ? null : trades;
    setWb(okAll);
    setWbError(all instanceof Error ? all.message : null);
    setPreview(okTrades);
    setPreviewError(trades instanceof Error ? trades.message : null);
    if (okTrades) setMapping(okTrades.mapping);
    // Your choice wins; "let the app decide" goes by the headings.
    let next: Flow;
    if (kind === "broker") next = "trades";
    else if (kind === "holdings") next = "holdings";
    else if (okAll?.broker) next = "trades";
    else if (isEverything(okAll)) next = "holdings";
    else next = okTrades ? "trades" : "holdings";
    setFlow(next);
    setBusy(false);
  };

  const template = async () => save(await api.importTemplate(), "trades-template.csv");
  const everythingTemplate = async () => save(await api.everythingTemplate(), "holdings-template.xlsx");
  const usable = (wb?.sheets ?? []).filter((s) => s.kind !== "skip" && !(s.missing ?? []).length);
  const wbBlocked = (wb?.sheets ?? []).filter((s) => s.kind !== "skip" && (s.missing ?? []).length > 0);

  const doImportEverything = async () => {
    if (!file) return;
    setBusy(true);
    const left = await importEverything(file);
    setBusy(false);
    if (useStore.getState().error) setError(useStore.getState().error);
    else if (left.length) setSkipped(left);          // stay open so the skipped rows can be read
    else setOpen(false);
  };

  const generic = preview?.broker === "generic" && brokerChoice === "auto";
  const missing = preview && generic
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
    const forced = kind === "broker" && brokerChoice !== "auto" ? brokerChoice : undefined;
    await importCsv(file, generic ? mapping : undefined, generic ? preview?.header_row : undefined, forced);
    setBusy(false);
    if (!useStore.getState().error) setOpen(false);
    else setError(useStore.getState().error);
  };

  const detected = wb?.broker
    ? `a broker trade report (${BROKER_NAME[wb.broker] ?? wb.broker})`
    : isEverything(wb)
      ? (wb?.sheets.some((s) => s.kind === "mixed") ? "your holdings file (Instrument type column)" : "your holdings workbook")
      : preview ? "a list of trades" : "nothing it can read";
  const guide = formats?.everything;

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 pt-12"
         onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="import-title"
           className="flex max-h-[88vh] w-[900px] max-w-[95vw] flex-col border border-amber bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 id="import-title" className="tracking-widest text-amber">IMPORT · CSV OR EXCEL</h2>
          <button onClick={() => setOpen(false)} aria-label="Close" className="text-dim hover:text-ink">✕</button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {!flow && formats && (
            <div className="space-y-4">
              <section>
                <h3 id="import-kind" className="mb-1.5 text-[10px] tracking-widest text-ink">WHAT ARE YOU UPLOADING?</h3>
                <div role="radiogroup" aria-labelledby="import-kind" className="grid gap-2 sm:grid-cols-3">
                  {KINDS.map((k) => (
                    <button key={k.id} role="radio" aria-checked={kind === k.id} onClick={() => setKind(k.id)}
                            className={`border p-2 text-left ${kind === k.id ? "border-amber bg-amber/10" : "border-line hover:border-amber/60"}`}>
                      <div className={`text-[10px] tracking-widest ${kind === k.id ? "text-amber" : "text-ink"}`}>
                        {kind === k.id ? "● " : "○ "}{k.title}
                      </div>
                      <div className="mt-1 text-[10.5px] leading-snug text-dim">{k.text}</div>
                    </button>
                  ))}
                </div>
                {kind === "broker" && (
                  <label className="mt-2 flex items-center gap-2 text-[11px] text-dim">
                    Broker
                    <select value={brokerChoice} onChange={(e) => setBrokerChoice(e.target.value as BrokerChoice)}
                            className="border border-line bg-bg px-1 py-0.5 text-ink outline-none focus:border-amber">
                      <option value="auto">Recognise from the headings</option>
                      <option value="zerodha">Zerodha Console tradebook</option>
                      <option value="groww">Groww order report</option>
                      <option value="upstox">Upstox trade book</option>
                    </select>
                  </label>
                )}
              </section>

              {kind !== "broker" && guide && (
                <section className="border border-amber/60 p-2.5">
                  <h3 className="mb-1 text-[10px] tracking-widest text-amber">HOLDINGS FILE · THE INSTRUMENT TYPE COLUMN</h3>
                  <p className="text-[11px] leading-relaxed text-dim">
                    Add a column headed <span className="font-semibold text-ink">Instrument type</span> and say on every
                    row what it is. That is how the app tells an FD from a stock, or EPF from NPS: each row goes to
                    trades, bonds or wealth by its type, so one sheet can hold everything.
                  </p>
                  <div className="mt-2 overflow-x-auto">
                    <table className="grid-table">
                      <thead><tr><th className="l">Instrument type</th><th className="l">Goes to</th><th className="l">Columns it uses</th><th className="l">Also accepted</th></tr></thead>
                      <tbody>
                        {guide.types.map((t) => (
                          <tr key={t.type}>
                            <td className="l font-semibold text-cyan">{t.type}</td>
                            <td className="l text-dim">{t.goes_to}</td>
                            <td className="l text-[10.5px]">{t.uses}</td>
                            <td className="l text-[10px] text-dim">{t.also.join(", ")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-2 text-[10.5px] text-dim">
                    <span className="text-ink">Columns: </span>
                    {guide.columns.map((c, i) => (
                      <span key={c.heading} title={c.format}>
                        <span className={c.required ? "text-amber" : "text-ink"}>{c.heading}</span>{i < guide.columns.length - 1 ? " · " : ""}
                      </span>
                    ))}
                  </div>
                  <ul className="mt-1.5 list-disc pl-4 text-[10.5px] text-dim">
                    {guide.notes.map((n) => <li key={n}>{n}</li>)}
                  </ul>
                  <button onClick={everythingTemplate} className={`${quiet} mt-2`}>DOWNLOAD HOLDINGS TEMPLATE (.XLSX)</button>
                </section>
              )}

              {kind !== "holdings" && (
                <>
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
                  <section>
                    <h3 className="mb-1.5 text-[10px] tracking-widest text-ink">ANY OTHER TRADE FILE · HEADINGS</h3>
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
                </>
              )}
            </div>
          )}

          {flow && (
            <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border border-line px-2.5 py-2 text-[11px]">
              <span className="text-ink">{file?.name}</span>
              <span className="text-dim">App found {detected}.</span>
              <span className="ml-auto text-[10px] tracking-widest text-dim">READ AS</span>
              <div role="radiogroup" aria-label="Read the file as" className="flex">
                {([["trades", "BROKER / TRADE REPORT"], ["holdings", "MY HOLDINGS FILE"]] as const).map(([id, label]) => (
                  <button key={id} role="radio" aria-checked={flow === id} onClick={() => { setFlow(id); setError(null); }}
                          className={`-ml-px border px-2 py-0.5 text-[10px] tracking-widest first:ml-0 ${flow === id ? "relative z-10 border-amber bg-amber text-black" : "border-line text-dim hover:text-ink"}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {flow === "holdings" && !wb && (
            <p role="alert" className="text-down">Could not read it as a holdings file: {wbError}</p>
          )}
          {flow === "holdings" && wb && (
            <div className="space-y-3">
              {wb.broker && (
                <p className="text-[11px] text-amber">
                  This looks like a {BROKER_NAME[wb.broker] ?? "broker report"}. Its rows will be read as trades either way.
                </p>
              )}
              <div className="overflow-x-auto">
                <table className="grid-table">
                  <thead><tr><th className="l">Sheet</th><th className="l">Holds</th><th className="r">Rows</th><th className="l">Columns found</th></tr></thead>
                  <tbody>
                    {wb.sheets.map((s) => {
                      const found = Object.entries(s.mapping ?? {}).filter(([, v]) => v).map(([, v]) => v);
                      const miss = s.missing ?? [];
                      return (
                        <tr key={s.sheet || "file"}>
                          <td className="l text-ink">{s.sheet || file?.name}</td>
                          <td className={`l ${s.kind === "skip" ? "text-dim" : "text-cyan"}`}>
                            {holds(s)}
                            {s.default_exchange && <span className="text-dim"> · blank Exchange = {s.default_exchange}</span>}
                            {s.kind === "skip" && s.reason && <span className="text-dim"> ({s.reason})</span>}
                          </td>
                          <td className="r tabular-nums">{s.kind === "skip" ? "" : s.rows}</td>
                          <td className="l text-[10.5px]">
                            {miss.length > 0
                              ? <span className="text-down">Missing: {miss.join(", ")}. Rename a heading in the file and choose it again.</span>
                              : <span className="text-dim">{found.join(", ")}</span>}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {!wb.sheets.some((s) => s.kind === "mixed") && (
                <p className="text-[10.5px] text-dim">
                  Tip: add an <span className="text-ink">Instrument type</span> column (Stock, Mutual fund, Gold, Bond,
                  FD, PPF, EPF, NPS…) so every row is placed exactly.
                </p>
              )}
              {skipped.length > 0 && (
                <div className="border border-amber/60 p-2 text-[10.5px]">
                  <div className="text-amber">Imported. These rows were skipped:</div>
                  <ul className="mt-1 max-h-40 list-disc overflow-auto pl-4 text-dim">
                    {skipped.map((s) => <li key={s}>{s}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}

          {flow === "trades" && !preview && (
            <p role="alert" className="text-down">
              Could not read it as a trade report: {previewError}. If it lists FDs, pension or other holdings, read it
              as MY HOLDINGS FILE.
            </p>
          )}
          {flow === "trades" && preview && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-baseline gap-x-3 text-[11px]">
                <span className="text-dim">Read as</span>
                <span className="text-amber">
                  {kind === "broker" && brokerChoice !== "auto"
                    ? `${BROKER_NAME[brokerChoice]} (your choice)`
                    : BROKER_NAME[preview.broker] ?? preview.broker}
                </span>
                <span className="text-dim">· headings on row {preview.header_row + 1}</span>
              </div>
              {wb && isEverything(wb) && !wb.broker && (
                <p className="text-[11px] text-amber">
                  This file also has holdings (bonds, deposits, pension or an Instrument type column). Read it as MY
                  HOLDINGS FILE to import those too.
                </p>
              )}

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
            {!flow ? (
              kind !== "holdings" && <button onClick={template} className={quiet}>DOWNLOAD TRADES TEMPLATE (.CSV)</button>
            ) : (
              <button onClick={reset} className={quiet}>BACK</button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {flow === "trades" && missing.length > 0 && (
              <span className="text-[11px] text-down">Choose a column for {missing.map((m) => m.label).join(", ")}</span>
            )}
            {flow === "holdings" && wbBlocked.length > 0 && (
              <span className="text-[11px] text-down">Sheets with missing columns are left out</span>
            )}
            <button onClick={() => fileRef.current?.click()} disabled={busy} className={flow ? quiet : loud}>
              {busy ? "READING…" : flow ? "CHOOSE ANOTHER FILE" : "CHOOSE FILE"}
            </button>
            {flow === "holdings" && wb && !skipped.length && (
              <button onClick={doImportEverything} disabled={busy || !usable.length} className={loud}>
                {busy ? "IMPORTING…" : "IMPORT ALL"}
              </button>
            )}
            {flow === "holdings" && skipped.length > 0 && (
              <button onClick={() => setOpen(false)} className={loud}>DONE</button>
            )}
            {flow === "trades" && preview && (
              <button onClick={doImport} disabled={busy || missing.length > 0} className={loud}>
                {busy ? "IMPORTING…" : "IMPORT TRADES"}
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
