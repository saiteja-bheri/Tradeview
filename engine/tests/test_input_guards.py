"""Regression tests for the four defects found by the 2026-11-17 stress test:
D1 oversells, D2 future-dated trades, D3/D4 unreadable uploads returning 500."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.ledger.positions import clip_oversells, held_on
from app.market import history
from tests.conftest import fake_fetch
from tests.test_api import upload

XT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def trade(sym, side, qty, day, price=100.0, id=None):
    return SimpleNamespace(id=id, symbol=sym, side=side, quantity=qty, price=price,
                           traded_at=datetime.fromisoformat(day), broker="t", imported_at=None, trade_id=str(id))


def split(sym, day, ratio):
    return SimpleNamespace(symbol=sym, ex_date=date.fromisoformat(day), kind="split", value=ratio, review="")


# ---------------------------------------------------------------- D1 maths

def test_clip_caps_unbacked_sale_and_keeps_backed_ones():
    t = [trade("A", "BUY", 10, "2025-01-02", id=1), trade("A", "SELL", 4, "2025-02-03", id=2),
         trade("A", "SELL", 99999, "2025-03-03", id=3), trade("B", "SELL", 5, "2025-03-03", id=4)]
    out, warns = clip_oversells(t, [])
    sells = {x.id: x.quantity for x in out if x.side == "SELL"}
    assert sells == {2: 4, 3: 6}             # 6 left after selling 4; B's sale has nothing behind it
    assert len(warns) == 2 and "99993" in warns[0]


def test_clip_counts_splits_and_same_day_buys():
    t = [trade("A", "BUY", 10, "2025-01-02"), trade("A", "SELL", 20, "2025-06-02")]
    out, warns = clip_oversells(t, [split("A", "2025-03-03", 2)])
    assert [x.quantity for x in out if x.side == "SELL"] == [20] and warns == []
    assert held_on(t, [split("A", "2025-03-03", 2)], "A", datetime(2025, 6, 2)) == 20
    same_day = [trade("A", "BUY", 5, "2025-01-02T09:30"), trade("A", "SELL", 5, "2025-01-02T15:00")]
    assert clip_oversells(same_day, [])[1] == []


# ---------------------------------------------------------------- D1 / D2 via the API

def _buy(client, qty=10, day="2025-01-02"):
    r = client.post("/api/ledger/trades", json={"symbol": "ITC", "side": "BUY", "quantity": qty, "price": 400,
                                                 "traded_at": day})
    assert r.status_code == 201
    return r.json()["id"]


def test_manual_oversell_rejected_with_reason(client):
    _buy(client, 10)
    r = client.post("/api/ledger/trades", json={"symbol": "ITC", "side": "SELL", "quantity": 11, "price": 420,
                                                 "traded_at": "2025-03-03"})
    assert r.status_code == 400 and "held 10" in r.json()["detail"]
    ok = client.post("/api/ledger/trades", json={"symbol": "ITC", "side": "SELL", "quantity": 10, "price": 420,
                                                  "traded_at": "2025-03-03"})
    assert ok.status_code == 201                                   # selling exactly what is held is fine
    early = client.post("/api/ledger/trades", json={"symbol": "ITC", "side": "SELL", "quantity": 1, "price": 420,
                                                     "traded_at": "2024-12-31"})
    assert early.status_code == 400                                # before the purchase


def test_editing_a_sale_cannot_oversell(client):
    _buy(client, 10)
    sid = client.post("/api/ledger/trades", json={"symbol": "ITC", "side": "SELL", "quantity": 5, "price": 420,
                                                   "traded_at": "2025-03-03"}).json()["id"]
    body = {"symbol": "ITC", "side": "SELL", "quantity": 10, "price": 420, "traded_at": "2025-03-03"}
    assert client.put(f"/api/ledger/trades/{sid}", json=body).status_code == 200   # its own 5 don't count twice
    assert client.put(f"/api/ledger/trades/{sid}", json={**body, "quantity": 11}).status_code == 400


def test_future_dated_manual_trade_rejected(client):
    r = client.post("/api/ledger/trades", json={"symbol": "ITC", "side": "BUY", "quantity": 1, "price": 400,
                                                 "traded_at": TOMORROW})
    assert r.status_code == 422 and "future" in r.text
    today = client.post("/api/ledger/trades", json={"symbol": "ITC", "side": "BUY", "quantity": 1, "price": 400,
                                                     "traded_at": date.today().isoformat()})
    assert today.status_code == 201


def test_import_skips_future_rows_and_caps_oversells_in_cash(client, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    head = "trade_date,symbol,exchange,segment,trade_type,quantity,price,brokerage,order_id,total_amount\n"
    rows = (f"2025-01-02,ITC,NSE,EQ,buy,10,400,0,O1,4000\n"
            f"2025-03-03,ITC,NSE,EQ,sell,99999,410,0,O2,40999590\n"     # typo: far more than held
            f"{TOMORROW},ITC,NSE,EQ,buy,5,400,0,O3,2000\n")
    r = client.post("/api/ledger/import", files={"file": ("z.csv", (head + rows).encode(), "text/csv")}).json()
    assert r["imported"] == 2 and any("future" in s for s in r["skipped"])
    cash = client.get("/api/portfolio-cash").json()
    assert cash["sale_proceeds"] == pytest.approx(10 * 410)        # only the 10 that existed, not 99,999
    m = client.get("/api/metrics", params={"refresh": "false"}).json()
    assert any("more than held" in w for w in m["warnings"])


# ---------------------------------------------------------------- D3 / D4

@pytest.mark.parametrize("path,payload,ctype", [
    ("/api/ledger/import", bytes(range(256)) * 50, "text/csv"),
    ("/api/ledger/import/preview", bytes(range(256)) * 50, "text/csv"),
    ("/api/ledger/import?broker=upstox", b"\xff\xfe\x00garbage\x00" * 300, "text/csv"),
    ("/api/import/everything", b"PK\x03\x04notreallyazip" * 20, XT),
    ("/api/import/everything/preview", b"PK\x03\x04notreallyazip" * 20, XT),
    ("/api/ledger/import", b"PK\x03\x04notreallyazip" * 20, XT),
    ("/api/import/everything", bytes(range(256)) * 50, "text/csv"),
])
def test_unreadable_uploads_are_400_not_500(client, path, payload, ctype):
    r = client.post(path, files={"file": ("bad", payload, ctype)})
    assert r.status_code == 400, r.text
    assert "could not be read" in r.json()["detail"]


def test_csv_with_bare_carriage_returns_still_reads(client):
    """Old Mac line endings (\\r only) used to raise csv.Error; they are valid CSV."""
    data = ("trade_date,symbol,exchange,segment,trade_type,quantity,price,brokerage,order_id,total_amount\r"
            "2025-01-02,ITC,NSE,EQ,buy,10,400,0,R1,4000\r").encode()
    r = client.post("/api/ledger/import/preview", files={"file": ("r.csv", data, "text/csv")})
    assert r.status_code == 200
