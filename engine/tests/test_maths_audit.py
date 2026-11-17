"""Regression tests for the maths audit of 2026-11-17."""
import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from app.ledger.positions import build_positions
from app.market import history
from app.quant import projection, returns, service, stress
from tests.conftest import fake_fetch
from tests.test_api import upload


def t(sym, side, qty, price, day):
    return SimpleNamespace(symbol=sym, side=side, quantity=qty, price=price, traded_at=datetime.fromisoformat(day))


def test_portfolio_xirr_ignores_unpriced_holdings():
    """An unpriced holding (an FD typed in as a trade, a delisted stock) has no
    closing value; its purchase must not read as money lost."""
    trades = [t("A", "BUY", 10, 100, "2024-01-01"), t("FD", "BUY", 1, 100_000, "2024-01-01")]
    pos = build_positions(trades, [])
    today = date(2025, 1, 1)
    per, port = returns.compute_returns(trades, pos, {"A": 1100.0}, today=today)
    only_a, _ = returns.compute_returns(trades[:1], build_positions(trades[:1], []), {"A": 1100.0}, today=today)
    assert per["FD"]["xirr"] is None
    assert port["xirr"] == pytest.approx(only_a["A"]["xirr"], rel=1e-6)
    assert port["xirr"] == pytest.approx(0.10, abs=1e-3)          # 1000 -> 1100 in a year
    assert port["total_return_pct"] == pytest.approx(0.10)       # and it agrees with total return


def test_correlation_stress_survives_a_flat_priced_holding():
    rng = np.random.default_rng(2)
    asset = np.column_stack([rng.normal(0, 0.01, 300), rng.normal(0, 0.012, 300), np.zeros(300)])
    out = stress.correlation_stress(np.array([100.0, 100.0, 50.0]), asset, 0.95, 1)
    assert math.isfinite(out["var_normal"]) and math.isfinite(out["var_stressed"])
    assert out["var_stressed"] >= out["var_normal"]
    # the flat holding adds no rupee risk: the same VaR as the two risky ones alone
    two = stress.correlation_stress(np.array([100.0, 100.0]), asset[:, :2], 0.95, 1)
    assert out["var_normal"] == pytest.approx(two["var_normal"], rel=1e-9)


def test_past_outlook_median_reproduces_past_compound_growth():
    """With past performance of 10% a year compound and 20% volatility, the
    likely (median) path should grow ~10% a year, not ~8%."""
    r = projection.project(start_value=100_000, by_class={"equity": 100_000},
                           metrics={"return_annualized": 0.10, "volatility_annualized": 0.20}, observations=500,
                           monthly_sip=0, step_up_pct=0, years=10, interval="yearly", outlook="past",
                           wealth_items=[], simulations=20_000)
    assert r["assumptions"]["expected_return"] == pytest.approx(1.10 * math.exp(0.02) - 1)
    assert r["summary"]["median"] == pytest.approx(100_000 * 1.10 ** 10, rel=0.03)
    assert r["summary"]["median_annual_return"] == pytest.approx(0.10, abs=0.005)


def test_other_assets_put_in_stops_when_a_deposit_matures():
    today = date.today()
    rd = SimpleNamespace(kind="recurring_deposit", amount=10_000, rate=7.0, start_date=today,
                         maturity_date=today + timedelta(days=200), monthly_contribution=1_000.0)
    _, put_in = projection._other_paths([rd], 24, renew_deposits=False, today=today)
    months_paid = (rd.maturity_date.year - today.year) * 12 + rd.maturity_date.month - today.month
    assert put_in[-1] == pytest.approx(10_000 + 1_000 * months_paid)
    _, renewed = projection._other_paths([rd], 24, renew_deposits=True, today=today)
    assert renewed[-1] == pytest.approx(10_000 + 1_000 * 24)


def test_foreign_index_benchmark_is_converted_to_rupees(client, upstox_csv, monkeypatch):
    """^GSPC was taken as an INR series, so beta mixed rupee holdings with a
    dollar index. Now it is converted at each day's USD/INR rate."""
    from app.market import fx
    assert fx.currency_of("^GSPC") == "USD" and fx.currency_of("^NSEI") == "INR"
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)
    client.put("/api/settings", json={"benchmark": "^GSPC"})
    m = client.get("/api/metrics").json()
    cached = {s["symbol"] for s in client.get("/api/cache").json()["symbols"]}
    assert "USDINR=X" in cached                                     # the rate was fetched for the benchmark
    with client.app.state.sessionmaker() as s:
        close, _ = history.load_prices(s, ["^GSPC", "USDINR=X"])
        held = [h["symbol"] for h in m["holdings"] if h["value"]]
        _, adj, _, _, _ = service.inr_prices(s, held + ["^GSPC"])
    ratio = (adj["^GSPC"] / close["^GSPC"]).dropna()
    assert ratio.iloc[-1] == pytest.approx(close["USDINR=X"].dropna().iloc[-1])   # INR per USD applied
    tl = client.get("/api/timeline").json()
    assert tl["series"]["benchmark"] is not None


def test_benchmark_refresh_saves_reported_currency_without_breaking(client, upstox_csv, monkeypatch):
    """Yahoo reports a currency for an unheld index; saving it must not clash
    with the refreshed-stamp row (a variable-name clash once broke every refresh)."""
    def fetch_with_ccy(symbol, start):
        frame = fake_fetch(symbol, start)
        frame.attrs["currency"] = "USD" if symbol == "^GSPC" else "INR"
        return frame

    monkeypatch.setattr(history, "fetch", fetch_with_ccy)
    upload(client, upstox_csv)
    client.put("/api/settings", json={"benchmark": "^GSPC"})
    m = client.get("/api/metrics").json()
    assert not [w for w in m["warnings"] if "Could not refresh" in w], m["warnings"]
    assert m["metrics"]["beta"] is not None
    with client.app.state.sessionmaker() as s:
        from app.db.models import Setting
        assert s.get(Setting, "currency:^GSPC").value == "USD"
        assert s.get(Setting, "refreshed:^GSPC") is not None


def test_period_returns_match_prices(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)
    client.get("/api/metrics")                                    # download prices
    r = client.get("/api/period-returns", params={"period": "1M", "live": "false"}).json()
    assert r["returns"] and r["benchmark_return"] is not None
    sym = next(iter(r["returns"]))
    bars = client.get(f"/api/prices/{sym}", params={"days": 120}).json()["bars"]
    by_day = {b["date"]: b for b in bars}
    start, end = by_day[r["from"]], by_day[r["to"]]
    key = "adj_close" if "adj_close" in start else "close"
    assert r["returns"][sym] == pytest.approx(end[key] / start[key] - 1, rel=1e-9)
    for p in ("1D", "1W", "3M", "6M", "1Y", "YTD"):
        assert client.get("/api/period-returns", params={"period": p}).status_code == 200
    assert client.get("/api/period-returns", params={"period": "2D"}).status_code == 422
