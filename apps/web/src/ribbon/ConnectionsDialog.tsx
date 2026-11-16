import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ConnectionsState, PriceSource, SourceId, SourceState, SyncResult } from "../api/types";
import { feedLabel } from "../format";
import { useStore } from "../state/store";

const PRICE_LABEL: Record<PriceSource, string> = {
  auto: "AUTO", upstox: "UPSTOX", zerodha: "ZERODHA", groww: "GROWW", bse: "BSE", yahoo: "YAHOO", off: "OFF",
};

const btn = "border px-2.5 py-1 disabled:opacity-40";
const quiet = `${btn} border-line text-dim hover:border-amber hover:text-ink`;
const loud = `${btn} border-amber text-amber hover:bg-amber hover:text-black disabled:hover:bg-transparent disabled:hover:text-amber`;
const field = "min-w-0 flex-1 border border-line bg-bg px-2 py-1.5 text-ink outline-none placeholder:text-dim/60 focus:border-amber disabled:opacity-50";

function stateOf(s: SourceState): { text: string; cls: string } {
  if (s.kind === "data") return { text: s.experimental ? "EXPERIMENTAL" : "BUILT IN", cls: "text-dim" };
  if (!s.configured) return { text: "NOT SET UP", cls: "text-dim" };
  if (s.session.needed && !s.session.active) return { text: "LOG IN TODAY", cls: "text-amber" };
  if (s.mismatches.length) return { text: `${s.mismatches.length} MISMATCH`, cls: "text-down" };
  return { text: "CONNECTED", cls: "text-up" };
}

/** Brokers and price sources. Credentials go straight to the engine, which keeps
 *  them in the system keychain; the UI only ever learns whether each one is set. */
export function ConnectionsDialog() {
  const open = useStore((s) => s.connectOpen);
  const setOpen = useStore((s) => s.setConnectOpen);
  const reload = useStore((s) => s.reload);
  const liveStatus = useStore((s) => s.live?.status);
  const [state, setState] = useState<ConnectionsState | null>(null);
  const [selected, setSelected] = useState<SourceId>("upstox");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setNotice(null);
    api.connections().then(setState).catch((e) => setError((e as Error).message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  if (!open) return null;

  const run = async (fn: () => Promise<ConnectionsState | void>, done?: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await fn();
      if (next) setState(next);
      if (done) setNotice(done);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const feed = liveStatus ?? state?.feed;
  const source = state?.sources.find((s) => s.id === selected);

  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/60 pt-16"
         onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="connect-title"
           className="flex max-h-[84vh] w-[780px] max-w-[94vw] flex-col border border-amber bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 id="connect-title" className="tracking-widest text-amber">CONNECTIONS</h2>
          <button onClick={() => setOpen(false)} aria-label="Close" className="text-dim hover:text-ink">✕</button>
        </div>

        <div className="space-y-2 border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="text-[10px] tracking-widest text-dim">LIVE PRICES FROM</span>
            <div role="radiogroup" aria-label="Live price source" className="flex flex-wrap">
              {(state?.price_sources ?? []).map((p) => (
                <button key={p} role="radio" aria-checked={state?.price_source === p}
                        disabled={busy || !!state?.env_override}
                        onClick={() => run(() => api.setPriceSource(p))}
                        className={`-ml-px border px-2 py-0.5 text-[11px] first:ml-0 disabled:opacity-50 ${
                          state?.price_source === p ? "relative z-10 border-amber bg-amber text-black"
                            : "border-line text-dim hover:text-ink"}`}>
                  {PRICE_LABEL[p]}
                </button>
              ))}
            </div>
          </div>
          <div className="text-[11px]">
            <span className={feed?.state === "error" ? "text-down" : feed?.state === "live" ? "text-up" : "text-amber"}>
              {feedLabel(feed)}
            </span>
            {feed?.detail ? <span className="text-dim"> · {feed.detail}</span> : null}
            {state?.env_override && (
              <span className="text-dim"> · fixed to {state.env_override.toUpperCase()} by the QT_FEED environment variable</span>
            )}
            {state?.price_source === "auto" && !state.env_override && (
              <span className="text-dim"> · AUTO uses Upstox when its token is saved, otherwise Yahoo</span>
            )}
          </div>
        </div>

        <div className="flex min-h-0 flex-1">
          <nav aria-label="Sources" className="w-44 shrink-0 overflow-y-auto border-r border-line py-1">
            {(state?.sources ?? []).map((s) => {
              const st = stateOf(s);
              return (
                <button key={s.id} onClick={() => { setSelected(s.id); setError(null); setNotice(null); }}
                        aria-current={selected === s.id}
                        className={`block w-full px-3 py-2 text-left ${selected === s.id ? "bg-raise" : "hover:bg-raise/60"}`}>
                  <div className={selected === s.id ? "text-amber" : "text-ink"}>{s.label.toUpperCase()}</div>
                  <div className={`text-[10px] tracking-widest ${st.cls}`}>{st.text}</div>
                </button>
              );
            })}
          </nav>

          <div className="min-w-0 flex-1 overflow-y-auto px-4 py-3">
            {source ? (
              <SourcePanel key={source.id} source={source} busy={busy} run={run}
                           onSynced={(r) => {
                             setNotice(syncNotice(r));
                             api.connections().then(setState).catch(() => {});
                             reload(false);
                           }}
                           setBusy={setBusy} setError={setError} />
            ) : (
              <div className="text-dim">{error ? "" : "…"}</div>
            )}
            {notice && <div role="status" className="mt-3 text-up">{notice}</div>}
            {error && <div role="alert" className="mt-3 text-down">{error}</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

function syncNotice(r: SyncResult): string {
  const parts = [`${r.holdings} holdings read`];
  if (r.imported) parts.push(`${r.imported} new trades added`);
  if (r.duplicates) parts.push(`${r.duplicates} already in ledger`);
  parts.push(r.mismatches.length ? `${r.mismatches.length} differ from the ledger` : "ledger matches");
  return parts.join(" · ");
}

function SourcePanel({ source, busy, run, onSynced, setBusy, setError }: {
  source: SourceState;
  busy: boolean;
  run: (fn: () => Promise<ConnectionsState | void>, done?: string) => Promise<void>;
  onSynced: (r: SyncResult) => void;
  setBusy: (b: boolean) => void;
  setError: (e: string | null) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [paste, setPaste] = useState("");
  const anySaved = source.fields.some((f) => f.set && f.source === "keychain");
  const typed = Object.values(values).some((v) => v.trim());
  const canSync = source.capabilities.includes("holdings") || source.capabilities.includes("trades");

  const sync = async () => {
    setBusy(true);
    setError(null);
    try {
      onSynced(await api.sync(source.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-baseline gap-2">
          <h3 className="text-ink">{source.label.toUpperCase()}</h3>
          {source.experimental && <span className="border border-amber/60 px-1 text-[10px] tracking-widest text-amber">EXPERIMENTAL</span>}
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-dim">{source.notes}</p>
        {source.capabilities.includes("live") && (
          <p className="mt-1 text-[11px] text-dim"><span className="text-ink">Live prices:</span> {source.live_note}</p>
        )}
      </div>

      {source.fields.length > 0 && (
        <form className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (typed) run(() => api.saveCredentials(source.id, values), "Saved to the system keychain").then(() => setValues({}));
              }}>
          {source.fields.map((f) => {
            const fromEnv = f.source === "environment";
            return (
              <label key={f.name} className="grid grid-cols-[110px_1fr] items-center gap-x-3 gap-y-0.5">
                <span className="text-[11px] text-dim">{f.label.toUpperCase()}{f.required ? "" : " (OPTIONAL)"}</span>
                <input
                  type={f.secret ? "password" : "text"} autoComplete="off" spellCheck={false}
                  value={values[f.name] ?? ""} disabled={busy || fromEnv}
                  onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                  placeholder={fromEnv ? "Set by environment variable" : f.set ? "Saved · type to replace" : f.label}
                  aria-label={`${source.label} ${f.label}`}
                  className={field}
                />
                {f.help && <span className="col-start-2 text-[10px] text-dim/80">{f.help}</span>}
              </label>
            );
          })}
          <div className="flex items-center gap-3 pt-1">
            <button type="submit" disabled={busy || !typed} className={loud}>SAVE</button>
            {anySaved && (
              <button type="button" disabled={busy}
                      onClick={() => run(() => api.removeCredentials(source.id), `${source.label} credentials removed`)}
                      className="text-[11px] text-dim underline hover:text-down disabled:opacity-40">
                Remove saved {source.label} credentials
              </button>
            )}
          </div>
        </form>
      )}

      {source.session.needed && source.configured && (
        <div className="space-y-2 border-t border-line pt-3">
          <div className="text-[11px]">
            <span className="text-dim">SESSION </span>
            {source.session.active
              ? <span className="text-up">Active since {source.session.issued?.replace("T", " ").slice(0, 16)}</span>
              : <span className="text-amber">Not logged in today (sessions end about 06:00 each morning)</span>}
          </div>

          {source.login === "redirect" && (
            <>
              <ol className="list-decimal space-y-0.5 pl-4 text-[11px] text-dim">
                <li>Open the Kite login and sign in.</li>
                <li>Kite sends your browser to your app's redirect address. Copy that whole address.</li>
                <li>Paste it here and press LOG IN.</li>
              </ol>
              <div className="flex gap-2">
                <button type="button" disabled={busy} className={quiet}
                        onClick={() => api.loginUrl(source.id).then(({ url }) => window.open(url, "_blank"))
                          .catch((e) => setError((e as Error).message))}>
                  OPEN KITE LOGIN
                </button>
              </div>
            </>
          )}

          <form className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  run(() => api.openSession(source.id, paste.trim() || undefined), `Logged in to ${source.label}`)
                    .then(() => setPaste(""));
                }}>
            <input value={paste} onChange={(e) => setPaste(e.target.value)} disabled={busy}
                   type={source.login === "generate" ? "password" : "text"} autoComplete="off" spellCheck={false}
                   placeholder={source.login === "redirect" ? "Paste the address with request_token=…"
                     : "Optional: paste an access token instead"}
                   aria-label={`${source.label} login`}
                   className={field} />
            <button type="submit" disabled={busy || (source.login === "redirect" && !paste.trim())} className={loud}>
              LOG IN
            </button>
          </form>
          {source.session.active && (
            <button type="button" disabled={busy} onClick={() => run(() => api.closeSession(source.id), "Logged out")}
                    className="text-[11px] text-dim underline hover:text-down disabled:opacity-40">
              Log out of {source.label}
            </button>
          )}
        </div>
      )}

      {canSync && source.configured && (
        <div className="space-y-2 border-t border-line pt-3">
          <div className="flex items-center gap-3">
            <button type="button" onClick={sync} disabled={busy || (source.session.needed && !source.session.active)}
                    className={quiet}>
              SYNC
            </button>
            <span className="text-[11px] text-dim">
              {source.last_sync ? `Last synced ${source.last_sync.replace("T", " ").slice(0, 16)} · ${source.holdings_synced} holdings`
                : "Not synced yet"}
              {source.capabilities.includes("trades") ? " · adds today's trades" : ""}
            </span>
          </div>
          {source.mismatches.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] tabular-nums">
                <thead className="text-dim">
                  <tr><th className="py-0.5 text-left font-normal">SYMBOL</th>
                    <th className="text-right font-normal">{source.label.toUpperCase()}</th>
                    <th className="text-right font-normal">LEDGER</th></tr>
                </thead>
                <tbody>
                  {source.mismatches.map((m) => (
                    <tr key={m.symbol} className="border-t border-line/60">
                      <td className="py-0.5">{m.symbol}</td>
                      <td className="text-right">{m.broker_quantity}</td>
                      <td className="text-right text-down">{m.ledger_quantity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-[10px] text-dim">
                The ledger is built from imported trades. A difference usually means trades from before your
                import are missing; import the full report with IMPORT CSV.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
