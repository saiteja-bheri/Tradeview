# Terminal Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single three-column screen with a rail of six pages (five dockable, one Settings page), a slim top bar and the reference look, plus four new cards and one read-only engine endpoint.

**Architecture:** A `page` field in the zustand store drives which page is visible; every dockable page is its own flexlayout `Model` persisted under its own key, and all pages stay mounted (hidden with CSS) so charts survive switching. New cards are ordinary panes registered in one pane table. Market quotes come from a new engine module with an injectable fetcher and a 5-minute in-memory cache.

**Tech Stack:** Electron, React 19, Vite 8, Tailwind 4, zustand, flexlayout-react, lightweight-charts; FastAPI, SQLAlchemy, yfinance, pytest.

**Spec:** `docs/superpowers/specs/2026-11-17-terminal-redesign-design.md`

## Global Constraints

- Strictly read-only: no element anywhere may look like an order (buy, sell, place, order, trade now, buying power, available funds). The ledger form's BOUGHT/SOLD is exempt.
- Existing read-only engine tests stay unchanged and green; the new route path must not contain order, execut, place, buy, sell or webhook.
- Production CSP in `apps/web/vite.config.ts` unchanged: no remote fonts, images or inline scripts. Icons are inline SVG.
- Layout keys: `qt.layout.<page>.v1` for page in markets, portfolio, chart, analytics, plan. `qt.layout.v9` is ignored, not deleted.
- Colours: accent teal around `#14d9a5`, losses around `#ff4d6d`, amber only for warnings; card radius 8px, padding 12px; body text contrast at least 4.5:1.
- Interface font: system sans-serif stack; all numbers tabular figures; `table.grid-table` stays monospace.
- No commits: the user reviews the local app and asks for the commit. Replace every "commit" with leaving the change uncommitted.
- Minimum window stays 1000 x 600.

## Review Focus

- Live feed off or the stock not held: Stock panel and Price updates show a plain empty state, never a blank card or a crash.
- Yahoo unreachable: the Markets page shows each card's "offline" state and the rest of the app works; the endpoint returns `online: false` instead of failing.
- A saved per-page layout from a newer or broken build: the page falls back to its default layout.
- Selecting a stock while the Chart page is hidden: on switching, the chart has the right symbol and correct size (no zero-width chart).
- Ctrl/⌘+number while typing in the search box or a form: does not switch pages.

---

### Task 1: Markets overview endpoint (engine)

**Files:**
- Create: `engine/app/market/overview.py`
- Modify: `engine/app/config.py` (add `NIFTY50`, `INDEX_STRIP`, `GLOBAL_INDICES`)
- Modify: `engine/app/api/watch.py` (add route) 
- Test: `engine/tests/test_overview.py`

**Interfaces:**
- Produces: `GET /api/markets/overview?universe=nifty50|mine&window=21|63|252` →
  `{"online": bool, "as_of": str|None, "indexes": [Index], "global": [Index], "movers": {"universe": str, "gainers": [Mover], "losers": [Mover]}}`
  where `Index = {"symbol","name","region","last","change_pct","series": [{"date","pct"}]}` (`series` only in `indexes`, percent change from the window's first close) and `Mover = {"symbol","name","last","change_pct"}`, 5 each, sorted by `change_pct`.
- Produces: `overview.quotes(symbols: list[str], fetcher: QuoteFetcher | None = None) -> dict[str, tuple[float, float]]` returning `(last, prev_close)`; `QuoteFetcher = Callable[[list[str]], dict[str, tuple[float, float]]]`. The app sets `app.state.quote_fetcher` (None in production).

Values: `INDEX_STRIP = ["^NSEI", "^BSESN", "^NSEBANK"]` plus the saved benchmark if different. `GLOBAL_INDICES` = `[("^NSEI","NIFTY 50","India"), ("^BSESN","SENSEX","India"), ("^GSPC","S&P 500","US"), ("^IXIC","NASDAQ","US"), ("^DJI","DOW JONES","US"), ("^FTSE","FTSE 100","UK"), ("^GDAXI","DAX","Europe"), ("^FCHI","CAC 40","Europe"), ("^N225","NIKKEI 225","Asia"), ("^HSI","HANG SENG","Asia"), ("000001.SS","SHANGHAI","Asia"), ("^STI","STRAITS TIMES","Asia")]`. `NIFTY50` = the 50 current constituents as `.NS` symbols, with a comment that it is maintained by hand.

- [ ] **Step 1: Write the failing tests** in `engine/tests/test_overview.py`, with a fake quote fetcher on `app.state.quote_fetcher` and `history.fetch` replaced by `conftest.fake_fetch`:
  - `test_overview_returns_indexes_global_and_movers`: universe `nifty50`; `len(global) == 12`; each index has `change_pct == pytest.approx((last/prev - 1))`; `indexes[0]["series"][0]["pct"] == 0`; gainers sorted descending, losers ascending, 5 each.
  - `test_mine_universe_is_holdings_plus_watchlist`: import the fixture CSV, star one symbol via `PUT /api/watchlist/INFY.NS`; movers symbols ⊆ {RELIANCE.NS, TCS.NS, INFY.NS}.
  - `test_quotes_are_cached_for_five_minutes`: two calls → fetcher called once; after monkeypatching `overview.time.monotonic` +301 s → called twice.
  - `test_offline_returns_online_false`: fetcher raises `OSError` → 200 with `online is False`, empty lists.
  - `test_bad_universe_or_window_is_400_or_422`.
- [ ] **Step 2: Run** `npm run engine:test -- tests/test_overview.py` — expect failures (module missing).
- [ ] **Step 3: Implement** `overview.py`: `quotes()` with a module-level `_CACHE: dict[tuple[str,...], tuple[float, dict]]`, TTL 300 s via `time.monotonic()`; default fetcher uses one `yfinance.download(symbols, period="5d", interval="1d", group_by="ticker", progress=False, threads=False)` and takes the last two non-null closes. `build(session, universe, window, fetcher) -> dict`; index series from `history.refresh_symbol` (`with_actions=False`) + `history.load_prices`, last `window` closes. Names for movers from `Instrument.name`, else the ticker. Route in `watch.py` (already token-protected router) runs `build` in `asyncio.to_thread`.
- [ ] **Step 4: Run** `npm run engine:test` — all pass, including `test_no_execution_surface`.
- [ ] **Step 5: Live check on the Mac:** call `overview.quotes(config.NIFTY50)` once and confirm 50 entries; fix any symbol Yahoo does not know.

### Task 2: Theme and fonts

**Files:** Modify `apps/web/src/index.css`; all `apps/web/src/**/*.tsx` (class rename).

- [ ] **Step 1:** In `@theme`, add `--font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;` and `--color-accent: #14d9a5`; set `--color-bg: #0b0e11`, `--color-panel: #12161b`, `--color-raise: #1a2027`, `--color-line: #232a33`, `--color-ink: #e6e9ee`, `--color-dim: #8a94a3`, `--color-up: #14d9a5`, `--color-down: #ff4d6d`; keep `--color-amber`. Body uses `--font-sans`, 12.5px; `table.grid-table` and `.font-mono` use `--font-mono`.
- [ ] **Step 2:** Rename accent uses: every `amber` utility (`text-amber`, `bg-amber`, `border-amber`, `hover:*-amber`, `focus:*-amber`, `/amber`) becomes `accent`, then restore `amber` only where it marks a warning: lines rendering `⚠`, the CHECK SPLITS button, BSE-listing notice in ChartPane, "experimental" badges. List the restored spots in the task notes.
- [ ] **Step 3:** Card look for flexlayout: tabsets get `margin: 4px; border-radius: 8px; border: 1px solid var(--color-line); overflow: hidden`; layout background `--color-bg`, splitter 6px transparent with accent on hover; tab strip text tabs with the selected tab as a rounded pill (`background: var(--color-raise); color: var(--color-ink); border-radius: 999px`), font `--font-sans` 11px, letter-spacing 0.04em.
- [ ] **Step 4: Verify:** `npm run build` passes; grep shows no `amber` outside the restored warning spots.

### Task 3: Shell: pages, rail, top bar

**Files:**
- Create: `apps/web/src/layout/pages.ts`, `apps/web/src/layout/Rail.tsx`, `apps/web/src/layout/TopBar.tsx`, `apps/web/src/layout/PageWorkspace.tsx`, `apps/web/src/layout/icons.tsx`
- Modify: `apps/web/src/state/store.ts`, `apps/web/src/App.tsx`, `apps/web/src/ribbon/Palette.tsx`
- Delete: `apps/web/src/layout/Workspace.tsx`, `apps/web/src/ribbon/Ribbon.tsx` (contents redistributed)

**Interfaces:**
- Produces: `type PageId = "markets" | "portfolio" | "chart" | "analytics" | "plan" | "settings"`; `PAGES: { id: PageId; label: string; icon: (p: {className?: string}) => JSX.Element; layout?: IJsonModel }[]` in rail order; `PANES: Record<string, () => JSX.Element>` (all existing panes plus `stock`, `updates`, `indexes`, `global`, `movers` from Tasks 4–5).
- Store: `page: PageId`, `setPage(p: PageId)`, `layoutEpochs: Partial<Record<PageId, number>>`, `resetLayout(page?: PageId)` (no argument = current page; `"all"` handled by Settings via a separate `resetAllLayouts()`). `select(symbol)` and `openSymbol(...)` also set `page: "chart"` when the symbol is non-null.
- Default layouts exactly as the spec table (Markets row 1: indexes 55 / global 45; row 2: heatmap 40 / news 35 / movers 25. Portfolio: holdings 65 / tabs trades, actions, watchlist, history 35. Chart: chart 70 / column stock 55 + updates 45. Analytics: risk+stress 28 / performance+covariance+optimizer 48 / insight 24. Plan: plan 50 / wealth 50).

- [ ] **Step 1:** `PageWorkspace({ page })` loads `qt.layout.<page>.v1`, falls back to the default when parsing or `Model.fromJson` throws, saves on change; key includes the page's epoch.
- [ ] **Step 2:** `App` renders `TopBar`, the notice bar, then a row: `Rail` + a container holding one `PageWorkspace` per dockable page and `SettingsPage` (Task 6), each wrapped in a `div` with `hidden` unless active.
- [ ] **Step 3:** `Rail`: 56px column, five page buttons top, Settings bottom; `aria-label` = page label, `aria-current="page"` on the active one, tooltip via `title`. Global keydown: Ctrl/⌘+1…6 → `setPage`, ignored when the target is an input, textarea, select or contenteditable.
- [ ] **Step 4:** `TopBar`: QT mark + READ-ONLY tag, VALUE / DAY P&L / UNREALIZED from `live.portfolio` falling back to `portfolio` (with `Flash`), `SearchBox`, CHECK SPLITS (when pending, amber), feed light and label (logic moved from Ribbon), REFRESH, IMPORT.
- [ ] **Step 5:** Palette: add "Go to <label>" items for all six pages; "Connect…" items call `setPage("settings")` with section `connections` (Task 6 interface); "Reset layout" resets the current page.
- [ ] **Step 6: Verify:** `npm run build`; then Task 7's walkthrough steps for rail and keys.

### Task 4: Chart page cards

**Files:** Create `apps/web/src/panes/StockPanel.tsx`, `apps/web/src/panes/PriceUpdates.tsx`; Modify `apps/web/src/state/store.ts`.

**Interfaces:**
- Store: `ticks: Record<string, { ts: number; price: number }[]>`, filled in the `openTicks` callback: for each quote whose `ltp` differs from the last stored price, unshift `{ ts, price: ltp }`, cap 50 per symbol.
- `StockPanel` reads `selected`, the matching `Holding`, `live.quotes[selected]`, and `api.prices(selected, 365)` once per symbol for the 52-week high/low (blank when no bars).

- [ ] **Step 1:** `StockPanel`: header with name, ticker, exchange, last price and day change (teal/pink); rows QUANTITY, AVG COST, VALUE, UNREALIZED, REALIZED, WEIGHT, BETA, SHARE OF VAR (`component_var / metrics.var`), 52W HIGH, 52W LOW; star and eye toggles (existing `toggleStar`/`toggleWatch`). Not held: price facts plus the line "Not in your portfolio". No inputs.
- [ ] **Step 2:** `PriceUpdates`: title "PRICE UPDATES", note "Live price snapshots for your holdings, not individual trades."; table TIME (HH:MM:SS), PRICE, CHANGE vs previous row (teal/pink). Empty states: feed off → "Live feed is off. Choose a price source in Settings → Connections."; not held → "Live updates cover the stocks you hold."
- [ ] **Step 3: Verify:** `npm run build`; walkthrough in Task 7 checks both empty states and a populated list.

### Task 5: Markets page cards

**Files:** Create `apps/web/src/panes/IndexesCard.tsx`, `apps/web/src/panes/GlobalMarketsCard.tsx`, `apps/web/src/panes/MoversCard.tsx`, `apps/web/src/state/markets.ts`; Modify `apps/web/src/api/client.ts`, `apps/web/src/api/types.ts`.

**Interfaces:**
- Consumes Task 1's response. Client: `api.marketsOverview(universe: "nifty50" | "mine", window: 21 | 63 | 252): Promise<MarketsOverview>`.
- `useMarkets()` hook in `state/markets.ts`: one shared request per (universe, window), refreshed every 5 minutes while the Markets page is visible, holds `{ data, loading, error }`; universe and window persisted in localStorage (`qt.markets.universe`, `qt.markets.window`).

- [ ] **Step 1:** `IndexesCard`: legend chips (name, last, change %), a lightweight-charts line series per index from `series` (percent axis), 1M/3M/1Y switch via `Seg`.
- [ ] **Step 2:** `GlobalMarketsCard`: grid grouped by region; each tile name, last, change %, background tinted teal/pink by sign with intensity capped at ±3%.
- [ ] **Step 3:** `MoversCard`: GAINERS / LOSERS tables (name, price, % change), universe switch NIFTY 50 / MY STOCKS; row click → `openSymbol`.
- [ ] **Step 4:** Offline (`online: false`) → each card shows "Market data is offline" with a RETRY button.
- [ ] **Step 5: Verify:** `npm run build`.

### Task 6: Settings page

**Files:** Create `apps/web/src/settings/SettingsPage.tsx` and one file per section in `apps/web/src/settings/` (`RiskSection.tsx`, `ConnectionsSection.tsx`, `DisplaySection.tsx`, `AiSection.tsx`, `NewsSection.tsx`, `DataSection.tsx`, `AboutSection.tsx`); Modify `apps/web/src/ribbon/ConnectionsDialog.tsx` (export its body as `ConnectionsPanel`, delete the dialog wrapper), `apps/web/src/panes/NewsPane.tsx` (export `SourcesPanel`), `apps/web/src/panes/InsightPane.tsx` (extract `InsightKeyForm`, pane shows a "Manage key in Settings" link when not configured), `App.tsx` (drop `ConnectionsDialog`).

**Interfaces:**
- Store: `settingsSection: SectionId`, `openSettings(section?: SectionId)` (sets page and section). `SectionId = "risk" | "connections" | "display" | "ai" | "news" | "data" | "about"`.

- [ ] **Step 1:** Layout: 220px section list (active section accent bar), content column max-width 820px, each section a card with a heading and one-line description as in the reference.
- [ ] **Step 2:** Risk: `BenchmarkPicker`, VaR confidence (95/99), VaR horizon (1/2/3/5/10), risk lookback (existing options), covariance horizon and window (existing options), risk-free rate (number input in %, saved as fraction via `setParam`, validated 0–20).
- [ ] **Step 3:** Connections: `ConnectionsPanel`. Display: CCY select (moved from Ribbon), "Reset all layouts". AI: `InsightKeyForm`. News: `SourcesPanel` without its close button. Data: Import (opens dialog), Export ledger CSV, Bonds editor (opens dialog), price cache summary from `api.cache()`. About: engine version from `/health`, feed status, the read-only statement.
- [ ] **Step 4: Verify:** `npm run build`; every former ribbon control is reachable (checked in Task 7).

### Task 7: Verification walkthrough

**Files:** Create `scripts/ui-walkthrough.mjs` (Playwright, run in the cloud container against a stand-in engine; not shipped).

- [ ] **Step 1:** Copy the working tree's diff from the Mac into the container checkout at the same commit and apply it.
- [ ] **Step 2:** Start the engine with fake price and quote fetchers and the fixture ledger; serve `apps/web/dist` with `vite preview`.
- [ ] **Step 3:** Script visits every page via the rail and via Ctrl+1…6, asserts each pane's heading renders, checks Ctrl+2 typed in the search box does not switch page, selects a holding and asserts the Chart page shows it at non-zero width, checks Stock panel and Price updates empty states, sets the quote fetcher to fail and checks the Markets offline state, and asserts no visible button's text matches `/\b(buy|sell|place|order|trade now)\b/i` except the ledger form's BOUGHT/SOLD.
- [ ] **Step 4:** Screenshots of all six pages at 1440×900 for the user.
- [ ] **Step 5:** `npm run engine:test` and `npm run build` on the Mac; report results. Do not commit.
