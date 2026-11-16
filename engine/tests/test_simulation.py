"""Stress testing, column-mapped imports and the display currency. No network."""
from __future__ import annotations

import io
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market import history
from app.quant import stress
from tests.test_tracking import DAYS, market


def long_market(symbol, start):
    """Like `market`, plus history from 2019 for the benchmark and RELIANCE so
    the COVID crash (17 Jan - 23 Mar 2020) can be replayed: the index falls 38%
    and RELIANCE 30% over that window. TCS has only recent history."""
    if symbol in ("^NSEI", "RELIANCE.NS") and start < date(2019, 6, 1):
        days = pd.bdate_range("2019-01-01", DAYS[-1]).date
        drop = 0.62 if symbol == "^NSEI" else 0.70
        values = np.where(np.array(days) < date(2020, 1, 17), 100.0,
                          np.where(np.array(days) <= date(2020, 3, 23), 100.0 * drop, 120.0))
        rng = np.random.default_rng(len(symbol))
        values = values * (1 + rng.normal(0, 0.0001, len(days)))
        values[list(days).index(min(d for d in days if d >= date(2020, 1, 17)))] = 100.0
        f = pd.DataFrame({"close": values, "adj_close": values, "dividend": 0.0, "split": 0.0}, index=days)
        f.attrs["currency"] = "INR"
        return f
    return market(symbol, start)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "fetch", long_market)
    app = create_app(db_url=f"sqlite:///{(tmp_path / 's.sqlite3').as_posix()}", token="")
    with TestClient(app) as c:
        yield c


def buy(client, symbol, qty, price, when=None, market=None):
    r = client.post("/api/ledger/trades", json={"symbol": symbol, "side": "BUY", "quantity": qty, "price": price,
                                               "traded_at": f"{when or DAYS[-300]}T10:00:00", "market": market})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------- stress testing

def test_conditional_shock_follows_beta():
    rng = np.random.default_rng(0)
    m = rng.normal(0, 0.01, 600)
    asset = np.column_stack([1.5 * m + rng.normal(0, 0.004, 600), 0.5 * m + rng.normal(0, 0.004, 600)])
    values = np.array([60_000.0, 40_000.0])
    r = stress.market_shock(values, asset, m, -0.20, 21)
    b = stress.betas(asset, m)
    assert b[0] == pytest.approx(1.5, abs=0.05) and b[1] == pytest.approx(0.5, abs=0.05)
    assert r["pnl"] == pytest.approx(-0.20 * (60_000 * b[0] + 40_000 * b[1]))
    assert r["low"] < r["pnl"] < r["high"]


def test_monte_carlo_and_correlation_stress_are_consistent():
    rng = np.random.default_rng(1)
    asset = rng.multivariate_normal([0, 0], [[1e-4, 3e-5], [3e-5, 1e-4]], 800)
    values = np.array([50_000.0, 50_000.0])
    mc = stress.monte_carlo(values, asset, 21, 20_000)
    p = mc["percentiles"]
    assert p["p1"] < p["p5"] < p["p50"] < p["p95"] < p["p99"]
    assert mc["expected_shortfall_99"] <= p["p1"] and mc["expected_shortfall_95"] <= p["p5"]
    assert sum(mc["histogram"]["counts"]) == 20_000
    cs = stress.correlation_stress(values, asset, 0.95, 21)
    assert cs["var_stressed"] > cs["var_normal"] > 0
    assert cs["avg_correlation_stressed"] > cs["avg_correlation"]


def test_stress_endpoint_with_crisis_replay(client):
    buy(client, "RELIANCE.NS", 10, 1000.0)
    buy(client, "TCS.NS", 5, 3000.0)
    r = client.post("/api/stress", json={"shock_pct": -25, "horizon_days": 21, "simulations": 2000}).json()
    assert r["portfolio_value"] > 0 and r["observations"] >= 60
    assert any(s["shock"] == -0.25 for s in r["shocks"])
    assert r["custom"]["shock"] == -0.25 and len(r["custom"]["holdings"]) == 2
    assert sum(h["pnl"] for h in r["custom"]["holdings"]) == pytest.approx(r["custom"]["pnl"])
    covid = next(c for c in r["crises"] if c["id"] == "covid")
    assert covid["available"] and covid["market_move"] == pytest.approx(-0.38, abs=0.01)
    rows = {x["symbol"]: x for x in covid["by_holding"]}
    assert rows["RELIANCE.NS"]["method"] == "actual" and rows["RELIANCE.NS"]["move"] == pytest.approx(-0.30, abs=0.01)
    assert rows["TCS.NS"]["method"] == "beta"
    gfc = next(c for c in r["crises"] if c["id"] == "gfc")
    assert gfc["available"] is False                            # no 2008 data in the fake
    assert r["monte_carlo"]["simulations"] == 2000
    assert r["correlation"]["var_stressed"] >= r["correlation"]["var_normal"]


def test_stress_needs_holdings(client):
    assert client.post("/api/stress", json={}).status_code == 409


# ---------------------------------------------------------------- imports

SCRAMBLED = """My Broker - Trade Statement
Client: ABC123
Units,Ticker,Txn Date,Buy/Sell,Exch,Trade Px,Ref No
10,INFY,15-01-2025,B,NSE,1500,R1
2,AAPL,2025-02-03,S,NASDAQ,200,R2
100,VOD,2025-03-01,BUY,LSE,72.5,R3
5,NIFTY25FEB,2025-03-02,BUY,NFO,10,R4
"""


def test_preview_finds_headings_in_any_order(client):
    r = client.post("/api/ledger/import/preview", files={"file": ("t.csv", SCRAMBLED, "text/csv")}).json()
    assert r["broker"] == "generic" and r["header_row"] == 2
    assert r["mapping"]["quantity"] == "Units" and r["mapping"]["symbol"] == "Ticker"
    assert r["mapping"]["date"] == "Txn Date" and r["mapping"]["price"] == "Trade Px"
    assert r["missing"] == [] and len(r["samples"]) == 4


def test_generic_file_imports_automatically_and_from_excel(client):
    r = client.post("/api/ledger/import", files={"file": ("t.csv", SCRAMBLED, "text/csv")}).json()
    assert r["broker"] == "generic" and r["imported"] == 3
    assert any("derivatives" in s for s in r["skipped"])
    syms = {t["symbol"] for t in client.get("/api/ledger/trades").json()}
    assert syms == {"INFY.NS", "AAPL", "VOD.L"}

    from openpyxl import Workbook

    book = Workbook()
    for line in ["Date,Scrip Code,Side,Quantity,Price,Exchange,Trade Num",
                 "03-01-2025,RELIANCE,Buy,4,1250,NSE,7001"]:
        book.active.append(line.split(","))
    buf = io.BytesIO()
    book.save(buf)
    r = client.post("/api/ledger/import", files={"file": ("u.xlsx", buf.getvalue())}).json()
    assert r["broker"] == "upstox" and r["imported"] == 1          # Upstox from Excel


def test_user_chosen_columns_are_used(client):
    odd = "Col A,Col B,Col C,Col D,Col E\n2025-01-15,HDFCBANK,BUY,7,1650\n"
    pre = client.post("/api/ledger/import/preview", files={"file": ("o.csv", odd, "text/csv")}).json()
    assert set(pre["missing"]) >= {"date", "symbol", "quantity"}
    failed = client.post("/api/ledger/import", files={"file": ("o.csv", odd, "text/csv")})
    assert failed.status_code == 400 and "Choose the columns" in failed.json()["detail"]
    chosen = {"date": "Col A", "symbol": "Col B", "side": "Col C", "quantity": "Col D", "price": "Col E"}
    r = client.post("/api/ledger/import", files={"file": ("o.csv", odd, "text/csv")},
                    data={"columns": json.dumps(chosen), "header_row": "0"}).json()
    assert r["imported"] == 1
    assert client.get("/api/ledger/trades").json()[0]["symbol"] == "HDFCBANK.NS"


def test_formats_and_template(client):
    f = client.get("/api/ledger/import/formats").json()
    assert [h["heading"] for h in f["generic"]["headings"]][:7] == ["Date", "Time", "Symbol", "Exchange", "Side",
                                                                   "Quantity", "Price"]
    assert "zerodha" in f["brokers"] and "trade_date" in f["brokers"]["zerodha"]["required"]
    template = client.get("/api/ledger/import/template").text
    r = client.post("/api/ledger/import", files={"file": ("t.csv", template, "text/csv")}).json()
    assert r["imported"] == 3 and r["skipped"] == []                # the template imports as-is


# ---------------------------------------------------------------- display currency

def test_display_currency_converts_and_auto_picks_the_biggest(client):
    buy(client, "AAPL", 100, 100.0, market="INTL")                  # ~$11,000: most of the value
    buy(client, "INFY.NS", 1, 1000.0)
    d = client.get("/api/metrics").json()["display"]
    assert d == {"choice": "INR", "currency": "INR", "inr_per_unit": 1.0}
    client.put("/api/settings", json={"display_currency": "USD"})
    d = client.get("/api/metrics").json()["display"]
    assert d["currency"] == "USD" and d["inr_per_unit"] == 85.0
    client.put("/api/settings", json={"display_currency": "AUTO"})
    assert client.get("/api/metrics").json()["display"]["currency"] == "USD"
    assert client.put("/api/settings", json={"display_currency": "XYZ"}).status_code == 400


def test_stress_covers_rallies_and_the_upside(client):
    buy(client, "RELIANCE.NS", 10, 1000.0)
    buy(client, "TCS.NS", 5, 3000.0)
    r = client.post("/api/stress", json={"shock_pct": 25, "horizon_days": 21, "simulations": 2000}).json()
    assert r["custom"]["shock"] == 0.25 and r["custom"]["pnl"] > 0          # a rally gains
    assert {s["shock"] for s in r["shocks"]} >= {-0.40, -0.10, 0.10, 0.40}
    ups = [s for s in r["shocks"] if s["shock"] > 0]
    assert all(s["pnl"] > 0 for s in ups) and ups == sorted(ups, key=lambda s: s["shock"])
    assert {c["kind"] for c in r["crises"]} == {"crash", "rally"}
    covid_rally = next(c for c in r["crises"] if c["id"] == "covidrally")
    assert covid_rally["available"] and covid_rally["market_move"] > 0       # 62 -> 120 in the fake
    mc = r["monte_carlo"]
    assert mc["expected_gain_95"] >= mc["percentiles"]["p95"] > 0
    assert set(mc["prob_gain"]) == {"5", "10", "20", "30"}
