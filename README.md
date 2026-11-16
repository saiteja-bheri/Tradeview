# Quant Terminal

A read-only desktop quant terminal: an Electron + React front end over a local
Python engine (FastAPI + SQLite) that computes all risk metrics itself. It has
no order routing of any kind.

Runs on macOS and Windows. All commands below are the same on both.

## Requirements

- Node.js 20 or newer
- Python 3.11 or newer (on Windows, install from python.org so the `py` launcher exists)

## Run the app

```bash
npm install            # once: UI and Electron dependencies
npm run engine:setup   # once: Python engine
npm run dev            # desktop app with hot reload
npm start              # desktop app from a production build of the UI
```

The desktop app starts the engine itself on a free local port and stops it on
quit. Use **IMPORT CSV** in the ribbon to load an Upstox trade book. The search
bar in the ribbon finds any NSE or BSE stock by company name or ticker (press
`/` to focus it); without a network it still searches the stocks in your ledger.

The app never places trades and has no way to. The **TRADES** tab is a ledger:
**+ ADD TRADE** records a trade you made elsewhere, **EDIT** and **REMOVE**
correct entries, and **EXPORT CSV** saves the whole ledger. An exported file can
be edited in a spreadsheet and imported again: its `Ledger Id` column ties each
row to its entry, so changed rows are updated and new rows are added.

**BENCH** in the ribbon picks the benchmark for beta and alpha: a built-in list
of NSE and BSE indices and ETFs, or any index, ETF, mutual fund or stock found
by search. The covariance tab has its own return horizon (1, 2, 3, 5 or 10
days), and **LOOKBACK** in the risk tab sets how much history the ratios use
(1 month to 5 years).

## Build an installer

```bash
npm run package        # .dmg on macOS, .exe installer on Windows, in release/
```

Each installer has to be built on its own system, because the Python engine is
frozen into a native binary (with PyInstaller) and bundled into the app. The
installed app needs neither Python nor Node. `.github/workflows/release.yml`
builds both on GitHub (run it from the Actions tab or push a `v*` tag).

The builds are not code-signed. On macOS, open the app the first time with
right-click > Open; on Windows, choose "More info" > "Run anyway" on the
SmartScreen prompt. Signing needs an Apple Developer ID and a Windows
code-signing certificate. The first launch after installing can take up to a
minute while the system checks the engine; later launches take a second or two.

## Engine on its own

```bash
npm run engine:setup   # create engine/.venv and install dependencies
npm run engine:test    # run the test suite
npm run engine:dev     # start the engine on http://127.0.0.1:8765
```

Interactive API docs: http://127.0.0.1:8765/docs

| Variable | Purpose | Default |
| --- | --- | --- |
| `QT_PORT` | engine port | `8765` |
| `QT_TOKEN` | if set, every `/api` call must send it as `X-QT-Token` | unset |
| `QT_DATA_DIR` | where the SQLite ledger lives | per-user app data folder |
| `QT_FEED` | live prices: `auto`, `upstox`, `yahoo` or `off` | `auto` |
| `QT_UPSTOX_TOKEN` | Upstox token; overrides the one saved in the app | unset |
| `QT_GEMINI_API_KEY` | Gemini API key; overrides the one saved in the app | unset |
| `QT_GEMINI_MODEL` | Gemini model used for memos | `gemini-3.8-flash` |

## Live prices

The engine streams quotes and a mark-to-market snapshot over
`ws://127.0.0.1:<port>/ws/ticks`. Risk metrics stay based on daily closes.

Pick the source under **CONNECT > LIVE PRICES FROM**. `AUTO` keeps the original
behaviour (Upstox when its token is saved, otherwise Yahoo). The `QT_FEED`
environment variable (`auto | upstox | zerodha | groww | bse | yahoo | off`)
overrides the choice.

**Upstox (real time).** Click **CONNECT** in the ribbon and paste an Upstox
*Analytics Token*. It is read-only, valid for one year, and cannot place or
change orders, which matches this app's no-execution rule. Create it in the
Upstox Developer Apps page under the Analytics tab. The token is saved in the
system credential store (macOS Keychain, Windows Credential Manager), never in
the database, and the feed switches to Upstox straight away. A daily OAuth
access token also works but has to be replaced every day.

**Yahoo (delayed).** With no token, quotes are polled from Yahoo every 15
seconds and the ribbon shows DELAYED. `QT_FEED=upstox` disables this fallback.

The engine only ever sends GET requests to Upstox: the feed authorize call and
the public instrument list.

**Zerodha (real time).** Streams over Kite's WebSocket. Needs the paid Kite
Connect plan; the free Personal plan has no market data.

**Groww (last traded price).** Polled every few seconds through Groww's
official SDK. Groww's LTP call has no previous close, so day P&L stays blank.

**BSE India (experimental).** BSE publishes no official API. Prices come from
the community `bse` package (BseIndiaApi) and can stop working when BSE changes
its site. Scrip codes are looked up by ISIN. **SYNC FROM BSE** in the Corp
Actions pane adds BSE's own dividends, bonus issues and splits for every stock
you have traded; anything already recorded for that date is left alone.

## What you can hold

| Kind | How to add it | Prices from | Income |
|---|---|---|---|
| Stocks, ETFs | ticker (INFY, NIFTYBEES) | Yahoo, or the live source | dividends (Yahoo, BSE, manual) |
| Gold ETFs, Sovereign Gold Bonds | ticker (GOLDBEES, SGBAUG28V) | Yahoo, or the live source | SGB interest as a manual dividend |
| Mutual funds | search the name, or `MF:<AMFI scheme code>` | AMFI daily NAV via mfapi.in | IDCW payouts as manual dividends |
| Gold, silver, crude and other commodities | `CMDTY:GOLD`, `CMDTY:SILVER`, `CMDTY:CRUDE`… | international futures × USD/INR, per gram / kg / barrel | none |
| Bonds, G-secs, NCDs | add terms under **Add or edit bonds** (Ctrl+K), then trade `BOND:<ID>` | the price you set | coupons, generated from the terms |

`CMDTY:` prices are an international equivalent; physical gold in India usually
costs a few percent more (import duty and GST). Each holding is tagged with an
asset class (override with `PUT /api/instruments/<symbol>/asset-class`), and the
Risk pane shows the allocation.

**Returns.** Every holding and the whole portfolio get a total return
(realized + unrealized + dividends and coupons, over money invested) and an
XIRR (annualised, money-weighted, like a fund statement). Brokerage and taxes
are not in the ledger, so both are before costs.

## Brokers

Every broker integration is read-only. Nothing in the engine can place,
modify or cancel an order, and the test suite scans the source to keep it that
way. Credentials are kept in the system credential store and never returned to
the UI.

| Broker | Trade history | Sync (today's trades, holdings check) | Live prices |
|---|---|---|---|
| Upstox | IMPORT CSV (trade book) | none (the Analytics Token can't read the account) | yes |
| Zerodha | IMPORT CSV (Console > Reports > Tradebook, CSV or Excel) | trades + holdings, any Kite plan | Kite Connect plan |
| Groww | IMPORT CSV (stock order report, CSV or Excel) | holdings | yes, polled |

IMPORT CSV recognises the broker from the column headings. **SYNC** under
CONNECT compares each broker's holdings with the positions built from that
broker's trades in the ledger, matching by ISIN so NSE and BSE listings of
the same company line up. Differences appear as warnings, and usually mean
older trades are missing from the import.

**Zerodha login.** Save the API key and secret from developers.kite.trade,
click **OPEN KITE LOGIN**, sign in, then paste the address Kite redirects you
to (it contains `request_token=`) and press **LOG IN**. Sessions end at about
06:00 every morning.

**Groww login.** Save the API key plus either the TOTP secret (the app then
logs in each day without asking) or the API secret, then press **LOG IN**.

Groww and BSE need optional packages (growwapi, pyotp, bse):

```bash
cd engine
.venv/Scripts/pip install -e ".[brokers]"     # Windows; use .venv/bin/pip on macOS
```

## Splits, bonus issues and other corporate actions

Splits, bonus issues and dividends come from Yahoo on every price refresh,
from BSE with **SYNC FROM BSE**, or by hand; one from BSE or entered by hand
wins over Yahoo's for the same date. Every position is rebuilt from the trades
with each split or bonus multiplying the shares held before its ex-date.

Some brokers restate old trades after a split, and applying the split again
would double the shares. So for every split or bonus that falls between a
trade's date and the day that trade was uploaded, the app asks once
(**CHECK SPLITS** in the ribbon; it opens by itself after an import) whether
the file lists the trade as originally traded or already adjusted. Each
question carries a suggested answer worked out from the prices: Yahoo's
historical closes are split-adjusted, so a file price about N times Yahoo's
close means the file is in pre-split terms. Until answered, the action is
applied. An action after the upload date can't be in the file and is applied
without asking. Answers survive later price refreshes.

## International stocks

Any Yahoo listing works: AAPL, MSFT, VOD.L, 7203.T, SAP.DE. Pick it from the
search (a bare ticker you type still means NSE). Enter trades in the listing's
own currency. Everything is converted to rupees the way an Indian investor
experiences it: each trade at the exchange rate on its date, each dividend at
the rate on its ex-date, each day's price at that day's rate (London prices in
pence are handled). Returns, XIRR and risk metrics therefore include the
currency move. Holdings show the price and average cost in the listing's
currency and the value in rupees.

## Local price cache

Daily prices for every stock you hold, star or open are stored in the local
database (`ledger.sqlite3` in the data folder). A symbol refreshed today is
served from the file with no download; otherwise only the days since the last
stored bar are fetched. The whole history is downloaded again only for a new
symbol, a longer window than is stored, or a new split or dividend (which makes
Yahoo restate every adjusted close). The WATCHLIST pane shows how many requests
were served locally and exports any cached series as CSV.

## Watchlist and optimizer

Star (*) any stock from the search, the holdings or the watchlist. The
OPTIMIZER runs a mean-variance (Markowitz) optimisation of the starred stocks,
optionally with your holdings: maximum Sharpe ratio, minimum risk, equal
weight and your current mix, with the efficient frontier. Returns are in
rupees, the covariance uses Ledoit-Wolf shrinkage, and portfolios are
long-only with a cap per stock. Expected returns are past averages, the least
reliable input, which is why the minimum-risk portfolio (which ignores them)
is shown beside the maximum-Sharpe one.

## Stock search and display currency

The search box (press `/`) finds stocks on any market. Every result shows
where it trades and its currency (RELIANCE · NSE · INR, AAPL · NASDAQ · USD,
VOD.L · LSE · GBp, 7203.T · TOKYO · JPY), grouped by market. The chips at the
top (or Tab) narrow the search to India, US, UK, Europe, Asia or funds, and the
choice is remembered. Over-the-counter copies and duplicate cross-listings of
the same company are folded into the primary listing.

**CCY** in the ribbon sets the currency money is shown in: INR, USD, EUR, GBP,
JPY, AED, SGD, AUD, CAD, CHF, HKD, or AUTO (the currency most of the portfolio's
value is in). Only the display changes: the ledger and every calculation stay
in rupees, converted at the latest cached rate.

## Stress test

The STRESS TEST tab shows what a market downturn would cost, using the same
return history, covariance and correlations as the risk metrics:

* **Market falls**: for a fall in the benchmark over a week, month or quarter,
  each holding moves by its beta times the fall, with a 90% range from the
  covariance that remains once the market move is known.
* **Past crises**: the 2008 crash, the 2013 taper tantrum, the 2015-16 China
  slowdown, the 2020 COVID crash and the 2022 sell-off replayed on today's
  holdings. A holding uses its own price move when its history covers the
  period (in rupees, so currency moves count) and its beta otherwise. The first
  run downloads long history once; the cache keeps it.
* **Monte Carlo**: 10,000 simulated outcomes with fat tails, giving the
  1-in-20 and 1-in-100 losses, the average of the worst 5%, and the chance of
  losing 5, 10, 20 or 30%.
* **Correlation breakdown**: VaR again with every correlation moved halfway to
  1, because in sell-offs stocks tend to fall together.

## Importing trades

**IMPORT CSV / EXCEL** opens a page listing the exact headings each format
needs. Upstox, Zerodha and Groww reports are recognised as they come, CSV or
Excel. Any other file works when it has these headings, in any order (extra
columns are ignored, and rows above the headings are skipped):

| Heading | Needed | Format |
|---|---|---|
| Date | required | DD-MM-YYYY or YYYY-MM-DD |
| Time | optional | HH:MM or HH:MM:SS |
| Symbol | required | INFY, RELIANCE, AAPL, VOD.L |
| Exchange | optional | NSE, BSE, NASDAQ, NYSE, LSE... (blank = NSE) |
| Side | required | BUY or SELL (or a negative Quantity for sells) |
| Quantity | required | number of shares |
| Price | required | per share, in the listing's currency (or give Amount) |
| Amount | optional | quantity x price |
| Trade ID | optional | stops duplicates on re-import |
| ISIN, Name | optional | |

Common variations of each heading are recognised (Qty, Units, Ticker, Rate,
Buy/Sell, Txn Date...). If a column still isn't recognised, the import page
lets you point each field at the right column before importing. DOWNLOAD
TEMPLATE gives a ready-to-fill file.

## News

The NEWS tab covers the stocks you hold, watch (eye) or star, plus market news
for the benchmark. Stocks that are only in History get no news downloads.
Headlines come from free public feeds that need no keys. Each feed is
downloaded at most every 30 minutes and kept in the local database.

| Source | How it is used |
| --- | --- |
| Yahoo Finance | Headlines per stock, plus the results and dividend calendar |
| Google News | A search per stock by company name (last 7 days), from Google's many outlets |
| Economic Times, Livemint, Business Standard, BusinessLine, CNBC-TV18 | Indian market wires, one download each |
| MarketWatch, CNBC | US market wires, one download each |

Wire stories are matched to your stocks by company name or ticker. Stories
that mention none of your stocks appear as market news (the newest 10 per
wire), and only from wires in the same region as your benchmark. The same
story from several sources is shown once, with every source listed.

- **SOURCES** turns a feed off. A feed that is off is not downloaded.
- The **SHOW** chips hide a source's stories without changing what is downloaded.

The idea of aggregating many outlets and mapping stories to tickers comes from
[realtime-newsapi](https://github.com/janlukasschroeder/realtime-newsapi).
Its free newsfilter.io endpoint now refuses requests (HTTP 403), so it is not
used. Moneycontrol's public RSS stopped updating, so it is not used either.

## AI insight

The **AI INSIGHT** tab (right-hand panel, next to RISK and STRESS TEST) writes a
short hedging memo with Google Gemini. To give it a key: create one at
aistudio.google.com/apikey, paste it in the AI INSIGHT tab and press SAVE. It is
stored in the system credential store (Windows Credential Manager / macOS
Keychain), never in the database. Setting `QT_GEMINI_API_KEY` before starting
the app works too.

- A new memo is written at most once an hour or once a day (HOURLY / DAILY in
  the tab). Asking again sooner shows the latest memo without calling Gemini,
  so no tokens are spent.

- Gemini receives only a small JSON of figures the engine already computed and
  rounded (weights, beta, VaR, ratios, drawdown). No trades, quantities or
  costs. "Show data sent to Gemini" in the pane shows the exact content.
- The prompt forbids calculations, hedge sizes and order instructions. After the
  memo returns, every number in it is checked against the figures sent, and any
  that do not match are flagged in the pane as unverified.
- Memos are stored locally with the data that produced them.

## Status

- [x] Engine: Upstox trade-book import, positions with corporate actions,
      price history cache, risk metrics, settings
- [x] Electron shell (starts and stops the engine, sandboxed renderer)
- [x] React workspace (dockable panes, TradingView chart, risk inspector,
      command palette)
- [x] Live prices over WebSocket (Upstox feed adapter, delayed Yahoo fallback)
- [x] Upstox token setup in the app, stored in the system keychain
- [x] Gemini hedging memo with a check on every number it quotes
- [x] Packaging: macOS .dmg built and tested; Windows installer configured but
      not yet built or tested

Metric formulas: [docs/metrics.md](docs/metrics.md)
