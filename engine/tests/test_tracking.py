"""Split/bonus review, international stocks in INR, the local price cache,
the starred watchlist and the portfolio optimiser. No network."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db.models import CorporateAction, PriceBar, Setting, Trade
from app.main import create_app
from app.market import history
from tests.conftest import fake_fetch

DAYS = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=400).date
CALLS: list[tuple[str, date]] = []


def frame(values, dividend=None, split=None, currency=""):
    f = pd.DataFrame({"close": values, "adj_close": values, "dividend": 0.0, "split": 0.0}, index=DAYS)
    for d, v in (dividend or {}).items():
        f.loc[d, "dividend"] = v
    for d, v in (split or {}).items():
        f.loc[d, "split"] = v
    f.attrs["currency"] = currency
    return f


def market(symbol, start):
    """USD/INR at 80 until 100 days ago, then 85. AAPL flat at $110, pays $1 sixty days ago.
    VOD.L at 200 pence, GBP/INR 100. Indian stocks and anything else: the shared random paths."""
    CALLS.append((symbol, start))
    n = len(DAYS)
    if symbol == "USDINR=X":
        return frame(np.where(np.arange(n) < n - 100, 80.0, 85.0))
    if symbol == "GBPINR=X":
        return frame(np.full(n, 100.0))
    if symbol == "AAPL":
        return frame(np.full(n, 110.0), dividend={DAYS[-60]: 1.0}, currency="USD")
    if symbol == "VOD.L":
        return frame(np.full(n, 200.0), currency="GBp")
    f = fake_fetch(symbol, start)
    f.attrs["currency"] = "INR" if symbol.endswith((".NS", ".BO")) or symbol.startswith("^") else "USD"
    return f


@pytest.fixture
def client(tmp_path, monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(history, "fetch", market)
    app = create_app(db_url=f"sqlite:///{(tmp_path / 't.sqlite3').as_posix()}", token="")
    with TestClient(app) as c:
        c.app_ref = app
        yield c


def trade(client, symbol, qty, price, when, side="BUY", market=None, name=None):
    r = client.post("/api/ledger/trades", json={"symbol": symbol, "side": side, "quantity": qty, "price": price,
                                               "traded_at": f"{when}T10:00:00", "market": market, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


def session_of(client):
    return client.app_ref.state.sessionmaker()


# ---------------------------------------------------------------- split / bonus review

def test_split_inside_the_upload_window_is_asked_about_and_suggested(client):
    traded = DAYS[-200]
    trade(client, "RELIANCE.NS", 10, 2000.0, traded.isoformat())
    ex = DAYS[-100]
    client.get("/api/metrics")                                       # caches prices
    with session_of(client) as s:
        # Yahoo's closes are split-adjusted: before a 2:1 split they show half the
        # traded price. The file says 2000, Yahoo's close that day says 1000.
        s.get(PriceBar, ("RELIANCE.NS", traded)).close = 1000.0
        s.commit()
    assert client.post("/api/corporate-actions", json={"symbol": "RELIANCE.NS", "ex_date": ex.isoformat(),
                                                        "kind": "split", "value": 2}).status_code == 201
    data = client.get("/api/portfolio/holdings").json()
    assert any("CHECK SPLITS" in w for w in data["warnings"])
    assert data["holdings"][0]["quantity"] == 20                     # applied while pending

    pending = client.get("/api/corporate-actions/review").json()
    assert len(pending) == 1
    item = pending[0]
    assert (item["quantity_if_applied"], item["quantity_if_skipped"]) == (20, 10)
    assert item["uploaded_on"] == date.today().isoformat()
    assert item["suggestion"]["answer"] == "apply"

    # The user says the file was already restated: the split must not apply twice.
    client.post(f"/api/corporate-actions/{item['id']}/review", json={"decision": "skip"})
    assert client.get("/api/portfolio/holdings").json()["holdings"][0]["quantity"] == 10
    assert client.get("/api/corporate-actions/review").json() == []
    actions = client.get("/api/corporate-actions").json()
    assert actions[0]["review"] == "skip"


def test_split_after_the_upload_is_applied_without_asking(client):
    trade(client, "TCS.NS", 5, 4000.0, DAYS[-300].isoformat())
    with session_of(client) as s:          # the trade entered the ledger long ago
        s.execute(update(Trade).values(imported_at=datetime.combine(DAYS[-250], datetime.min.time())))
        s.commit()
    client.post("/api/corporate-actions", json={"symbol": "TCS.NS", "ex_date": DAYS[-100].isoformat(),
                                                "kind": "bonus", "value": 2})
    assert client.get("/api/corporate-actions/review").json() == []
    assert client.get("/api/portfolio/holdings").json()["holdings"][0]["quantity"] == 10


def test_answer_survives_yahoo_rewriting_its_actions(client, monkeypatch):
    def with_split(symbol, start):
        f = market(symbol, start)
        if symbol == "INFY.NS":
            f.loc[DAYS[-50], "split"] = 2.0
        return f

    monkeypatch.setattr(history, "fetch", with_split)
    trade(client, "INFY.NS", 4, 1500.0, DAYS[-120].isoformat())
    client.get("/api/metrics")
    item = client.get("/api/corporate-actions/review").json()[0]
    assert item["source"] == "yfinance"
    client.post(f"/api/corporate-actions/{item['id']}/review", json={"decision": "skip"})
    client.post("/api/market/refresh")                               # full re-download
    with session_of(client) as s:
        split = s.scalars(select(CorporateAction).where(CorporateAction.kind == "split")).one()
        assert split.review == "skip"


# ---------------------------------------------------------------- international stocks

def test_us_stock_is_costed_and_valued_in_rupees(client):
    bought = DAYS[-200]                                              # USD/INR was 80 then
    assert trade(client, "AAPL", 10, 100.0, bought.isoformat())["symbol"] == "AAPL.NS"  # bare = NSE
    client.delete("/api/ledger/trades/1")
    t = trade(client, "AAPL", 10, 100.0, bought.isoformat(), market="INTL", name="Apple Inc.")
    assert t["symbol"] == "AAPL"
    data = client.get("/api/metrics").json()
    h = next(x for x in data["holdings"] if x["symbol"] == "AAPL")
    assert h["currency"] == "USD" and h["fx_rate"] == 85.0
    assert h["last"] == 110.0 and h["avg_cost"] == 100.0             # shown in dollars
    assert h["value"] == pytest.approx(10 * 110 * 85)                # valued in rupees today
    assert h["unrealized_pnl"] == pytest.approx(10 * 110 * 85 - 10 * 100 * 80)
    assert h["dividends"] == pytest.approx(10 * 1.0 * 85)            # $1 at that day's rate
    assert h["total_return"] == pytest.approx(10 * 110 * 85 - 10 * 100 * 80 + 850)
    assert h["xirr"] is not None and h["xirr"] > 0


def test_london_pence_are_converted(client):
    trade(client, "VOD.L", 100, 180.0, DAYS[-150].isoformat())       # suffix makes it international
    h = client.get("/api/metrics").json()["holdings"][0]
    assert h["currency"] == "GBp" and h["value"] == pytest.approx(100 * 200 / 100 * 100)


def test_live_snapshot_converts_foreign_quotes(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(history, "fetch", market)

    class Feed:
        name, retry_seconds = "fake", 0.01

        async def run(self, hub):
            hub.on_quote("AAPL", 120.0, 110.0)
            hub.set_status("live")
            await asyncio.Event().wait()

    app = create_app(db_url=f"sqlite:///{(tmp_path / 'l.sqlite3').as_posix()}", token="", feed=Feed())
    with TestClient(app) as c:
        c.post("/api/ledger/trades", json={"symbol": "AAPL", "side": "BUY", "quantity": 2, "price": 100,
                                           "traded_at": f"{DAYS[-200]}T10:00:00", "market": "INTL"})
        c.get("/api/metrics")
        with c.websocket_connect("/ws/ticks") as ws:
            snap = ws.receive_json()
            for _ in range(5):
                if snap["portfolio"]["priced"]:
                    break
                snap = ws.receive_json()
    row = snap["portfolio"]["holdings"]["AAPL"]
    assert row["value"] == pytest.approx(2 * 120 * 85) and row["day_pnl"] == pytest.approx(2 * 10 * 85)


# ---------------------------------------------------------------- local price cache

def test_prices_are_served_from_the_cache_and_updated_incrementally(client):
    client.put("/api/watchlist/INFY.NS", json={"watched": True})      # watched: prices are kept
    r = client.get("/api/prices/INFY.NS", params={"days": 365}).json()
    assert r["bars"] and r["currency"] == "INR"
    first = [c for c in CALLS if c[0] == "INFY.NS"]
    client.get("/api/prices/INFY.NS", params={"days": 365})
    assert [c for c in CALLS if c[0] == "INFY.NS"] == first          # same day: no download
    with session_of(client) as s:                                     # pretend it is tomorrow
        mark = s.get(Setting, "refreshed:INFY.NS")
        mark.value = (date.today() - timedelta(days=1)).isoformat() + "|" + mark.value.partition("|")[2]
        s.commit()
    client.get("/api/prices/INFY.NS", params={"days": 365})
    last_call = [c for c in CALLS if c[0] == "INFY.NS"][-1]
    assert last_call[1] == DAYS[-1] - timedelta(days=7)               # only the last week
    stats = client.get("/api/cache").json()
    assert stats["served_from_cache"] >= 1 and stats["incremental_updates"] == 1
    assert stats["full_downloads"] == 1          # the watch itself; every later read is local
    assert client.get("/api/prices/INFY.NS/csv").text.startswith("date,close,adj_close\n")


def test_a_new_dividend_forces_a_full_download(client, monkeypatch):
    client.put("/api/watchlist/ITC.NS", json={"watched": True})
    with session_of(client) as s:
        mark = s.get(Setting, "refreshed:ITC.NS")
        mark.value = "2000-01-01|" + mark.value.partition("|")[2]
        s.commit()

    def paid(symbol, start):
        f = market(symbol, start)
        f.loc[DAYS[-2], "dividend"] = 6.5
        return f

    monkeypatch.setattr(history, "fetch", paid)
    client.get("/api/prices/ITC.NS", params={"days": 365})
    assert client.get("/api/cache").json()["full_downloads"] == 2


# ---------------------------------------------------------------- watchlist and optimiser

def test_watch_star_and_history_are_separate(client):
    # Watching (eye) and starring both cache prices and list the stock.
    r = client.put("/api/watchlist/HDFCBANK.NS", json={"watched": True, "name": "HDFC Bank"}).json()
    row = r["watchlist"][0]
    assert row["watched"] and not row["starred"] and row["cached_bars"] > 200 and row["last"] is not None
    client.put("/api/watchlist/TCS.NS", json={"starred": True})
    assert {x["symbol"] for x in client.get("/api/watchlist").json()} == {"HDFCBANK.NS", "TCS.NS"}

    # Opening a stock from the search only records the visit: no download, not on the watchlist.
    before = len(CALLS)
    seen = client.post("/api/watchlist/MSFT/view", json={"name": "Microsoft", "exchange": "NASDAQ"}).json()
    assert seen == {"symbol": "MSFT", "tracked": False} and len(CALLS) == before
    assert "MSFT" not in {x["symbol"] for x in client.get("/api/watchlist").json()}
    hist = client.get("/api/history").json()
    assert hist[0]["symbol"] == "MSFT" and hist[0]["cached_bars"] == 0 and hist[0]["exchange"] == "NASDAQ"

    # Its chart: nothing cached, so nothing unless asked; then downloaded once and not saved.
    assert client.get("/api/prices/MSFT").json()["bars"] == []
    once = client.get("/api/prices/MSFT", params={"fetch": "true"}).json()
    assert once["bars"] and once["saved"] is False and once["currency"] == "USD"
    assert client.get("/api/prices/MSFT").json()["bars"] == []          # still nothing stored
    assert "MSFT" not in {x["symbol"] for x in client.get("/api/cache").json()["symbols"]}

    # Watching it later starts caching; clearing history keeps watched stocks listed.
    client.put("/api/watchlist/MSFT", json={"watched": True})
    assert client.get("/api/prices/MSFT").json()["saved"] is True
    assert client.delete("/api/history").json() == []
    assert "MSFT" in {x["symbol"] for x in client.get("/api/watchlist").json()}
    assert client.put("/api/watchlist/not a symbol!", json={"starred": True}).status_code == 400
    assert "MSFT" not in {x["symbol"] for x in client.delete("/api/watchlist/MSFT").json()}


def test_starred_rows_stay_watched_after_upgrade(tmp_path):
    from sqlalchemy import create_engine, text

    from app.db.models import make_sessionmaker

    url = f"sqlite:///{(tmp_path / 'old.sqlite3').as_posix()}"
    with create_engine(url).begin() as conn:
        conn.execute(text("CREATE TABLE watchlist (symbol VARCHAR PRIMARY KEY, starred BOOLEAN NOT NULL, "
                          "added_at DATETIME NOT NULL, viewed_at DATETIME)"))
        conn.execute(text("INSERT INTO watchlist VALUES ('INFY.NS', 1, '2026-01-01', NULL), "
                          "('MSFT', 0, '2026-01-01', '2026-01-02')"))
    make_sessionmaker(url)
    with create_engine(url).connect() as conn:
        rows = dict(conn.execute(text("SELECT symbol, watched FROM watchlist")).all())
    assert rows == {"INFY.NS": 1, "MSFT": 0}


def test_optimiser_scopes(client):
    # Default scope is the whole portfolio.
    no_holdings = client.post("/api/optimizer", json={})
    assert no_holdings.status_code == 400 and "Hold at least two" in no_holdings.json()["detail"]
    trade(client, "INFY.NS", 10, 1000.0, DAYS[-300].isoformat())
    trade(client, "TCS.NS", 3, 3000.0, DAYS[-300].isoformat())
    trade(client, "AAPL", 5, 150.0, DAYS[-300].isoformat(), market="INTL")
    r = client.post("/api/optimizer", json={"lookback_days": 252}).json()
    assert r["scope"] == "portfolio" and set(r["symbols"]) == {"INFY.NS", "TCS.NS", "AAPL"}
    assert set(r["portfolios"]["current"]["weights"]) == {"INFY.NS", "TCS.NS", "AAPL"}
    assert sum(r["portfolios"]["current"]["weights"].values()) == pytest.approx(1.0)

    for s in ("HDFCBANK.NS", "ITC.NS"):
        client.put(f"/api/watchlist/{s}", json={"starred": True})
    starred = client.post("/api/optimizer", json={"scope": "starred", "lookback_days": 252}).json()
    assert set(starred["symbols"]) == {"HDFCBANK.NS", "ITC.NS"} and "current" not in starred["portfolios"]
    both = client.post("/api/optimizer", json={"scope": "both", "lookback_days": 252}).json()
    assert set(both["symbols"]) == {"INFY.NS", "TCS.NS", "AAPL", "HDFCBANK.NS", "ITC.NS"}
    custom = client.post("/api/optimizer", json={"symbols": ["INFY.NS", "ITC.NS"], "lookback_days": 252}).json()
    assert custom["scope"] == "custom" and set(custom["symbols"]) == {"INFY.NS", "ITC.NS"}


def test_optimiser_on_starred_stocks(client):
    assert client.post("/api/optimizer", json={"scope": "starred"}).status_code == 400   # nothing starred yet
    for s in ("HDFCBANK.NS", "INFY.NS", "ITC.NS", "AAPL"):
        client.put(f"/api/watchlist/{s}", json={"starred": True})
    trade(client, "INFY.NS", 10, 1000.0, DAYS[-300].isoformat())
    r = client.post("/api/optimizer", json={"scope": "starred", "max_weight": 0.4, "lookback_days": 252}).json()
    assert set(r["symbols"]) == {"HDFCBANK.NS", "INFY.NS", "ITC.NS", "AAPL"}
    best, low = r["portfolios"]["max_sharpe"], r["portfolios"]["min_variance"]
    for p in (best, low):
        assert sum(p["weights"].values()) == pytest.approx(1.0, abs=1e-6)
        assert max(p["weights"].values()) <= 0.4 + 1e-6
    assert best["sharpe"] >= max(r["portfolios"][k]["sharpe"] for k in ("min_variance", "equal_weight")) - 1e-6
    assert low["volatility"] <= r["portfolios"]["equal_weight"]["volatility"] + 1e-9
    assert r["portfolios"]["current"]["weights"]["INFY.NS"] == 1.0
    assert len(r["frontier"]) > 5 and r["observations"] >= 200
    assert next(a for a in r["assets"] if a["symbol"] == "INFY.NS")["held"] is True
