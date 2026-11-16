"""Mutual funds, gold and commodities, bonds, returns (XIRR) and BSE
corporate actions. All data sources are faked; nothing touches the network."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.brokers import http
from app.main import create_app
from app.market import commodities, history
from tests.conftest import fake_fetch


def make(tmp_path):
    return create_app(db_url=f"sqlite:///{(tmp_path / 'a.sqlite3').as_posix()}", token="")


def fake_mfapi(code="122639", start_nav=50.0):
    """mfapi.in responses: 300 business days of NAVs, newest first, plus search."""
    days = pd.bdate_range(end=pd.Timestamp.today().normalize() - pd.Timedelta(days=1), periods=300)
    navs = start_nav * np.cumprod(1 + np.random.default_rng(3).normal(0.0005, 0.006, len(days)))
    data = [{"date": d.strftime("%d-%m-%Y"), "nav": f"{n:.4f}"} for d, n in zip(days[::-1], navs[::-1])]
    body = {"meta": {"scheme_code": int(code), "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                     "isin_growth": "INF879O01027", "scheme_category": "Equity Scheme - Flexi Cap Fund",
                     "fund_house": "PPFAS Mutual Fund"}, "data": data, "status": "SUCCESS"}

    def get_bytes(url, headers=None, timeout=30):
        if "/search?" in url:
            return json.dumps([{"schemeCode": 122639,
                                "schemeName": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"}]).encode()
        assert url.endswith(f"/mf/{code}"), url
        return json.dumps(body).encode()

    return get_bytes, navs


@pytest.fixture
def offline_market(monkeypatch):
    """Yahoo (stocks, futures, FX) from the deterministic fake; mfapi from fake_mfapi."""
    monkeypatch.setattr(history, "fetch", fake_fetch)
    get_bytes, navs = fake_mfapi()
    monkeypatch.setattr(http, "get_bytes", get_bytes)
    return navs


def trade(client, symbol, side, qty, price, when, name=None):
    r = client.post("/api/ledger/trades", json={"symbol": symbol, "side": side, "quantity": qty,
                                               "price": price, "traded_at": when, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- symbols

def test_new_symbol_kinds_are_validated(tmp_path):
    with TestClient(make(tmp_path)) as client:
        bad = [("MF:abc", "MF:"), ("CMDTY:UNOBTAINIUM", "Unknown commodity"), ("BOND:GOI2033", "BONDS first")]
        for symbol, message in bad:
            r = client.post("/api/ledger/trades", json={"symbol": symbol, "side": "BUY", "quantity": 1,
                                                       "price": 1, "traded_at": "2025-01-02T10:00:00"})
            assert r.status_code == 400 and message in r.json()["detail"], (symbol, r.text)


def test_old_ledger_gets_asset_class_column(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    url = f"sqlite:///{(tmp_path / 'old.sqlite3').as_posix()}"
    with create_engine(url).begin() as conn:
        conn.execute(text("CREATE TABLE instruments (symbol VARCHAR PRIMARY KEY, name VARCHAR, "
                          "exchange VARCHAR, scrip_code VARCHAR)"))
    from app.db.models import make_sessionmaker

    make_sessionmaker(url)
    cols = {c["name"] for c in inspect(create_engine(url)).get_columns("instruments")}
    assert {"isin", "asset_class"} <= cols


# ---------------------------------------------------------------- mutual funds

def test_mutual_fund_is_priced_from_amfi_navs_with_returns(tmp_path, offline_market):
    navs = offline_market
    with TestClient(make(tmp_path)) as client:
        found = client.get("/api/search", params={"q": "parag parikh"}).json()["results"]
        fund = next(r for r in found if r["symbol"] == "MF:122639")
        assert fund["asset_class"] == "mutual_fund" and "Flexi Cap" in fund["name"]

        start = (date.today() - timedelta(days=400)).isoformat() + "T10:00:00"
        trade(client, "MF:122639", "BUY", 100, 40.0, start, name=fund["name"])
        data = client.get("/api/metrics").json()
        h = next(x for x in data["holdings"] if x["symbol"] == "MF:122639")
        assert h["asset_class"] == "mutual_fund"
        assert h["last"] == pytest.approx(navs[-1], rel=1e-4)
        assert h["value"] == pytest.approx(100 * navs[-1], rel=1e-4)
        assert h["total_return"] == pytest.approx(100 * (navs[-1] - 40.0), rel=1e-4)
        assert h["xirr"] is not None
        assert data["allocation"] == [{"asset_class": "mutual_fund", "value": pytest.approx(h["value"]),
                                       "weight": 1.0}]


# ---------------------------------------------------------------- gold and commodities

def test_commodity_price_is_converted_to_inr_per_unit():
    days = pd.bdate_range("2025-01-01", periods=5).date

    def yahoo(symbol, start):
        price = {"GC=F": 2000.0, "SI=F": 30.0, "USDINR=X": 85.0}[symbol]
        idx = days if symbol != "USDINR=X" else days[:-1]  # FX missing on the last day: carried forward
        return pd.DataFrame({"close": price, "adj_close": price, "dividend": 0.0, "split": 0.0}, index=idx)

    gold = commodities.fetch("CMDTY:GOLD", days[0], yahoo=yahoo)
    assert len(gold) == 5
    assert gold["close"].iloc[-1] == pytest.approx(2000 * 85 / 31.1034768)   # ≈ ₹5,465 per gram
    silver = commodities.fetch("CMDTY:SILVER", days[0], yahoo=yahoo)
    assert silver["close"].iloc[0] == pytest.approx(30 * 85 * 1000 / 31.1034768)  # per kg
    with pytest.raises(ValueError):
        commodities.fetch("CMDTY:UNOBTAINIUM", days[0], yahoo=yahoo)


def test_gold_holding_and_gold_etf_are_both_gold(tmp_path, offline_market):
    with TestClient(make(tmp_path)) as client:
        assert any(c["symbol"] == "CMDTY:GOLD" for c in client.get("/api/commodities").json())
        assert client.get("/api/search", params={"q": "gold"}).json()["results"][0]["symbol"] == "CMDTY:GOLD"
        when = (date.today() - timedelta(days=200)).isoformat() + "T10:00:00"
        trade(client, "CMDTY:GOLD", "BUY", 10, 7000.0, when)          # 10 grams
        trade(client, "GOLDBEES.NS", "BUY", 100, 60.0, when, name="Nippon India ETF Gold BeES")
        trade(client, "INFY.NS", "BUY", 5, 1500.0, when, name="Infosys")
        data = client.get("/api/metrics").json()
        classes = {h["symbol"]: h["asset_class"] for h in data["holdings"]}
        assert classes == {"CMDTY:GOLD": "gold", "GOLDBEES.NS": "gold", "INFY.NS": "equity"}
        alloc = {a["asset_class"]: a["weight"] for a in data["allocation"]}
        assert set(alloc) == {"gold", "equity"} and sum(alloc.values()) == pytest.approx(1.0)

        r = client.put("/api/instruments/GOLDBEES.NS/asset-class", json={"asset_class": "etf"})
        assert r.json()["asset_class"] == "etf"
        classes = {h["symbol"]: h["asset_class"] for h in client.get("/api/metrics?refresh=false").json()["holdings"]}
        assert classes["GOLDBEES.NS"] == "etf"


# ---------------------------------------------------------------- bonds

def test_bond_coupons_are_income_and_maturity_is_flagged(tmp_path):
    with TestClient(make(tmp_path)) as client:
        maturity = date.today() + timedelta(days=3 * 365)
        r = client.put("/api/bonds/GOI2028", json={"name": "7.10% GS 2028", "face_value": 1000,
                                                   "coupon_rate": 7.2, "frequency": 2,
                                                   "maturity": maturity.isoformat(), "price": 1012.5})
        assert r.status_code == 200 and r.json()["coupon_per_bond"] == 36.0
        bought = (date.today() - timedelta(days=500)).isoformat() + "T10:00:00"
        trade(client, "BOND:GOI2028", "BUY", 10, 990.0, bought)
        data = client.get("/api/metrics").json()
        h = next(x for x in data["holdings"] if x["symbol"] == "BOND:GOI2028")
        assert h["asset_class"] == "bond" and h["name"] == "7.10% GS 2028"
        assert h["last"] == 1012.5 and h["value"] == 10125.0
        # 500 days held: two or three half-yearly coupons of ₹36 on 10 bonds
        assert h["dividends"] in (720.0, 1080.0)
        coupons = [a for a in client.get("/api/corporate-actions", params={"symbol": "BOND:GOI2028"}).json()
                   if a["source"] == "coupon"]
        assert coupons and all(a["value"] == 36.0 for a in coupons)
        assert h["total_return"] == pytest.approx(10125.0 - 9900.0 + h["dividends"])
        assert client.delete("/api/bonds/BOND:GOI2028").status_code == 409

        client.put("/api/bonds/OLD2020", json={"name": "Matured", "coupon_rate": 8, "frequency": 1,
                                               "maturity": "2024-06-30"})
        trade(client, "BOND:OLD2020", "BUY", 1, 1000.0, "2021-01-04T10:00:00")
        warnings = client.get("/api/metrics?refresh=true").json()["warnings"]
        assert any(w.startswith("BOND:OLD2020 matured on 30 Jun 2024") for w in warnings)


# ---------------------------------------------------------------- returns

def test_xirr_and_total_return_include_dividends(tmp_path, monkeypatch):
    from app.quant.returns import xirr

    assert xirr([(date(2025, 1, 1), -1000), (date(2026, 1, 1), 1100)]) == pytest.approx(0.10)
    assert xirr([(date(2025, 1, 1), -1000)]) is None

    def flat(symbol, start):
        days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300).date
        return pd.DataFrame({"close": 110.0, "adj_close": 110.0, "dividend": 0.0, "split": 0.0}, index=days)

    monkeypatch.setattr(history, "fetch", flat)
    with TestClient(make(tmp_path)) as client:
        one_year_ago = (date.today() - timedelta(days=365)).isoformat() + "T10:00:00"
        trade(client, "ITC.NS", "BUY", 100, 100.0, one_year_ago)
        client.post("/api/corporate-actions", json={"symbol": "ITC.NS", "kind": "dividend", "value": 5,
                                                     "ex_date": (date.today() - timedelta(days=100)).isoformat()})
        data = client.get("/api/metrics").json()
        h = data["holdings"][0]
        # ₹10,000 in; worth ₹11,000 plus ₹500 dividends: 15% total, about 15% a year
        assert h["total_return"] == pytest.approx(1500.0) and h["total_return_pct"] == pytest.approx(0.15)
        assert h["xirr"] == pytest.approx(0.155, abs=0.01)
        assert data["returns"]["invested"] == 10000.0 and data["returns"]["total_return_pct"] == pytest.approx(0.15)


# ---------------------------------------------------------------- BSE corporate actions

class FakeBse:
    def __init__(self):
        pass

    def lookup(self, text):
        return None

    def getScripCode(self, name):
        return {"INFY": "500209", "TCS": "532540"}[name]

    def actions(self, segment, scripcode, from_date, to_date):
        if scripcode == "500209":
            return [{"Purpose": "Bonus issue 1:1", "exdate": (date.today() - timedelta(days=30)).strftime("%Y%m%d")},
                    {"Purpose": "Final Dividend - Rs. - 20.0000",
                     "exdate": (date.today() - timedelta(days=60)).strftime("%Y%m%d")}]
        return []

    def exit(self):
        pass


def test_bse_sync_adds_bonus_and_dividends_once(tmp_path):
    app = make(tmp_path)
    app.state.bse_factory = FakeBse
    with TestClient(app) as client:
        trade(client, "INFY.NS", "BUY", 10, 1500.0, (date.today() - timedelta(days=90)).isoformat() + "T10:00:00")
        trade(client, "TCS.NS", "BUY", 2, 4000.0, (date.today() - timedelta(days=90)).isoformat() + "T10:00:00")
        trade(client, "MF:122639", "BUY", 1, 50.0, (date.today() - timedelta(days=90)).isoformat() + "T10:00:00")
        first = client.post("/api/corporate-actions/bse-sync").json()
        assert first["checked"] == 2                         # funds are skipped
        assert sorted((a["symbol"], a["kind"]) for a in first["added"]) == [("INFY.NS", "bonus"), ("INFY.NS", "dividend")]
        again = client.post("/api/corporate-actions/bse-sync").json()
        assert again["added"] == [] and again["already_recorded"] == 2
        infy = next(h for h in client.get("/api/portfolio/holdings").json()["holdings"] if h["symbol"] == "INFY.NS")
        assert infy["quantity"] == 20 and infy["avg_cost"] == 750.0 and infy["dividends"] == 200.0


def test_bse_sync_without_package_explains_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "bse", None)
    with TestClient(make(tmp_path)) as client:
        trade(client, "INFY.NS", "BUY", 1, 1500.0, "2025-01-02T10:00:00")
        r = client.post("/api/corporate-actions/bse-sync")
        assert r.status_code == 501 and "pip install bse" in r.json()["detail"]
