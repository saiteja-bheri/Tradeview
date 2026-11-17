"""SIP paid daily, weekly, monthly, every 2 months, quarterly, half-yearly or yearly."""
import time

import pytest

from app.quant.projection import SIP_FREQUENCIES, project, sip_schedule

BASE = dict(start_value=0, by_class={"equity": 1}, observations=500, step_up_pct=0, years=10,
            interval="yearly", outlook="past", wealth_items=[], simulations=2000)
# Past performance of 12% a year with (almost) no volatility: every path is the same,
# so results can be checked against compound-interest arithmetic.
CALM = {"return_annualized": 0.12, "volatility_annualized": 1e-9}


def run(freq, amount, **kw):
    return project(metrics=kw.pop("metrics", CALM), monthly_sip=0, sip_amount=amount, sip_frequency=freq,
                   **{**BASE, **kw})


@pytest.mark.parametrize("freq,per_year", SIP_FREQUENCIES.items())
def test_amount_is_per_instalment(freq, per_year):
    r = run(freq, 1000)
    a, s = r["assumptions"], r["summary"]
    assert a["installments_per_year"] == per_year and a["installments"] == per_year * 10
    assert s["invested_total"] == pytest.approx(1000 * per_year * 10)
    assert a["monthly_sip"] == pytest.approx(1000 * per_year / 12)


@pytest.mark.parametrize("freq", list(SIP_FREQUENCIES))
def test_value_matches_compound_interest(freq):
    """Each instalment grows from the day it is paid to the end of the plan."""
    r = run(freq, 1000)
    exact = sum(amt * 1.12 ** ((120 - t) / 12) for t, amt in sip_schedule(1000, freq, 10, 0))
    assert r["summary"]["median"] == pytest.approx(exact, rel=1e-6)
    assert r["summary"]["expected"] == pytest.approx(exact, rel=1e-6)
    assert r["summary"]["median_annual_return"] == pytest.approx(0.12, abs=1e-4)


def test_same_money_paid_earlier_grows_more():
    """₹1.2 lakh a year paid all at once at the start beats the same money spread
    across the year, which beats it spread daily (less time in the market)."""
    finals = {f: run(f, 120_000 / n)["summary"]["median"] for f, n in SIP_FREQUENCIES.items()}
    order = ["yearly", "halfyearly", "quarterly", "bimonthly", "monthly", "weekly", "daily"]
    assert all(finals[a] > finals[b] for a, b in zip(order, order[1:]))
    assert all(run(f, 120_000 / n)["summary"]["invested_total"] == pytest.approx(1_200_000)
               for f, n in SIP_FREQUENCIES.items())


def test_step_up_once_a_year_for_every_frequency():
    r = run("weekly", 500, step_up_pct=10, years=3)
    assert r["summary"]["invested_total"] == pytest.approx(500 * 52 * (1 + 1.1 + 1.21))
    sched = sip_schedule(500, "weekly", 3, 10)
    assert sched[51][1] == pytest.approx(500) and sched[52][1] == pytest.approx(550)   # week 53 steps up


def test_monthly_matches_the_original_monthly_sip():
    risky = {"return_annualized": 0.10, "volatility_annualized": 0.18}
    old = project(metrics=risky, monthly_sip=10_000, **BASE)
    new = run("monthly", 10_000, metrics=risky)
    assert new["summary"]["median"] == pytest.approx(old["summary"]["median"], rel=1e-12)
    assert new["points"][-1]["p10"] == pytest.approx(old["points"][-1]["p10"], rel=1e-12)


def test_daily_is_fast_enough_and_api_accepts_frequencies(client):
    t = time.perf_counter()
    r = run("daily", 500, years=25, simulations=5000, metrics={"return_annualized": 0.1, "volatility_annualized": 0.18})
    assert time.perf_counter() - t < 8 and r["summary"]["invested_total"] == pytest.approx(500 * 250 * 25)
    ok = client.post("/api/projection", json={"sip_amount": 2500, "sip_frequency": "weekly", "years": 5})
    assert ok.status_code == 200 and ok.json()["assumptions"]["sip_frequency"] == "weekly"
    assert client.post("/api/projection", json={"sip_amount": 1, "sip_frequency": "fortnightly"}).status_code == 422
    legacy = client.post("/api/projection", json={"monthly_sip": 5000, "years": 5}).json()
    assert legacy["assumptions"]["sip_frequency"] == "monthly" and legacy["assumptions"]["sip_amount"] == 5000
