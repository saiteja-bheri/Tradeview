import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { SearchResult } from "../api/types";
import { ticker } from "../format";
import { useStore } from "../state/store";
import { EyeIcon } from "../ui";

const MARKETS = ["ALL", "INDIA", "US", "UK", "EUROPE", "ASIA", "FUNDS"] as const;
type Market = (typeof MARKETS)[number];
const MARKET_KEY = "qt.search.market";
const LABEL: Record<string, string> = {
  INDIA: "India", US: "United States", UK: "United Kingdom", EUROPE: "Europe", ASIA: "Asia",
  AMERICAS: "Americas", PACIFIC: "Australia & NZ", FUNDS: "Funds & commodities", OTHER: "Other markets",
};

/** Keeps the engine's ranking inside each market, with markets ordered by their best result. */
function grouped(rows: SearchResult[]): SearchResult[] {
  const order: string[] = [];
  for (const r of rows) if (!order.includes(r.market ?? "OTHER")) order.push(r.market ?? "OTHER");
  return order.flatMap((m) => rows.filter((r) => (r.market ?? "OTHER") === m));
}

function savedMarket(): Market {
  try {
    const m = localStorage.getItem(MARKET_KEY) as Market | null;
    return m && MARKETS.includes(m) ? m : "ALL";
  } catch {
    return "ALL";
  }
}

/** Stock search by company name or ticker on every market. Each result shows
 *  where it trades and its currency; the chips narrow the search to one market. */
export function SearchBox() {
  const openSymbol = useStore((s) => s.openSymbol);
  const toggleStar = useStore((s) => s.toggleStar);
  const watch = useStore((s) => s.watch);
  const starredSet = new Set(watch.filter((w) => w.starred).map((w) => w.symbol));
  const watchedSet = new Set(watch.filter((w) => w.watched).map((w) => w.symbol));
  const toggleWatch = useStore((s) => s.toggleWatch);
  const [query, setQuery] = useState("");
  const [market, setMarket] = useState<Market>(savedMarket);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [online, setOnline] = useState(true);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const seq = useRef(0);

  const q = query.trim();

  useEffect(() => {
    try {
      localStorage.setItem(MARKET_KEY, market);
    } catch {
      /* remembering the market is a convenience only */
    }
  }, [market]);

  useEffect(() => {
    const mine = ++seq.current;
    if (!q) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(async () => {
      try {
        const r = await api.search(q, market);
        if (mine !== seq.current) return;
        setResults(grouped(r.results));
        setOnline(r.online);
        setActive(0);
      } catch {
        if (mine !== seq.current) return;
        setResults([]);
        setOnline(false);
      } finally {
        if (mine === seq.current) setLoading(false);
      }
    }, 200);
    return () => clearTimeout(timer);
  }, [q, market]);

  // "/" focuses the search from anywhere outside a text field
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = el?.tagName === "INPUT" || el?.tagName === "TEXTAREA" || el?.isContentEditable;
      if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    listRef.current?.querySelector(`#qt-search-${active}`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const pick = (symbol: string) => {
    const hit = results.find((r) => r.symbol === symbol);
    openSymbol(symbol, hit?.name, hit?.exchange);
    setQuery("");
    setResults([]);
    setOpen(false);
    inputRef.current?.blur();
  };

  const submit = () => {
    if (!q) return;
    const chosen = results[active];
    if (chosen) return pick(chosen.symbol);
    // Still loading or nothing found: a single word is taken as a ticker on the chosen market.
    if (!/\s/.test(q)) {
      const t = q.toUpperCase();
      pick(market === "INDIA" || market === "ALL" ? (/\.(NS|BO)$/.test(t) ? t : `${t}.NS`) : t);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
      if (results.length) {
        const step = e.key === "ArrowDown" ? 1 : -1;
        setActive((a) => (a + step + results.length) % results.length);
      }
    } else if (e.key === "Tab" && open && q) {
      e.preventDefault();  // Tab / Shift+Tab move between markets
      const i = MARKETS.indexOf(market);
      setMarket(MARKETS[(i + (e.shiftKey ? -1 : 1) + MARKETS.length) % MARKETS.length]);
    } else if (e.key === "Enter") {
      e.preventDefault();
      submit();
    } else if (e.key === "Escape") {
      if (open && q) setOpen(false);
      else inputRef.current?.blur();
    }
  };

  const show = open && q.length > 0;
  const where = market === "ALL" ? "on any market" : `in ${LABEL[market] ?? market}`;
  const status = loading && !results.length ? "Searching…"
    : !results.length ? (online ? `No matching stock ${where}.` : "No match in your ledger. Market search is offline.")
    : null;

  return (
    <div className="relative min-w-40 max-w-72 flex-1">
      <div className="flex items-center border border-line bg-bg focus-within:border-amber">
        <svg viewBox="0 0 16 16" aria-hidden="true" className="ml-2 h-3 w-3 shrink-0 text-dim">
          <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
        <input
          ref={inputRef}
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          placeholder={market === "ALL" ? "Search any stock by name or ticker" : `Search ${LABEL[market] ?? market}`}
          aria-label="Search stocks by name or ticker"
          role="combobox"
          aria-expanded={show}
          aria-controls="qt-search-list"
          aria-autocomplete="list"
          aria-activedescendant={show && results[active] ? `qt-search-${active}` : undefined}
          spellCheck={false}
          autoComplete="off"
          className="min-w-0 flex-1 bg-transparent px-2 py-1 text-amber outline-none placeholder:text-dim/60"
        />
        {market !== "ALL" && <span className="mr-1 text-[9px] tracking-widest text-dim">{market}</span>}
        {!q && <kbd className="mr-1.5 border border-line px-1 text-[10px] text-dim/70">/</kbd>}
      </div>

      {show && (
        <div className="absolute left-0 top-full z-30 mt-1 w-[30rem] max-w-[92vw] border border-amber bg-panel shadow-2xl">
          <div role="radiogroup" aria-label="Market" className="flex flex-wrap gap-1 border-b border-line px-2 py-1.5">
            {MARKETS.map((m) => (
              <button key={m} type="button" role="radio" aria-checked={market === m}
                      onMouseDown={(e) => { e.preventDefault(); setMarket(m); }}
                      className={`px-1.5 py-0.5 text-[10px] tracking-widest ${market === m ? "bg-amber text-black" : "text-dim hover:text-ink"}`}>
                {m}
              </button>
            ))}
            <span className="ml-auto self-center text-[9px] text-dim/70">TAB switches market</span>
          </div>
          {status ? (
            <div className="px-3 py-2 text-dim">{status}</div>
          ) : (
            <ul id="qt-search-list" ref={listRef} role="listbox" className="max-h-96 overflow-auto py-1">
              {results.map((r, i) => {
                const group = r.market ?? "OTHER";
                const header = i === 0 || (results[i - 1].market ?? "OTHER") !== group;
                const on = i === active;
                return (
                  <li key={r.symbol} role="presentation">
                    {header && market === "ALL" && (
                      <div className="px-3 pb-0.5 pt-1.5 text-[9px] tracking-widest text-dim">
                        {(LABEL[group] ?? group).toUpperCase()}
                      </div>
                    )}
                    <div
                      id={`qt-search-${i}`}
                      role="option"
                      aria-selected={on}
                      onMouseDown={(e) => { e.preventDefault(); pick(r.symbol); }}
                      onMouseMove={() => setActive(i)}
                      className={`flex cursor-pointer items-center gap-3 px-3 py-1.5 ${on ? "bg-amber text-black" : ""}`}
                    >
                      <span className="min-w-0 flex-1 truncate">{r.name || ticker(r.symbol)}</span>
                      {r.held && (
                        <span className={`text-[10px] tracking-widest ${on ? "text-black/70" : "text-up"}`}>HELD</span>
                      )}
                      <span className={`shrink-0 ${on ? "text-black" : "text-amber"}`}>{ticker(r.symbol)}</span>
                      <span className={`w-24 shrink-0 truncate text-right text-[10px] tracking-wider ${on ? "text-black/70" : "text-dim"}`}
                            title={`${r.exchange}${r.currency ? ` · priced in ${r.currency}` : ""}`}>
                        {r.exchange === "CMDTY" ? "CMD" : r.exchange}{r.currency ? ` · ${r.currency}` : ""}
                      </span>
                      <button type="button"
                              onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); toggleWatch(r.symbol, r.name); }}
                              aria-label={watchedSet.has(r.symbol) ? `Stop watching ${r.symbol}` : `Watch ${r.symbol}`}
                              title={watchedSet.has(r.symbol) ? "On your watchlist" : "Add to watchlist"}
                              className={`shrink-0 ${watchedSet.has(r.symbol) ? (on ? "text-black" : "text-cyan") : (on ? "text-black/60" : "text-dim hover:text-cyan")}`}>
                        <EyeIcon on={watchedSet.has(r.symbol)} />
                      </button>
                      <button type="button" title={starredSet.has(r.symbol) ? "Starred for the optimizer" : "Star for the optimizer"}
                              onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); toggleStar(r.symbol, r.name); }}
                              aria-label={starredSet.has(r.symbol) ? `Unstar ${r.symbol}` : `Star ${r.symbol}`}
                              className={`shrink-0 ${starredSet.has(r.symbol) ? (on ? "text-black" : "text-amber") : (on ? "text-black/60" : "text-dim hover:text-amber")}`}>
                        {starredSet.has(r.symbol) ? "★" : "☆"}
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {!status && !online && (
            <div className="border-t border-line px-3 py-1 text-[10px] text-dim">
              Market search is offline. Showing stocks from your ledger only.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
