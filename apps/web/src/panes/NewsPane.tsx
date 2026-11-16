import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { MarketEvent, NewsFeed, NewsSource } from "../api/types";
import { ticker } from "../format";
import { useStore } from "../state/store";
import { Empty } from "../ui";

type Scope = "all" | "portfolio" | "watchlist";

const KIND: Record<string, { label: string; cls: string }> = {
  earnings: { label: "RESULTS", cls: "text-amber" },
  ex_dividend: { label: "EX-DIV", cls: "text-up" },
  dividend: { label: "DIVIDEND", cls: "text-up" },
  split: { label: "SPLIT", cls: "text-amber" },
  bonus: { label: "BONUS", cls: "text-amber" },
  coupon: { label: "COUPON", cls: "text-up" },
  maturity: { label: "MATURES", cls: "text-cyan" },
  check: { label: "CHECK", cls: "text-down" },
};

function ago(iso: string): string {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(mins, 1)}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

function when(d: string): string {
  const days = Math.round((new Date(`${d}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days < 0) return `${-days}d ago`;
  return `in ${days}d`;
}

const HIDDEN_KEY = "qt.news.hidden";

function loadHidden(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

function saveHidden(s: Set<string>) {
  try {
    localStorage.setItem(HIDDEN_KEY, JSON.stringify([...s]));
  } catch {
    /* private window: the filter just isn't remembered */
  }
}

/** Which sources are downloaded at all. Switched-off sources cost no downloads. */
function SourcesPanel({ onSaved, onClose }: { onSaved: () => void; onClose: () => void }) {
  const [list, setList] = useState<NewsSource[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.newsSources().then(setList).catch((e) => setError((e as Error).message));
  }, []);
  const toggle = async (id: string) => {
    if (!list) return;
    const next = list.map((s) => (s.id === id ? { ...s, enabled: !s.enabled } : s));
    setList(next);
    try {
      setList(await api.setNewsSources(next.filter((s) => s.enabled).map((s) => s.id)));
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const regions = [...new Set((list ?? []).map((s) => s.region))];
  return (
    <div className="border-b border-line bg-raise/40 px-3 py-2 text-[11px]">
      <div className="flex items-baseline gap-2">
        <span className="text-[10px] tracking-widest text-dim">DOWNLOAD NEWS FROM</span>
        <button onClick={onClose} className="ml-auto text-[10.5px] text-dim underline hover:text-ink">close</button>
      </div>
      {error && <div role="alert" className="text-down">{error}</div>}
      <div className="mt-1 flex flex-wrap gap-x-6 gap-y-1">
        {regions.map((r) => (
          <div key={r}>
            <div className="text-[9.5px] tracking-widest text-dim">{r.toUpperCase()}</div>
            {(list ?? []).filter((s) => s.region === r).map((s) => (
              <label key={s.id} className="flex items-center gap-1.5">
                <input type="checkbox" checked={s.enabled} onChange={() => toggle(s.id)} className="accent-amber" />
                <span>{s.label}</span>
                <span className="text-[10px] text-dim">{s.kind === "symbol" ? "searched per stock" : "matched to your stocks"}</span>
              </label>
            ))}
          </div>
        ))}
      </div>
      <p className="mt-1 text-[10px] text-dim">
        Free public feeds, no keys. Each is asked at most every 30 minutes; market wires are one download each,
        whatever the number of stocks. Wire stories that name none of your stocks show as market news.
      </p>
    </div>
  );
}

/** Headlines and upcoming events for held, watched and starred stocks, plus
 *  market news for the benchmark, from Yahoo Finance, Google News and market
 *  wires. Kept locally: headlines refresh at most every 30 minutes and
 *  calendars every 12 hours, so reopening costs nothing. */
export function NewsPane() {
  const openSymbol = useStore((s) => s.openSymbol);
  const [scope, setScope] = useState<Scope>("all");
  const [only, setOnly] = useState<string | null>(null);
  const [feed, setFeed] = useState<NewsFeed | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(loadHidden);
  const [settings, setSettings] = useState(false);

  const toggleShown = (id: string) => {
    const next = new Set(hidden);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setHidden(next);
    saveHidden(next);
  };

  const load = (force = false) => {
    setBusy(true);
    setError(null);
    api.news({ scope, force })
      .then(setFeed)
      .catch((e) => setError((e as Error).message))
      .finally(() => setBusy(false));
  };

  useEffect(() => {
    setOnly(null);
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const items = (feed?.items ?? [])
    .filter((i) => !only || i.symbols.includes(only))
    .filter((i) => (i.sources ?? [i.source]).some((s) => !hidden.has(s)));
  const label = new Map((feed?.sources ?? []).map((s) => [s.id, s.label]));
  const enabled = (feed?.sources ?? []).filter((s) => s.enabled);
  const events = (feed?.events ?? []).filter((e) => !only || e.symbol === only);
  const names = new Map((feed?.covered ?? []).map((c) => [c.symbol, c.name]));

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-1.5">
        <div role="radiogroup" aria-label="News for" className="flex">
          {(["all", "portfolio", "watchlist"] as const).map((s) => (
            <button key={s} role="radio" aria-checked={scope === s} onClick={() => setScope(s)}
                    className={`-ml-px border px-1.5 py-0.5 text-[10px] tracking-widest first:ml-0 ${scope === s ? "relative z-10 border-amber bg-amber text-black" : "border-line text-dim hover:text-ink"}`}>
              {s === "all" ? "ALL" : s === "portfolio" ? "PORTFOLIO" : "WATCHLIST"}
            </button>
          ))}
        </div>
        <select value={only ?? ""} onChange={(e) => setOnly(e.target.value || null)} aria-label="Only this stock"
                className="border border-line bg-bg px-1 py-0.5 text-[11px] text-ink outline-none focus:border-amber">
          <option value="">Every stock</option>
          {(feed?.covered ?? []).map((c) => (
            <option key={c.symbol} value={c.symbol}>{c.why === "market" ? "Market" : ticker(c.symbol)}{c.name ? ` · ${c.name}` : ""}</option>
          ))}
        </select>
        <span className="ml-auto text-[10px] text-dim" title="Headlines refresh at most every 30 minutes, calendars every 12 hours">
          {feed?.updated_at ? `updated ${ago(feed.updated_at)}` : ""}
        </span>
        <button onClick={() => setSettings(!settings)} aria-expanded={settings}
                className={`border px-2 py-0.5 text-[10px] hover:text-ink ${settings ? "border-amber text-amber" : "border-line text-dim hover:border-amber"}`}>
          SOURCES
        </button>
        <button onClick={() => load(true)} disabled={busy}
                className="border border-line px-2 py-0.5 text-[10px] text-dim hover:border-amber hover:text-ink disabled:opacity-40">
          {busy ? "LOADING…" : "REFRESH"}
        </button>
      </div>

      {settings && <SourcesPanel onSaved={() => load(false)} onClose={() => setSettings(false)} />}
      {enabled.length > 1 && (
        <div className="flex flex-wrap items-center gap-1 border-b border-line px-3 py-1" aria-label="Show sources">
          <span className="mr-1 text-[9.5px] tracking-widest text-dim">SHOW</span>
          {enabled.map((s) => {
            const on = !hidden.has(s.id);
            return (
              <button key={s.id} onClick={() => toggleShown(s.id)} aria-pressed={on}
                      title={on ? `Hide ${s.label} stories` : `Show ${s.label} stories`}
                      className={`border px-1.5 py-px text-[10px] ${on ? "border-line text-ink" : "border-line/50 text-dim line-through opacity-60"}`}>
                {s.label} <span className="tabular-nums text-dim">{s.count ?? 0}</span>
              </button>
            );
          })}
        </div>
      )}

      {error && <div role="alert" className="px-3 py-2 text-down">{error}</div>}

      <div className="min-h-0 flex-1 overflow-auto">
        {!feed && !error ? (
          <Empty title="Loading news…" />
        ) : feed && !feed.covered.length ? (
          <Empty title="No stocks to follow yet" hint="News covers stocks you hold, watch (eye) or star, plus market news." />
        ) : (
          <>
            {events.length > 0 && (
              <section className="border-b border-line">
                <div className="px-3 pb-1 pt-2 text-[10px] tracking-widest text-dim">COMING UP</div>
                <ul className="pb-1.5">
                  {events.map((e: MarketEvent, i) => (
                    <li key={`${e.symbol}${e.kind}${e.date}${i}`} className="grid grid-cols-[64px_68px_86px_1fr] items-baseline gap-2 px-3 py-0.5 text-[11px]">
                      <span className="tabular-nums text-dim" title={e.date}>{when(e.date)}</span>
                      <span className={`text-[9px] tracking-widest ${KIND[e.kind]?.cls ?? "text-dim"}`}>{KIND[e.kind]?.label ?? e.kind.toUpperCase()}</span>
                      <button onClick={() => openSymbol(e.symbol, names.get(e.symbol))} className="truncate text-left text-cyan hover:underline">
                        {e.symbol === "^NSEI" ? "NIFTY 50" : ticker(e.symbol)}
                      </button>
                      <span className="min-w-0 truncate" title={`${e.text} · ${e.source}`}>{e.text}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <div className="px-3 pb-1 pt-2 text-[10px] tracking-widest text-dim">HEADLINES</div>
            {!items.length ? (
              <p className="px-3 pb-3 text-[11px] text-dim">
                {hidden.size ? "No headlines from the sources shown. Turn more on above." : "No headlines in the last 30 days."}
              </p>
            ) : (
              <ul>
                {items.map((n) => (
                  <li key={n.id} className="border-b border-line/60 px-3 py-2 hover:bg-raise/60">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-dim">
                      {n.symbols.map((s) => (
                        <button key={s} onClick={() => setOnly(s)} title={`Only ${s}`}
                                className="tracking-widest text-cyan hover:underline">
                          {s === "^NSEI" ? "MARKET" : ticker(s)}
                        </button>
                      ))}
                      <span>{n.publisher}</span>
                      {(n.sources ?? []).some((s) => label.get(s) !== n.publisher) && (
                        <span className="text-dim/80">via {(n.sources ?? []).map((s) => label.get(s) ?? s).join(", ")}</span>
                      )}
                      <span title={n.published_at}>{ago(n.published_at)}</span>
                    </div>
                    {n.url ? (
                      <a href={n.url} target="_blank" rel="noreferrer noopener"
                         className="mt-0.5 block text-[12px] text-ink hover:text-amber hover:underline">
                        {n.title}
                      </a>
                    ) : (
                      <div className="mt-0.5 text-[12px] text-ink">{n.title}</div>
                    )}
                    {n.summary && <p className="mt-0.5 line-clamp-2 text-[11px] text-dim">{n.summary}</p>}
                  </li>
                ))}
              </ul>
            )}
            {feed && feed.errors.length > 0 && (
              <p className="px-3 py-2 text-[10px] text-amber">Could not refresh: {feed.errors.join("; ")}</p>
            )}
            <p className="px-3 py-2 text-[10px] text-dim">
              Headlines from {enabled.map((s) => s.label).join(", ") || "no sources (turn some on under SOURCES)"};
              calendars from Yahoo Finance; corporate actions, coupons and maturities from your ledger. Links open in
              your browser.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
