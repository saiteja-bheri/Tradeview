# Terminal redesign: pages, rail and new look

Date: 2026-11-17. Status: draft for approval.

## Intent

The owner supplied three reference screens (a chart workspace with a side
panel, an account settings page, and a markets dashboard) as a **template, not
a replica**. They want Quant Terminal to take on that structure and feel: a
slim icon rail on the left that switches between pages, a top bar carrying
the portfolio figures and search, card-style panels, a markets overview, and
a settings page that gathers the controls now crowded into the ribbon.

Today the whole app is one screen: 16 tabs in three dockable columns
(`apps/web/src/layout/Workspace.tsx`, flexlayout-react) under a dense ribbon
(`apps/web/src/ribbon/Ribbon.tsx`) holding search, benchmark, VaR confidence,
VaR horizon, CHECK SPLITS, COMMANDS, CONNECT, REFRESH, CCY, IMPORT and the
feed status light.

## Goals

- Left icon rail switching between six pages (below), with tooltips and the
  active page highlighted.
- Each page keeps today's drag, dock, resize and maximize (approach B), with a
  default arrangement in the spirit of the references, remembered per page.
- A top bar: portfolio value, day P&L, unrealized P&L, search, feed status,
  REFRESH and IMPORT. Nothing else.
- A new Markets page built from existing panes plus three new cards.
- A Settings page with a section list on the left, absorbing the ribbon's
  parameter controls and the CONNECT dialog.
- A new visual style taken from the references (see Look).
- Every existing feature stays reachable. No pane is removed.

## Non-goals

- No change to any calculation, endpoint behaviour or data stored, except the
  new read-only Markets endpoint below.
- No new broker or price source.
- No mobile or narrow-window layout beyond today's minimum (1000 x 600).
- Not a pixel copy of the references: no account avatar, no "Available funds",
  no logos or names from them.

## Anti-goals (failure even if it works)

- **Anything that looks like a way to trade.** The references' Buy/Sell
  panel, order type, quantity, stop price, "Buy MSFT" button, buying power and
  available funds must not appear in any form. The app stays strictly
  read-only, and its existing tests that forbid order-like routes stay green.
- Losing an existing feature or a setting, or resetting the user's ledger.
- Numbers that no longer line up in columns (tabular digits are required).
- A slower app: switching pages must feel instant and must not refetch data
  the store already holds.

## Constraints

- Electron + React 19 + Vite + Tailwind 4 + zustand; flexlayout-react for
  docking; lightweight-charts for charts. No new UI framework.
- The production build's content security policy (`apps/web/vite.config.ts`)
  stays as is: no remote fonts, no remote images, no inline scripts. Any font
  must be bundled locally or come from the system.
- TradingView's free embed has no NSE data (NSE stocks use the Yahoo chart;
  see `apps/web/src/chartSymbol.ts`).
- Live feeds give last-traded prices, not individual trades, so there is no
  true time-and-sales tape.
- Saved layouts in localStorage under `qt.layout.v9` will no longer match; the
  new layouts use new keys and the old key is ignored (not deleted).

## Approaches considered

| | Approach | Trade-off |
|---|---|---|
| A | Fixed pages, a set arrangement of cards per page | Closest to the references and calmest; loses drag and dock. |
| **B** | **Pages, each with its own dockable layout (chosen)** | Looks like A out of the box and keeps the flexibility an analysis terminal benefits from; more work, as flexlayout must be restyled to look like cards. |
| C | Reskin the single screen; rail only jumps to tabs | Least work; no page structure, which is what the references are built around. |

The owner chose **B**.

## Design

### Shell

```
┌──┬──────────────────────────────────────────────────────────────────────┐
│QT│ VALUE ₹7,024  DAY +₹120 +1.7%  UNREAL −₹20,476   [ search…  / ]  ● UPSTOX LIVE  REFRESH  IMPORT │
├──┼──────────────────────────────────────────────────────────────────────┤
│◉ │                                                                      │
│▦ │                     current page (dockable cards)                    │
│📈│                                                                      │
│⚖ │                                                                      │
│◎ │                                                                      │
│  │                                                                      │
│⚙ │                                                                      │
└──┴──────────────────────────────────────────────────────────────────────┘
```

- **Rail** (about 56 px wide): icons for Markets, Portfolio, Chart, Analytics,
  Plan at the top; Settings at the bottom. Keyboard: Ctrl/⌘+1…6. The command
  palette (Ctrl/⌘+K) gains "Go to <page>" entries.
- **Top bar**: portfolio value, day P&L and unrealized P&L (flashing on change
  as today), the existing SearchBox, the CHECK SPLITS button when reviews are
  pending, the feed status light, REFRESH, IMPORT. A small "READ-ONLY" tag
  stays next to the logo.
- Picking a stock anywhere (search, holdings, heat map, movers) selects it as
  today and switches to the Chart page.

### Pages and default arrangements

Every existing pane keeps its component; only where it lives changes.

| Page | Default arrangement |
|---|---|
| **Markets** | Row 1: Indexes card (new), Global markets card (new). Row 2: Heat map, News, Top movers card (new). |
| **Portfolio** | Left: Holdings (wide). Right column tabs: Trades, Corp actions, Watchlist, History. |
| **Chart** | Left: Chart (wide). Right column: Stock panel (new, top), Price updates (new, bottom). |
| **Analytics** | Left tabs: Risk, Stress test. Centre tabs: Performance, Covariance, Optimizer. Right: AI insight. |
| **Plan** | Plan (SIP) and Wealth (deposits, PPF, EPF, NPS, insurance and the projection) side by side. *Builder's call: Wealth moves here from Portfolio so each pane lives on one page.* |
| **Settings** | Not dockable: a fixed page (see below). |

Each dockable page stores its layout under `qt.layout.<page>.v1`. A "Reset
layout" command resets the current page only.

### New cards

- **Stock panel** (Chart page, where the references put Buy/Sell): for the
  selected symbol, read-only facts the app already has: last price and day
  change, your quantity, average cost, value, unrealized and realized P&L,
  weight, beta, share of VaR, 52-week high/low from the cached daily closes,
  and star/watch toggles. When the stock is not held, it shows price facts
  and a "Not in your portfolio" line. No inputs that resemble an order.
- **Price updates** (Chart page, in place of Time & Sales): the last 50 live
  price updates for the selected symbol from the existing tick WebSocket,
  newest first, with time, price and change since the previous update.
  Titled "PRICE UPDATES" with a one-line note that these are price snapshots,
  not individual trades. Empty state when the feed is off.
- **Indexes card** (Markets): NIFTY 50, SENSEX, NIFTY BANK and the user's
  benchmark, each with last level and day change, and a line chart of daily
  closes over a selectable 1M/3M/1Y window, normalised to percent change so
  the lines share one axis.
- **Global markets card** (Markets): a grid of world indices grouped by region
  (India, US, UK, Europe, Asia) with level and day change, coloured
  up/down. Proposed list: ^NSEI, ^BSESN, ^GSPC, ^IXIC, ^DJI, ^FTSE, ^GDAXI,
  ^FCHI, ^N225, ^HSI, 000001.SS, ^STI. A world map is not drawn (see
  builder's choices).
- **Top movers card** (Markets): biggest gainers and losers of the day with
  name, price and % change, from a universe the user toggles between
  "NIFTY 50" and "My stocks" (holdings plus watchlist).

### New engine endpoint (read-only)

`GET /api/markets/overview?universe=nifty50|mine` returns index quotes for the
Indexes and Global cards and the movers list. Quotes come from Yahoo daily
data (last two closes), cached in the existing price cache and refreshed at
most every 5 minutes. The NIFTY 50 constituent list is a fixed list in
`engine/app/config.py`, updated by hand. Covered by tests with a fake fetcher,
like the rest of the engine. Its path contains no word the read-only route
test bans.

### Settings page

Fixed layout: section list on the left, content on the right, as in the
reference.

| Section | Contents (moved from) |
|---|---|
| Risk | Benchmark picker, VaR confidence, VaR horizon, risk lookback, covariance horizon and window, risk-free rate (ribbon, Risk pane, Covariance pane keep their quick controls too) |
| Connections | Everything in today's CONNECT dialog, inline (dialog removed; palette entry opens this section) |
| Display | Display currency (CCY), number format, reset all layouts |
| AI insight | Gemini key status, save and remove (from the AI insight pane; pane keeps a link here) |
| News | News sources on and off (from the News pane's sources panel) |
| Data | Import (opens the existing import dialog), export ledger CSV, bonds editor (opens the existing dialog), price cache summary |
| About | Version, engine status, data folder path, the read-only statement |

### Look

- Background near-black (#0b0e11-ish); cards one step lighter with an 8 px
  radius, a hairline border and 12 px padding; gaps between cards instead of
  shared borders.
- Accent teal (around #14d9a5) for highlights, selection and gains; pink-red
  (around #ff4d6d) for losses; amber kept only for warnings.
- Interface text in a sans-serif (system UI stack, or Inter bundled locally if
  the system font looks off); all numbers use tabular figures. Tables may stay
  monospace.
- Tab strips restyled as in the reference chart header: text tabs, the active
  one marked with a rounded pill.
- Contrast: body text at least 4.5:1 on its background.

## Decided by the owner

- Approach B: pages with docking inside each.
- The references are a template, not a replica.
- The app stays read-only (standing instruction).
- The reference look (see Look), replacing amber and all-monospace text.

## Proposed, open to correction

- The six pages and what sits on each.
- Stock panel replacing Buy/Sell; Price updates replacing Time & Sales.
- Top movers universe: NIFTY 50 or the user's own stocks, with a toggle.

## Left to the builder

- Icons (inline SVG, drawn for this app; no icon font, no remote images).
- Exact colour values, provided contrast holds.
- World map: drawing one needs map shapes bundled locally; the grid by region
  is the default. A map can be added later if wanted.
- How flexlayout's theme variables are overridden to produce the card look.
- Whether page switching unmounts inactive pages (preferred: keep them
  mounted and hidden, so charts and scroll positions survive).

## Testing

- Engine: tests for the overview endpoint (quotes, movers per universe, cache
  reuse, offline behaviour); the existing read-only tests unchanged and green.
- UI: type-check and build; a Playwright walkthrough against a stand-in engine
  that visits every page, checks each pane renders, switches pages by rail
  and keyboard, and confirms no button on any page is labelled as an order
  (buy, sell, place, order, trade now). *Builder's call: the Trades pane's
  ledger form, which records a past trade as BOUGHT or SOLD, is exempt; it
  writes only to the local ledger and is labelled as record keeping.*
- The Heat map pane is reused as it is (holdings and watchlist); a
  market-wide heat map is not part of this work. *Builder's call.*
