"""Portfolio value and net worth over time, and dividend cash. No network."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market import history

DAYS = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=400).date


def flat(symbol, start):
    """Every stock trades at 100 every day, except SPLT whose Yahoo close is
    split-adjusted: 50 throughout (it really traded at 100 before a 2:1 split)."""
    price = 50.0 if symbol == "SPLT.NS" else 100.0
    f = pd.DataFrame({"close": price, "adj_close": price, "dividend": 0.0, "split": 0.0}, index=DAYS)
    f.attrs["currency"] = "INR"
    return f


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "fetch", flat)
    app = create_app(db_url=f"sqlite:///{(tmp_path / 't.sqlite3').as_posix()}", token="")
    with TestClient(app) as c:
        yield c


def trade(client, symbol, side, qty, price, day):
    r = client.post("/api/ledger/trades", json={"symbol": symbol, "side": side, "quantity": qty, "price": price,
                                               "traded_at": f"{day}T10:00:00"})
    assert r.status_code == 201, r.text


def at(t, day, key):
    return t["series"][key][t["dates"].index(day.isoformat())]


def test_value_money_in_cash_and_gain_over_time(client):
    trade(client, "INFY.NS", "BUY", 10, 100, DAYS[-300])
    client.post("/api/corporate-actions", json={"symbol": "INFY.NS", "kind": "dividend", "value": 5,
                                                "ex_date": DAYS[-100].isoformat()})
    trade(client, "INFY.NS", "SELL", 4, 100, DAYS[-30])
    client.get("/api/metrics")
    t = client.get("/api/timeline").json()
    assert t["dates"][0] == DAYS[-300].isoformat()
    assert at(t, DAYS[-200], "market") == 1000 and at(t, DAYS[-200], "invested") == 1000
    assert at(t, DAYS[-101], "cash") == 0 and at(t, DAYS[-100], "cash") == 50     # dividend arrives as cash
    assert at(t, DAYS[-50], "net_worth") == 1050 and at(t, DAYS[-50], "gain") == 50
    # Selling 4 shares: the 400 stays in the portfolio as cash, so net worth does not drop.
    assert at(t, DAYS[-1], "market") == 600 and at(t, DAYS[-1], "cash") == 450
    assert at(t, DAYS[-1], "invested") == 1000 and at(t, DAYS[-1], "net_worth") == 1050
    assert at(t, DAYS[-1], "gain") == 50
    assert t["by_class"]["equity"][-1] == 600
    assert t["series"]["benchmark"][0] == pytest.approx(1000)                         # rebased to the portfolio


def test_purchases_use_portfolio_cash_before_new_money(client):
    trade(client, "INFY.NS", "BUY", 10, 100, DAYS[-300])        # 1000 new money
    trade(client, "INFY.NS", "SELL", 10, 120, DAYS[-200])       # 1200 cash (the fake price is 100: a 200 gain on the day)
    trade(client, "TCS.NS", "BUY", 5, 100, DAYS[-150])          # 500 paid from cash
    trade(client, "ITC.NS", "BUY", 10, 100, DAYS[-100])         # 700 from cash + 300 new money
    client.get("/api/metrics")
    c = client.get("/api/portfolio-cash").json()
    assert (c["sale_proceeds"], c["spent_from_cash"], c["new_money"]) == (1200, 1200, 1300)
    assert c["balance"] == 0 and c["money_in"] == 1300
    t = client.get("/api/timeline").json()
    assert at(t, DAYS[-160], "cash") == 1200 and at(t, DAYS[-160], "invested") == 1000
    assert at(t, DAYS[-150], "cash") == 700 and at(t, DAYS[-150], "market") == 500
    assert at(t, DAYS[-1], "invested") == 1300 and at(t, DAYS[-1], "market") == 1500
    assert at(t, DAYS[-1], "net_worth") == 1500 and at(t, DAYS[-1], "gain") == 200    # no money counted twice
    assert client.get("/api/metrics?refresh=false").json()["portfolio_cash"] == 0


def test_splits_keep_value_continuous_and_skipped_splits_are_not_doubled(client):
    trade(client, "SPLT.NS", "BUY", 10, 100, DAYS[-300])                             # 10 shares at 100, pre-split
    client.post("/api/corporate-actions", json={"symbol": "SPLT.NS", "kind": "split", "value": 2,
                                                "ex_date": DAYS[-60].isoformat()})
    client.get("/api/metrics")
    t = client.get("/api/timeline").json()
    assert at(t, DAYS[-61], "market") == pytest.approx(1000)                          # 10 x 100 before
    assert at(t, DAYS[-60], "market") == pytest.approx(1000)                          # 20 x 50 after
    review = client.get("/api/corporate-actions/review").json()[0]
    client.post(f"/api/corporate-actions/{review['id']}/review", json={"decision": "skip"})
    t = client.get("/api/timeline").json()                                            # file was already 10 post-split
    assert at(t, DAYS[-61], "market") == pytest.approx(500) and at(t, DAYS[-1], "market") == pytest.approx(500)


def test_cash_stays_until_withdrawn(client):
    trade(client, "TCS.NS", "BUY", 20, 100, DAYS[-300])
    client.post("/api/corporate-actions", json={"symbol": "TCS.NS", "kind": "dividend", "value": 10,
                                                "ex_date": DAYS[-100].isoformat()})
    future = (date.today() + timedelta(days=20)).isoformat()
    client.post("/api/corporate-actions", json={"symbol": "TCS.NS", "kind": "dividend", "value": 99,
                                                "ex_date": future})                    # announced, not paid yet
    trade(client, "TCS.NS", "SELL", 5, 100, DAYS[-80])                               # +500 cash
    client.get("/api/metrics")
    cash = client.get("/api/portfolio-cash").json()
    assert (cash["dividends"], cash["sale_proceeds"], cash["withdrawn"], cash["balance"]) == (200, 500, 0, 700)
    too_much = client.post("/api/portfolio-cash/withdrawals", json={"date": DAYS[-50].isoformat(), "amount": 750})
    assert too_much.status_code == 400 and "700.00" in too_much.json()["detail"]
    early = client.post("/api/portfolio-cash/withdrawals", json={"date": DAYS[-150].isoformat(), "amount": 10})
    assert early.status_code == 400                                                   # nothing in cash yet then
    w = client.post("/api/portfolio-cash/withdrawals",
                    json={"date": DAYS[-50].isoformat(), "amount": 600, "note": "to bank"}).json()
    assert w["balance"] == 100 and w["withdrawals"][0]["note"] == "to bank" and w["money_in"] == 2000 - 600
    # An earlier withdrawal that would leave the later one short is refused.
    clash = client.post("/api/portfolio-cash/withdrawals", json={"date": DAYS[-70].isoformat(), "amount": 650})
    assert clash.status_code == 400 and "too little cash" in clash.json()["detail"]
    assert client.get("/api/metrics?refresh=false").json()["portfolio_cash"] == 100
    wealth = client.get("/api/wealth").json()
    assert wealth["portfolio_cash"] == 100 and {g["group"]: g["value"] for g in wealth["groups"]}["Cash"] == 100
    t = client.get("/api/timeline").json()
    assert at(t, DAYS[-60], "cash") == 700 and at(t, DAYS[-40], "cash") == 100
    assert at(t, DAYS[-1], "gain") == pytest.approx(at(t, DAYS[-1], "market") + 100 - 1400)
    client.delete(f"/api/portfolio-cash/withdrawals/{w['withdrawals'][0]['id']}")
    assert client.get("/api/dividend-cash").json()["balance"] == 700                   # old path still works


def test_other_wealth_over_time(client):
    trade(client, "INFY.NS", "BUY", 1, 100, DAYS[-300])
    client.post("/api/wealth", json={"kind": "fixed_deposit", "amount": 100000, "rate": 8,
                                     "start_date": DAYS[-200].isoformat()})
    client.post("/api/wealth", json={"kind": "ppf", "amount": 50000, "start_date": DAYS[-100].isoformat()})
    client.get("/api/metrics")
    t = client.get("/api/timeline").json()
    g = t["wealth_groups"]
    k = lambda d: t["dates"].index(d.isoformat())  # noqa: E731
    assert g["Deposits"][k(DAYS[-201])] == 0 and g["Deposits"][k(DAYS[-200])] == pytest.approx(100000)
    assert g["Deposits"][-1] > g["Deposits"][k(DAYS[-150])] > 100000                # FD accrues
    assert g["Retirement"][k(DAYS[-101])] == 0 and g["Retirement"][-1] == 50000      # from its start date
    assert at(t, DAYS[-1], "net_worth") == pytest.approx(100 + g["Deposits"][-1] + 50000)


def test_timeline_without_trades(client):
    assert client.get("/api/timeline").json()["dates"] == []
