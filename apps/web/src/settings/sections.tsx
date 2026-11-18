import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { CacheStatus, InsightState } from "../api/types";
import { feedLabel, num, pct } from "../format";
import { HORIZONS as COV_HORIZONS, WINDOWS as COV_WINDOWS } from "../panes/CovariancePane";
import { SourcesPanel } from "../panes/NewsPane";
import { LOOKBACKS } from "../panes/RiskPane";
import { BenchmarkPicker } from "../ribbon/BenchmarkPicker";
import { ConnectionsPanel } from "../ribbon/ConnectionsDialog";
import { useStore } from "../state/store";
import { Seg } from "../ui";

const RELEASES = "https://github.com/saiteja-bheri/Tradeview/releases/latest";

export const CURRENCIES = ["AUTO", "INR", "USD", "EUR", "GBP", "JPY", "AED", "SGD", "AUD", "CAD", "CHF", "HKD"];

const button = "rounded-md border border-line px-3 py-1.5 text-dim hover:border-accent hover:text-ink disabled:opacity-40";
const primary = "rounded-md border border-accent px-3 py-1.5 text-accent hover:bg-accent hover:text-black disabled:opacity-40";

export function Card({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-4">
      <h2 className="text-[14px] font-semibold">{title}</h2>
      {hint && <p className="mt-0.5 text-[11.5px] text-dim">{hint}</p>}
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="grid grid-cols-[180px_1fr] items-center gap-3">
      <div className="text-[11px] tracking-widest text-dim">{label}</div>
      <div>
        {children}
        {hint && <div className="mt-1 text-[11px] text-dim/80">{hint}</div>}
      </div>
    </div>
  );
}

export function RiskSection() {
  const p = useStore((s) => s.portfolio?.params);
  const setParam = useStore((s) => s.setParam);
  const [rf, setRf] = useState("");
  useEffect(() => { if (p) setRf((p.risk_free_rate * 100).toFixed(2)); }, [p?.risk_free_rate]);   // eslint-disable-line react-hooks/exhaustive-deps
  const rfValue = Number(rf);
  const rfOk = rf.trim() !== "" && Number.isFinite(rfValue) && rfValue >= 0 && rfValue <= 20;

  return (
    <Card title="Risk" hint="How beta, alpha, the ratios, VaR and the covariance matrix are measured.">
      <Field label="BENCHMARK"><BenchmarkPicker hideLabel /></Field>
      <Field label="VAR CONFIDENCE">
        <Seg<number> label="VaR confidence" hideLabel value={p?.confidence}
                     options={[{ value: 0.95, label: "95%" }, { value: 0.99, label: "99%" }]}
                     onChange={(v) => setParam({ confidence: v })} />
      </Field>
      <Field label="VAR HORIZON">
        <Seg<number> label="VaR horizon" hideLabel value={p?.horizon_days}
                     options={[1, 2, 3, 5, 10].map((d) => ({ value: d, label: `${d}D` }))}
                     onChange={(v) => setParam({ horizon_days: v })} />
      </Field>
      <Field label="RISK LOOKBACK" hint="History behind beta, alpha, Sharpe, Sortino, drawdown, volatility and VaR.">
        <Seg<number> label="Risk lookback" hideLabel value={p?.lookback_days} options={LOOKBACKS}
                     onChange={(v) => setParam({ lookback_days: v })} />
      </Field>
      <Field label="COVARIANCE HORIZON">
        <Seg<number> label="Covariance horizon" hideLabel value={p?.cov_horizon_days} options={COV_HORIZONS}
                     onChange={(v) => setParam({ cov_horizon_days: v })} />
      </Field>
      <Field label="COVARIANCE WINDOW">
        <Seg<number> label="Covariance window" hideLabel value={p?.cov_lookback_days} options={COV_WINDOWS}
                     onChange={(v) => setParam({ cov_lookback_days: v })} />
      </Field>
      <Field label="RISK-FREE RATE" hint="Annual rate used by Sharpe, Sortino and alpha. 0 to 20%.">
        <form className="flex items-center gap-2"
              onSubmit={(e) => { e.preventDefault(); if (rfOk) setParam({ risk_free_rate: rfValue / 100 }); }}>
          <input value={rf} onChange={(e) => setRf(e.target.value)} inputMode="decimal" aria-label="Risk-free rate in percent"
                 className={`w-24 rounded-md border bg-bg px-2 py-1 text-right font-mono outline-none ${rfOk ? "border-line focus:border-accent" : "border-down"}`} />
          <span className="text-dim">%</span>
          <button type="submit" disabled={!rfOk || (p != null && Math.abs(rfValue / 100 - p.risk_free_rate) < 1e-9)}
                  className={primary}>SAVE</button>
        </form>
      </Field>
    </Card>
  );
}

export function ConnectionsSection() {
  return (
    <Card title="Connections" hint="Brokers and live price sources. Everything here is read-only: the app can never place an order.">
      <div className="overflow-hidden rounded-md border border-line"><ConnectionsPanel /></div>
    </Card>
  );
}

export function DisplaySection() {
  const p = useStore((s) => s.portfolio?.params);
  const display = useStore((s) => s.portfolio?.display);
  const setParam = useStore((s) => s.setParam);
  const resetAllLayouts = useStore((s) => s.resetAllLayouts);
  const [done, setDone] = useState(false);
  return (
    <Card title="Display" hint="How money is shown and how pages are arranged. Calculations always stay in rupees.">
      <Field label="CURRENCY"
             hint={display?.choice === "AUTO" ? `AUTO is showing ${display.currency}, the currency most of your portfolio is in.` : undefined}>
        <select value={p?.display_currency ?? "INR"} aria-label="Display currency"
                onChange={(e) => setParam({ display_currency: e.target.value })}
                className="rounded-md border border-line bg-bg px-2 py-1 text-ink outline-none focus:border-accent">
          {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </Field>
      <Field label="PAGE LAYOUTS" hint="Puts every page's panels back where they started.">
        <button className={button} onClick={() => { resetAllLayouts(); setDone(true); }}>
          {done ? "LAYOUTS RESET" : "RESET ALL LAYOUTS"}
        </button>
      </Field>
    </Card>
  );
}

export function AiSection() {
  const [state, setState] = useState<InsightState | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.insight().then(setState).catch((e) => setError((e as Error).message)); }, []);
  const run = async (fn: () => Promise<InsightState>) => {
    setBusy(true); setError(null);
    try { setState(await fn()); setKey(""); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Card title="AI insight" hint="Google Gemini writes the memo from summary figures only: never your trades, quantities or costs.">
      <Field label="STATUS">
        <span className={state?.configured ? "text-up" : "text-dim"}>
          {state == null ? "…" : state.configured
            ? `Key saved (${state.source === "environment" ? "environment variable" : "system keychain"}) · ${state.model}`
            : "No key saved"}
        </span>
      </Field>
      <Field label="API KEY" hint="Create one at aistudio.google.com/apikey. Stored in the system keychain, never in the ledger.">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); run(() => api.saveInsightKey(key.trim())); }}>
          <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" spellCheck={false}
                 placeholder={state?.configured ? "Paste a new key to replace it" : "Gemini API key"} aria-label="Gemini API key"
                 className="min-w-0 flex-1 rounded-md border border-line bg-bg px-2 py-1.5 outline-none focus:border-accent" />
          <button type="submit" disabled={busy || key.trim().length < 20} className={primary}>SAVE</button>
          {state?.configured && state.source !== "environment" && (
            <button type="button" disabled={busy} className={button} onClick={() => run(() => api.removeInsightKey())}>REMOVE</button>
          )}
        </form>
      </Field>
      {error && <div role="alert" className="text-down">{error}</div>}
    </Card>
  );
}

export function NewsSection() {
  return (
    <Card title="News" hint="Which free public feeds the News tab downloads from.">
      <div className="overflow-hidden rounded-md border border-line"><SourcesPanel onSaved={() => {}} /></div>
    </Card>
  );
}

export function DataSection() {
  const setImportOpen = useStore((s) => s.setImportOpen);
  const setBondsOpen = useStore((s) => s.setBondsOpen);
  const exportCsv = useStore((s) => s.exportCsv);
  const [cache, setCache] = useState<CacheStatus | null>(null);
  useEffect(() => { api.cache().then(setCache).catch(() => {}); }, []);
  return (
    <Card title="Data" hint="Your ledger lives on this computer. Nothing here sends anything to a broker.">
      <Field label="TRADES">
        <div className="flex flex-wrap gap-2">
          <button className={primary} onClick={() => setImportOpen(true)}>IMPORT CSV / EXCEL</button>
          <button className={button} onClick={() => exportCsv()}>EXPORT LEDGER CSV</button>
        </div>
      </Field>
      <Field label="BONDS"><button className={button} onClick={() => setBondsOpen(true)}>ADD OR EDIT BONDS</button></Field>
      <Field label="PRICE CACHE">
        {cache ? (
          <span className="text-dim">
            {num(cache.symbols.length, 0)} symbols · {num(cache.bars, 0)} daily prices · {num(cache.served_from_cache, 0)} requests served locally
          </span>
        ) : <span className="text-dim">…</span>}
      </Field>
    </Card>
  );
}

/** Wipes the app back to a fresh install: ledger, settings, caches and layouts. */
export function ResetCard() {
  const [typed, setTyped] = useState("");
  const [keys, setKeys] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = typed === "RESET";

  const reset = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.resetEverything(keys);
      try {
        Object.keys(localStorage).filter((k) => k.startsWith("qt.")).forEach((k) => localStorage.removeItem(k));
      } catch { /* storage unavailable: layouts just stay */ }
      window.location.reload();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <section className="rounded-lg border border-down/50 bg-panel p-4">
      <h2 className="text-[14px] font-semibold text-down">Reset everything</h2>
      <p className="mt-0.5 text-[11.5px] text-dim">
        Deletes every trade, corporate action, wealth item, bond, watchlist entry, AI memo and setting, the
        price cache and your page layouts, so the app starts as if freshly installed. This cannot be undone:
        export your ledger first if you may want it back.
      </p>
      <div className="mt-3 space-y-2">
        <label className="flex items-center gap-2 text-[11.5px]">
          <input type="checkbox" checked={keys} onChange={(e) => setKeys(e.target.checked)} className="accent-[var(--color-down)]" />
          Also remove saved API keys and broker logins (Upstox, Zerodha, Groww, Gemini)
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type RESET" aria-label="Type RESET to confirm"
                 spellCheck={false} autoComplete="off"
                 className="w-36 rounded-md border border-line bg-bg px-2 py-1.5 font-mono outline-none focus:border-down" />
          <button onClick={reset} disabled={!ready || busy}
                  className="rounded-md border border-down px-3 py-1.5 text-down hover:bg-down hover:text-black disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-down">
            {busy ? "RESETTING…" : "RESET EVERYTHING"}
          </button>
        </div>
        {error && <div role="alert" className="text-down">{error}</div>}
      </div>
    </section>
  );
}

export function AboutSection() {
  const status = useStore((s) => s.status);
  const feed = useStore((s) => s.live?.status);
  const rf = useStore((s) => s.portfolio?.params.risk_free_rate);
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    api.health().then((h) => setVersion((h as { version?: string }).version ?? null)).catch(() => {});
  }, []);
  return (
    <Card title="About" hint="Quant Terminal is a read-only analytics terminal.">
      <Field label="ENGINE">{status === "ok" ? `Running${version ? ` · version ${version}` : ""}` : status.toUpperCase()}</Field>
      <Field label="PRICES">{feedLabel(feed)}{feed?.detail ? ` · ${feed.detail}` : ""}</Field>
      <Field label="RISK-FREE RATE">{pct(rf ?? null, 2)}</Field>
      <Field label="TRADING">
        <span>It cannot place, change or cancel orders with any broker. Trades you add are records of trades made elsewhere.</span>
      </Field>
      <Field label="DOWNLOAD" hint="Installers for macOS (Apple silicon) and Windows, to share or to update this app.">
        <a href={RELEASES} target="_blank" rel="noreferrer noopener" className="text-accent underline hover:text-ink">
          Latest release on GitHub
        </a>
      </Field>
    </Card>
  );
}
