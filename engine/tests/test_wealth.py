"""Wealth items (cash, deposits, pension, insurance), the SIP projection, and the
wealth section of the AI payload. No network."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.market import history
from app.quant.projection import project
from tests.test_tracking import DAYS, market


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "fetch", market)
    app = create_app(db_url=f"sqlite:///{(tmp_path / 'w.sqlite3').as_posix()}", token="")
    with TestClient(app) as c:
        yield c


def add(client, **body):
    r = client.post("/api/wealth", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_items_are_valued_and_summed_into_net_worth(client):
    year_ago = (date.today() - timedelta(days=365)).isoformat()
    fd = add(client, kind="fixed_deposit", name="SBI FD", amount=100_000, rate=7.0, start_date=year_ago,
             maturity_date=(date.today() + timedelta(days=60)).isoformat())
    assert fd["value"] == pytest.approx(100_000 * (1 + 0.07 / 4) ** 4, rel=1e-3)   # quarterly compounding
    assert fd["matures_in_days"] == 60
    add(client, kind="cash", name="Savings", amount=50_000)
    add(client, kind="ppf", amount=300_000, monthly_contribution=5_000)
    term = add(client, kind="term_insurance", name="Term plan", cover=10_000_000, premium=12_000)
    assert term["value"] == 0 and term["effective_rate"] == 0
    add(client, kind="life_insurance", name="Endowment", amount=80_000, cover=500_000, premium=20_000)

    client.post("/api/ledger/trades", json={"symbol": "INFY.NS", "side": "BUY", "quantity": 10, "price": 1000,
                                           "traded_at": f"{DAYS[-200]}T10:00:00"})
    client.get("/api/metrics")
    w = client.get("/api/wealth").json()
    others = fd["value"] + 50_000 + 300_000 + 80_000
    assert w["other_assets"] == pytest.approx(others)
    assert w["net_worth"] == pytest.approx(w["market_value"] + others)
    groups = {g["group"]: g["value"] for g in w["groups"]}
    assert groups["Retirement"] == 300_000 and groups["Cash"] == 50_000 and groups["Insurance"] == 80_000
    assert w["liquidity"]["cash"] == 50_000 and w["liquidity"]["locked"] == 380_000
    assert w["protection"] == {"life_cover": 10_500_000, "annual_premium": 32_000, "policies": 2}
    assert w["monthly_contributions"] == 5_000
    assert [m["name"] for m in w["maturing_within_90_days"]] == ["SBI FD"]


def test_items_can_be_edited_deleted_and_are_validated(client):
    assert client.post("/api/wealth", json={"kind": "fixed_deposit", "amount": 1000}).status_code == 400
    bad = {"kind": "ppf", "amount": 1, "start_date": "2025-01-01", "maturity_date": "2024-01-01"}
    assert client.post("/api/wealth", json=bad).status_code == 400
    assert client.post("/api/wealth", json={"kind": "crypto", "amount": 1}).status_code == 422
    item = add(client, kind="epf", amount=200_000)
    assert item["effective_rate"] == 8.25                                          # default EPF rate
    edited = client.put(f"/api/wealth/{item['id']}", json={"kind": "epf", "amount": 210_000, "rate": 8.1}).json()
    assert edited["value"] == 210_000 and edited["effective_rate"] == 8.1
    assert client.delete(f"/api/wealth/{item['id']}").json() == {"deleted": item["id"]}
    assert client.get("/api/wealth").json()["items"] == []


def test_sip_projection_matches_the_closed_form():
    r = project(start_value=0, by_class={}, metrics={}, observations=0, monthly_sip=10_000, step_up_pct=0,
                years=10, interval="yearly", outlook="neutral", wealth_items=[], simulations=4000)
    rm = 1.11 ** (1 / 12) - 1
    closed = sum(10_000 * (1 + rm) ** (120 - k) for k in range(120))              # paid at the start of each month
    s = r["summary"]
    assert s["expected"] == pytest.approx(closed, rel=1e-6)
    assert s["invested_total"] == 1_200_000
    assert s["bad_case"] < s["median"] < s["good_case"]
    assert [p["month"] for p in r["points"]] == list(range(0, 121, 12))           # equal yearly intervals
    assert r["assumptions"]["expected_return"] == pytest.approx(0.11)
    assert 0.08 < s["median_annual_return"] < 0.11


def test_step_up_and_intervals():
    flat = project(start_value=0, by_class={}, metrics={}, observations=0, monthly_sip=1000, step_up_pct=0,
                   years=2, interval="quarterly", outlook="cautious", wealth_items=[], simulations=500)
    up = project(start_value=0, by_class={}, metrics={}, observations=0, monthly_sip=1000, step_up_pct=10,
                 years=2, interval="monthly", outlook="cautious", wealth_items=[], simulations=500)
    assert [p["month"] for p in flat["points"]] == [0, 3, 6, 9, 12, 15, 18, 21, 24]
    assert len(up["points"]) == 25
    assert up["summary"]["invested_total"] == pytest.approx(12 * 1000 + 12 * 1100)


def test_past_performance_needs_history_and_warns_on_extremes():
    weak = project(start_value=100_000, by_class={"equity": 100_000}, metrics={}, observations=10,
                   monthly_sip=0, step_up_pct=0, years=1, interval="yearly", outlook="past", wealth_items=[])
    assert weak["assumptions"]["source"] == "neutral" and weak["warnings"]
    hot = project(start_value=100_000, by_class={"equity": 100_000},
                  metrics={"return_annualized": 0.45, "volatility_annualized": 0.2}, observations=252,
                  monthly_sip=0, step_up_pct=0, years=1, interval="yearly", outlook="past", wealth_items=[])
    assert hot["assumptions"]["source"] == "past" and "rarely repeats" in hot["warnings"][0]


def test_projection_endpoint_continues_the_portfolio_with_wealth(client):
    client.post("/api/ledger/trades", json={"symbol": "INFY.NS", "side": "BUY", "quantity": 10, "price": 1000,
                                           "traded_at": f"{DAYS[-300]}T10:00:00"})
    client.get("/api/metrics")
    add(client, kind="ppf", amount=100_000, rate=7.1, monthly_contribution=1_000)
    cont = client.post("/api/projection", json={"monthly_sip": 5000, "years": 5, "interval": "yearly"}).json()
    start = cont["points"][0]
    assert start["invested"] == pytest.approx(cont["assumptions"]["start_value"]) and start["invested"] > 0
    assert start["other"] == 100_000 and cont["points"][-1]["other"] > 100_000 + 60 * 1_000
    fresh = client.post("/api/projection", json={"mode": "fresh", "monthly_sip": 5000, "years": 5,
                                                 "include_wealth": False}).json()
    assert fresh["points"][0]["invested"] == 0 and fresh["points"][-1]["other"] == 0
    assert fresh["summary"]["invested_total"] == 5000 * 60
    past = client.post("/api/projection", json={"outlook": "past", "years": 3}).json()
    assert past["assumptions"]["source"] in ("past", "neutral")


def test_ai_payload_includes_wealth_only_when_entered(client):
    from app.ai.memo import build_payload, unverified_numbers

    client.post("/api/ledger/trades", json={"symbol": "INFY.NS", "side": "BUY", "quantity": 10, "price": 1000,
                                           "traded_at": f"{DAYS[-300]}T10:00:00"})
    client.get("/api/metrics")
    assert "wealth" not in client.get("/api/insight/preview").json()
    add(client, kind="cash", amount=40_000)
    add(client, kind="term_insurance", cover=5_000_000, premium=9_000)
    payload = client.get("/api/insight/preview").json()
    w = payload["wealth"]
    assert w["life_cover_inr"] == 5_000_000 and w["insurance_premium_per_year_inr"] == 9_000
    assert w["cash_pct"] is not None and 0 < w["cash_pct"] < 100
    text = f"Cash is {w['cash_pct']}% of net worth and cover is 5,000,000 against a premium of 9,000."
    assert unverified_numbers(text, payload) == []


# ---------------------------------------------------------------- tax and deposit renewal

def test_gains_tax_applies_above_the_exemption_only():
    from app.quant.projection import after_tax

    assert after_tax(500_000, 300_000, 12.5, 125_000) == pytest.approx(500_000 - 0.125 * 75_000)
    assert after_tax(400_000, 300_000, 12.5, 125_000) == 400_000              # gain within the exemption
    assert after_tax(250_000, 300_000, 12.5, 0) == 250_000                    # a loss is not taxed
    r = project(start_value=0, by_class={}, metrics={}, observations=0, monthly_sip=10_000, step_up_pct=0,
                years=10, interval="yearly", outlook="neutral", wealth_items=[], simulations=2000,
                tax_gains_pct=12.5, gains_exemption=125_000)
    s = r["summary"]
    assert s["median_after_tax"] == pytest.approx(s["median"] - 0.125 * (s["median"] - 1_200_000 - 125_000))
    assert s["tax_on_median"] > 0 and s["median_annual_return_after_tax"] < s["median_annual_return"]


def test_existing_gains_count_through_the_cost_basis():
    base = dict(start_value=1_000_000, by_class={"equity": 1_000_000}, metrics={}, observations=0, monthly_sip=0,
                step_up_pct=0, years=1, interval="yearly", outlook="cautious", wealth_items=[], simulations=500,
                tax_gains_pct=10, gains_exemption=0)
    bought_cheap = project(**base, start_cost=600_000)          # 4 lakh of gains already in the portfolio
    bought_at_value = project(**base)
    assert bought_cheap["summary"]["tax_on_median"] > bought_at_value["summary"]["tax_on_median"] + 39_000


def test_interest_tax_and_deposit_maturity():
    from types import SimpleNamespace

    from app.quant.projection import _other_paths

    today = date.today()
    fd = SimpleNamespace(kind="fixed_deposit", amount=100_000, rate=8.0, start_date=today,
                         maturity_date=today + timedelta(days=365), monthly_contribution=0.0)
    ppf = SimpleNamespace(kind="ppf", amount=100_000, rate=7.1, start_date=None, maturity_date=None,
                          monthly_contribution=0.0)
    gross = _other_paths([fd], 24)[0][-1]
    taxed = _other_paths([fd], 24, tax_interest_pct=30)[0][-1]
    assert taxed == pytest.approx(100_000 * (1 + 0.08 / 12 * 0.7) ** 24, rel=1e-6) and taxed < gross
    assert _other_paths([ppf], 24, tax_interest_pct=30)[0][-1] == _other_paths([ppf], 24)[0][-1]   # PPF untaxed
    lapsed = _other_paths([fd], 24, renew_deposits=False)[0]
    first_year = 100_000 * (1 + 0.08 / 12) ** 12
    assert lapsed[12] == pytest.approx(first_year, rel=1e-6)
    assert lapsed[24] == pytest.approx(first_year * (1 + 0.03 / 12) ** 12, rel=1e-6)          # savings rate after maturity
