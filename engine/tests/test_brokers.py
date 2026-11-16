"""Zerodha, Groww and BSE support: imports, broker sync, reconciliation,
login sessions, price feeds and the price-source choice. No network: every
broker call is replaced with a fake."""
from __future__ import annotations

import asyncio
import io
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.brokers import http
from app.brokers.base import BrokerError, UnavailableFeed, last_reset
from app.brokers.registry import FeedContext, build_sources, choose_feed
from app.ledger import detect
from app.main import create_app
from app.market import symbols
from app.market.bse_india import BseClient
from app.market.feeds.bse_poll import BsePollFeed
from app.market.feeds.groww_poll import GrowwPollFeed, groww_key
from app.market.feeds.zerodha import build_token_map, parse_ticks, token_for
from app.secrets import MemoryStore, memory_stores

ZERODHA_CSV = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
INFY,INE009A01021,2025-01-06,NSE,EQ,EQ,buy,false,10.000000,1800.000000,55001,1100001,2025-01-06T09:30:05
INFY,INE009A01021,2025-02-03,NSE,EQ,EQ,sell,false,4.000000,1900.000000,55002,1100002,2025-02-03T10:12:00
IDEA-BE,INE669E01016,2025-02-04,NSE,EQ,BE,buy,false,100.000000,8.500000,55003,1100003,2025-02-04T11:00:00
NIFTY25FEB23000CE,,2025-02-05,NFO,FO,,buy,false,75.000000,40.000000,55004,1100004,2025-02-05T12:00:00
"""

GROWW_CSV = """Groww Order History
Client name,TEST USER
Stock name,Symbol,ISIN,Type,Quantity,Value,Exchange,Exchange Order Id,Execution date and time,Order status
HDFC Bank Ltd,HDFCBANK,INE040A01034,BUY,8,"13,600.00",NSE,9001,10-01-2025 10:15 AM,Executed
HDFC Bank Ltd,HDFCBANK,INE040A01034,BUY,2,"3,500.00",NSE,9002,11-01-2025 11:00 AM,Cancelled
ITC Ltd,ITC,INE154A01025,BUY,20,"9,000.00",BSE,9003,12-01-2025 01:30 PM,Executed
"""


def make(tmp_path, **kw):
    return create_app(db_url=f"sqlite:///{(tmp_path / 'b.sqlite3').as_posix()}", token="", **kw)


# ------------------------------------------------------------- symbols

def test_symbol_helpers():
    assert symbols.to_yahoo("IDEA-BE", "NSE") == "IDEA.NS"
    assert symbols.to_yahoo("bajaj-auto", "bse") == "BAJAJ-AUTO.BO"
    assert symbols.split("RELIANCE.NS") == ("RELIANCE", "NSE")
    assert symbols.split("^NSEI") == ("^NSEI", "")
    assert symbols.is_isin("INE002A01018") and not symbols.is_isin("RELIANCE")


# ------------------------------------------------------------- CSV / Excel imports

def test_detects_each_broker(upstox_csv):
    assert detect.detect(upstox_csv) == "upstox"
    assert detect.detect(ZERODHA_CSV.encode()) == "zerodha"
    assert detect.detect(GROWW_CSV.encode()) == "groww"


def test_zerodha_tradebook_import(tmp_path):
    with TestClient(make(tmp_path)) as client:
        r = client.post("/api/ledger/import", files={"file": ("tradebook.csv", ZERODHA_CSV, "text/csv")}).json()
        assert r["broker"] == "zerodha" and r["imported"] == 3
        assert any("non-equity" in s for s in r["skipped"])
        again = client.post("/api/ledger/import", files={"file": ("t.csv", ZERODHA_CSV, "text/csv")}).json()
        assert (again["imported"], again["duplicates"]) == (0, 3)

        trades = client.get("/api/ledger/trades").json()
        assert {t["broker"] for t in trades} == {"zerodha"}
        assert {t["symbol"] for t in trades} == {"INFY.NS", "IDEA.NS"}
        infy = next(h for h in client.get("/api/portfolio/holdings").json()["holdings"]
                    if h["symbol"] == "INFY.NS")
        assert infy["quantity"] == 6 and infy["avg_cost"] == 1800.0


def test_groww_report_import_csv_and_excel(tmp_path):
    with TestClient(make(tmp_path)) as client:
        r = client.post("/api/ledger/import", files={"file": ("groww.csv", GROWW_CSV, "text/csv")}).json()
        assert r["broker"] == "groww" and r["imported"] == 2
        assert any("cancelled" in s for s in r["skipped"])
        held = {h["symbol"]: h for h in client.get("/api/portfolio/holdings").json()["holdings"]}
        assert held["HDFCBANK.NS"]["avg_cost"] == 1700.0     # 13,600 / 8
        assert held["ITC.BO"]["quantity"] == 20

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    for line in GROWW_CSV.splitlines():
        import csv as _csv
        sheet.append(next(_csv.reader([line])))
    buf = io.BytesIO()
    book.save(buf)
    name, parsed = detect.parse(buf.getvalue())
    assert name == "groww" and len(parsed.trades) == 2


def test_export_keeps_the_broker_of_each_trade(tmp_path):
    with TestClient(make(tmp_path)) as client:
        client.post("/api/ledger/import", files={"file": ("t.csv", ZERODHA_CSV, "text/csv")})
        exported = client.get("/api/ledger/export").text
    with TestClient(create_app(db_url=f"sqlite:///{(tmp_path / 'copy.sqlite3').as_posix()}", token="")) as copy:
        copy.post("/api/ledger/import", files={"file": ("e.csv", exported, "text/csv")})
        assert {t["broker"] for t in copy.get("/api/ledger/trades").json()} == {"zerodha"}


def test_old_ledger_gets_the_isin_column(tmp_path):
    url = f"sqlite:///{(tmp_path / 'old.sqlite3').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE instruments (symbol VARCHAR PRIMARY KEY, name VARCHAR, "
                          "exchange VARCHAR, scrip_code VARCHAR)"))
        conn.execute(text("INSERT INTO instruments VALUES ('TCS.NS', 'TCS', 'NSE', 'TCS')"))
    from app.db.models import make_sessionmaker

    make_sessionmaker(url)
    assert "isin" in {c["name"] for c in inspect(create_engine(url)).get_columns("instruments")}


# ------------------------------------------------------------- Zerodha API

class FakeKite:
    """Stands in for app.brokers.http.call."""

    def __init__(self):
        self.calls = []
        self.holdings = [
            {"tradingsymbol": "INFY", "exchange": "NSE", "isin": "INE009A01021", "quantity": 5,
             "t1_quantity": 0, "average_price": 1800.0},
            {"tradingsymbol": "TCS", "exchange": "BSE", "isin": "INE467B01029", "quantity": 0,
             "t1_quantity": 3, "average_price": 4000.0},
            {"tradingsymbol": "IDEA", "exchange": "NSE", "isin": "INE669E01016", "quantity": 100,
             "t1_quantity": 0, "average_price": 8.5},
        ]
        self.trades = [
            {"trade_id": "77001", "exchange": "NSE", "tradingsymbol": "TCS", "transaction_type": "BUY",
             "quantity": 3, "average_price": 4000.0, "fill_timestamp": "2026-11-16 10:00:00"},
            {"trade_id": "77002", "exchange": "NFO", "tradingsymbol": "NIFTY", "transaction_type": "BUY",
             "quantity": 75, "average_price": 50.0, "fill_timestamp": "2026-11-16 10:00:00"},
        ]

    def __call__(self, method, url, headers=None, form=None, timeout=20):
        self.calls.append((method, url, form))
        if url.endswith("/session/token"):
            return {"data": {"access_token": "kite-access-token-123"}}
        if url.endswith("/portfolio/holdings"):
            return {"data": self.holdings}
        if url.endswith("/trades"):
            return {"data": self.trades}
        raise AssertionError(url)


def test_zerodha_login_sync_and_reconciliation(tmp_path, monkeypatch):
    kite = FakeKite()
    monkeypatch.setattr(http, "call", kite)
    with TestClient(make(tmp_path)) as client:
        client.post("/api/ledger/import", files={"file": ("t.csv", ZERODHA_CSV, "text/csv")})
        saved = client.put("/api/connections/zerodha/credentials",
                           json={"values": {"api_key": "kitekey", "api_secret": "kite-secret-xyz"}})
        assert saved.status_code == 200 and "kite-secret-xyz" not in saved.text
        url = client.get("/api/connections/zerodha/login-url").json()["url"]
        assert url.startswith("https://kite.zerodha.com/connect/login?") and "api_key=kitekey" in url

        assert client.post("/api/connections/zerodha/sync").status_code == 401   # no session yet
        bad = client.post("/api/connections/zerodha/session", json={"value": "not a url"})
        assert bad.status_code == 400
        ok = client.post("/api/connections/zerodha/session",
                         json={"value": "http://127.0.0.1/cb?action=login&status=success&request_token=rt42"})
        assert ok.status_code == 200 and "kite-access-token-123" not in ok.text
        zerodha = next(s for s in ok.json()["sources"] if s["id"] == "zerodha")
        assert zerodha["session"]["active"] is True
        method, _, form = kite.calls[-1]
        assert method == "POST" and form["request_token"] == "rt42" and len(form["checksum"]) == 64

        result = client.post("/api/connections/zerodha/sync").json()
        assert result["imported"] == 1 and result["holdings"] == 3   # the NFO trade is ignored
        assert all(c[0] == "GET" for c in kite.calls if not c[1].endswith("/session/token"))
        # Ledger: INFY 6 (10 bought, 4 sold), TCS 3 from today's sync. Zerodha: INFY 5, TCS 3 (T1).
        rows = {m["symbol"]: m for m in result["mismatches"]}
        assert set(rows) == {"INFY.NS"}
        assert (rows["INFY.NS"]["broker_quantity"], rows["INFY.NS"]["ledger_quantity"]) == (5, 6)
        warnings = client.get("/api/portfolio/holdings").json()["warnings"]
        assert any(w.startswith("Zerodha holds 5 INFY.NS") for w in warnings)
        # TCS bought on NSE but held as BSE: matched through the ISIN, so no warning.
        assert not any("holds" in w and "TCS" in w for w in warnings)


def test_zerodha_session_expires_at_the_morning_reset():
    sources = build_sources(memory_stores, MemoryStore())
    z = sources["zerodha"]
    stale = (last_reset() - timedelta(minutes=1)).isoformat(timespec="seconds")
    z.stores["access_token"].set(f"{stale}|old-token")
    assert z.session_token() is None
    z._store_session("fresh-token")
    assert z.session_token() == "fresh-token"
    assert isinstance(z.make_feed(Path(".")), object)
    z.end_session()
    assert isinstance(z.make_feed(Path(".")), UnavailableFeed)


def test_unknown_credential_fields_and_spaces_are_rejected(tmp_path):
    with TestClient(make(tmp_path)) as client:
        assert client.put("/api/connections/zerodha/credentials",
                          json={"values": {"password": "x"}}).status_code == 400
        assert client.put("/api/connections/groww/credentials",
                          json={"values": {"api_key": "has space"}}).status_code == 400
        assert client.get("/api/connections/nosuch/login-url").status_code == 404
        assert client.post("/api/connections/upstox/sync").status_code == 400


# ------------------------------------------------------------- Groww API (fake SDK)

class FakeGroww:
    SEGMENT_CASH = "CASH"
    issued = []

    def __init__(self, token):
        self.token = token

    @staticmethod
    def get_access_token(api_key, totp=None, secret=None):
        FakeGroww.issued.append((api_key, totp, secret))
        return "groww-access-token-abcdefghij"

    def get_holdings_for_user(self, timeout=None):
        return {"holdings": [{"isin": "INE040A01034", "trading_symbol": "HDFCBANK", "quantity": 8,
                              "average_price": 1700.0}]}

    def get_ltp(self, segment, exchange_trading_symbols):
        return {k: 1750.0 for k in exchange_trading_symbols if k == "NSE_HDFCBANK"}


@pytest.fixture
def fake_groww_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "growwapi", types.SimpleNamespace(GrowwAPI=FakeGroww))
    monkeypatch.setitem(sys.modules, "pyotp", types.SimpleNamespace(
        TOTP=lambda secret: types.SimpleNamespace(now=lambda: "123456")))
    FakeGroww.issued = []


def test_groww_totp_login_and_holdings_sync(tmp_path, fake_groww_sdk):
    with TestClient(make(tmp_path)) as client:
        client.post("/api/ledger/import", files={"file": ("g.csv", GROWW_CSV, "text/csv")})
        client.put("/api/connections/groww/credentials",
                   json={"values": {"api_key": "gkey", "totp_secret": "JBSWY3DPEHPK3PXP"}})
        opened = client.post("/api/connections/groww/session", json={})
        assert opened.status_code == 200 and FakeGroww.issued == [("gkey", "123456", None)]
        result = client.post("/api/connections/groww/sync").json()
        assert result["holdings"] == 1 and result["imported"] == 0
        # Ledger has HDFCBANK 8 (matches) and ITC 20 that Groww no longer reports.
        assert [m["symbol"] for m in result["mismatches"]] == ["ITC.BO"]


def test_groww_without_sdk_explains_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "growwapi", None)
    with TestClient(make(tmp_path)) as client:
        client.put("/api/connections/groww/credentials", json={"values": {"api_key": "gkey", "api_secret": "s3cr3t"}})
        r = client.post("/api/connections/groww/session", json={})
        assert r.status_code == 501 and "pip install growwapi" in r.json()["detail"]


# ------------------------------------------------------------- price feeds

class Stop(Exception):
    pass


class FakeHub:
    def __init__(self, held):
        self.held = held
        self.quotes = {}
        self.statuses = []

    def held_symbols(self):
        return self.held

    def on_quote(self, symbol, ltp, prev_close, ts=None):
        self.quotes[symbol] = (ltp, prev_close)

    def set_status(self, state, detail=""):
        self.statuses.append((state, detail))
        raise Stop  # end the polling loop after one round


def run_once(feed, hub):
    with pytest.raises(Stop):
        asyncio.run(feed.run(hub))


def _packet(token, *ints):
    body = token.to_bytes(4, "big") + b"".join(int(v).to_bytes(4, "big", signed=True) for v in ints)
    return len(body).to_bytes(2, "big") + body


def test_kite_binary_ticks():
    nse_token = (408065 << 8) | 1          # segment 1 = NSE equity
    ltp_only = _packet(nse_token, 150025)                                    # 8 bytes
    quote = _packet(nse_token, 150025, 1, 150000, 10, 5, 5, 149000, 151000, 148000, 148050)  # 44 bytes
    index = _packet((256265 << 8) | 9, 2350010, 2360000, 2340000, 2345000, 2330000, 20010)    # 28 bytes
    frame = (3).to_bytes(2, "big") + ltp_only + quote + index
    ticks = parse_ticks(frame)
    assert [t["ltp"] for t in ticks] == [1500.25, 1500.25, 23500.10]
    assert [t["close"] for t in ticks] == [None, 1480.50, 23300.00]
    assert parse_ticks(b"\x00") == []                                         # heartbeat


def test_kite_instrument_map():
    csv_text = ("instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,"
                "lot_size,instrument_type,segment,exchange\n"
                "738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.1,1,EQ,NSE,NSE\n"
                "128083204,500325,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,BSE,BSE\n"
                "12345,1,RELIANCE25FEBFUT,,0,2025-02-27,0,0.1,250,FUT,NFO-FUT,NFO\n")
    maps = {"NSE": build_token_map(csv_text, "NSE"), "BSE": build_token_map(csv_text, "BSE")}
    assert token_for("RELIANCE.NS", maps) == 738561
    assert token_for("500325.BO", maps) == token_for("RELIANCE.BO", maps) == 128083204
    assert token_for("^NSEI", maps) is None


def test_groww_poll_feed():
    assert groww_key("HDFCBANK.NS") == "NSE_HDFCBANK" and groww_key("^NSEI") is None
    hub = FakeHub(["HDFCBANK.NS", "ITC.BO"])
    run_once(GrowwPollFeed(lambda: FakeGroww("t"), interval=0), hub)
    assert hub.quotes == {"HDFCBANK.NS": (1750.0, None)}
    assert hub.statuses == [("live", "No Groww price for ITC.BO")]


class FakeBse:
    """Stands in for bse.BSE (the BseIndiaApi package)."""

    def __init__(self):
        self.quoted, self.looked_up = [], []

    def lookup(self, text):
        self.looked_up.append(text)
        return {"symbol": "RELIANCE", "isin": text, "bse_code": "500325"} if text == "INE002A01018" else None

    def getScripCode(self, name):
        if name == "INFY":
            return "500209"
        raise ValueError("not found")

    def quote(self, code):
        self.quoted.append(code)
        return {"PrevClose": 1300.0, "Open": 1301.0, "High": 1320.0, "Low": 1295.0, "LTP": 1310.5}

    def actions(self, segment, scripcode, from_date, to_date):
        return [
            {"scrip_code": 500209, "Purpose": "Interim Dividend - Rs. - 18.0000", "exdate": "20250115"},
            {"scrip_code": 500209, "Purpose": "Bonus issue 1:1", "Ex_date": "03 Feb 2025", "exdate": ""},
            {"scrip_code": 500209, "Purpose": "Annual General Meeting", "exdate": "20250301"},
        ]

    def exit(self):
        pass


def test_bse_poll_feed_uses_isin_lookup_and_caches_codes(tmp_path):
    fake = FakeBse()
    client = BseClient(tmp_path, factory=lambda: fake)
    hub = FakeHub(["RELIANCE.NS", "532540.BO", "INFY.NS", "NOSUCH.NS", "MF:122639"])
    feed = BsePollFeed(tmp_path, client=client, interval=0,
                       isin_of=lambda: {"RELIANCE.NS": "INE002A01018"})
    run_once(feed, hub)
    assert fake.quoted == ["500325", "532540", "500209"]   # by ISIN, already a code, by ticker
    assert hub.quotes["RELIANCE.NS"] == (1310.5, 1300.0)
    assert "MF:122639" not in hub.quotes                    # funds are not BSE equities
    assert hub.statuses == [("live", "No BSE price for NOSUCH.NS")]
    cached = BseClient(tmp_path, factory=lambda: None)      # second run: no lookups needed
    assert cached.code_for("RELIANCE.NS", "INE002A01018") == "500325"
    assert cached.code_for("NOSUCH.NS") is None


def test_bse_corporate_actions_are_parsed(tmp_path):
    client = BseClient(tmp_path, factory=FakeBse)
    from datetime import date as d

    rows = client.actions("500209", d(2025, 1, 1), d(2025, 12, 31))
    assert [(r["ex_date"], r["kind"], r["value"]) for r in rows] == [
        (d(2025, 1, 15), "dividend", 18.0), (d(2025, 2, 3), "bonus", 2.0)]


# ------------------------------------------------------------- choosing the price source

def test_choose_feed_order_and_overrides(tmp_path):
    sources = build_sources(memory_stores, MemoryStore())
    ctx = FeedContext(sources=sources, preference="auto", cache_dir=tmp_path)
    assert choose_feed(ctx).name == "yahoo-delayed"
    sources["upstox"].stores["token"].set("x" * 30)
    assert choose_feed(ctx).name == "upstox"
    ctx.preference = "bse"
    assert choose_feed(ctx).name == "bse"
    ctx.preference = "zerodha"
    feed = choose_feed(ctx)
    assert isinstance(feed, UnavailableFeed) and "Log in to Zerodha" in feed.message
    assert choose_feed(ctx, env_choice="yahoo").name == "yahoo-delayed"
    assert choose_feed(ctx, env_choice="off") is None


class NamedFeed:
    retry_seconds = 0.01

    def __init__(self, name):
        self.name = name

    async def run(self, hub):
        hub.set_status("live")
        await asyncio.Event().wait()


def test_price_source_is_saved_and_switches_the_live_feed(tmp_path):
    factory = lambda ctx: NamedFeed(ctx.preference)  # noqa: E731
    with TestClient(make(tmp_path, feed_factory=factory)) as client:
        assert client.get("/api/connections").json()["price_source"] == "auto"
        assert client.put("/api/connections/price-source", json={"source": "nasdaq"}).status_code == 400
        r = client.put("/api/connections/price-source", json={"source": "bse"}).json()
        assert r["price_source"] == "bse"
        with client.websocket_connect("/ws/ticks") as ws:
            assert ws.receive_json()["status"]["source"] == "bse"
    # The choice survives a restart.
    with TestClient(make(tmp_path, feed_factory=factory)) as client:
        with client.websocket_connect("/ws/ticks") as ws:
            assert ws.receive_json()["status"]["source"] == "bse"


def test_overview_lists_every_source_without_secrets(tmp_path):
    with TestClient(make(tmp_path)) as client:
        client.put("/api/connections/groww/credentials", json={"values": {"api_key": "groww-key-SECRET"}})
        body = client.get("/api/connections")
        assert "groww-key-SECRET" not in body.text
        ids = [s["id"] for s in body.json()["sources"]]
        assert ids == ["upstox", "zerodha", "groww", "bse", "yahoo"]
        groww = next(s for s in body.json()["sources"] if s["id"] == "groww")
        assert groww["configured"] is True and groww["fields"][0]["set"] is True


def test_zerodha_adapter_only_posts_to_open_a_session():
    text_ = (Path(__file__).parents[1] / "app" / "brokers" / "zerodha.py").read_text()
    assert text_.count('"POST"') == 1 and '"POST", f"{API}/session/token"' in text_
    for path in (Path(__file__).parents[1] / "app" / "market" / "feeds").glob("*.py"):
        body = path.read_text()
        assert '"POST"' not in body and "method=\"POST\"" not in body, path
