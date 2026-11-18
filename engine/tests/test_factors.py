"""Carhart four-factor analysis on IIM Ahmedabad's Indian factor data."""
import numpy as np
import pandas as pd
import pytest

from app.market import history
from app.quant import factors

PAGE = """<a href="DATA/2025-08_FourFactors_and_Market_Returns_Daily_SurvivorshipBiasAdjusted.csv">old</a>
<a href="DATA/2025-12_FourFactors_and_Market_Returns_Daily_SurvivorshipBiasAdjusted.csv">daily</a>
<a href="DATA/2025-12_FourFactors_and_Market_Returns_Daily.csv">deprecated</a>"""


def factor_frame(days):
    rng = np.random.default_rng(11)
    n = len(days)
    return pd.DataFrame({"MF": rng.normal(0.0004, 0.010, n), "SMB": rng.normal(0, 0.006, n),
                         "HML": rng.normal(0, 0.005, n), "WML": rng.normal(0, 0.007, n),
                         "RF": np.full(n, 0.00025)}, index=pd.Index(days, name="Date"))


def csv_text(frame):
    pct = frame * 100
    lines = ["Date,SMB,HML,WML,MF,RF", "1993-10-01,1.0,1.0,-0.5,NA,NA"]
    lines += [f"{d},{r.SMB},{r.HML},{r.WML},{r.MF},{r.RF}" for d, r in pct.iterrows()]
    return "\n".join(lines) + "\n"


def test_latest_survivorship_adjusted_daily_file_is_picked():
    assert factors.latest_file(PAGE) == ("2025-12", "DATA/2025-12_FourFactors_and_Market_Returns_Daily_SurvivorshipBiasAdjusted.csv")


def test_csv_is_read_as_decimal_returns_without_missing_rows():
    days = pd.bdate_range("2025-01-01", periods=5).date
    f = factor_frame(days)
    out = factors.parse(csv_text(f).encode())
    assert list(out.columns) == ["MF", "SMB", "HML", "WML", "RF"] and len(out) == 5
    assert out.loc[days[0], "MF"] == pytest.approx(f.loc[days[0], "MF"])


def test_regression_recovers_known_loadings():
    days = pd.bdate_range("2023-01-02", periods=750).date
    f = factor_frame(days)
    rng = np.random.default_rng(5)
    excess = 0.0002 + 1.1 * f.MF + 0.5 * f.SMB - 0.3 * f.HML + 0.2 * f.WML + rng.normal(0, 0.004, len(f))
    fit = factors.regress(excess.to_numpy(), f[["MF", "SMB", "HML", "WML"]].to_numpy())
    assert fit["coef"][1:] == pytest.approx([1.1, 0.5, -0.3, 0.2], abs=0.06)
    assert fit["coef"][0] == pytest.approx(0.0002, abs=0.0004)
    assert fit["t"][1] > 30 and fit["r2"] > 0.8 and fit["n"] == 750
    # standard errors match the textbook formula
    X = np.column_stack([np.ones(len(f)), f[["MF", "SMB", "HML", "WML"]].to_numpy()])
    resid = excess.to_numpy() - X @ fit["coef"]
    se = np.sqrt(np.diag(resid @ resid / (len(f) - 5) * np.linalg.inv(X.T @ X)))
    assert fit["se"] == pytest.approx(se)


@pytest.fixture
def market(client, monkeypatch):
    end = pd.Timestamp("2025-12-31")
    days = pd.bdate_range(end=end, periods=900).date
    f = factor_frame(days)
    rng = np.random.default_rng(9)
    loads = {"AAA.NS": (1.2, 0.8, -0.4, 0.3), "BBB.NS": (0.7, -0.3, 0.6, -0.2), "^NSEI": (1.0, 0, 0, 0)}
    rets = {s: f.RF + b[0] * f.MF + b[1] * f.SMB + b[2] * f.HML + b[3] * f.WML + rng.normal(0, 0.003, len(f))
            for s, b in loads.items()}
    # prices continue past the factor data to today, as real prices do
    later = pd.bdate_range(days[-1] + pd.Timedelta(days=1), pd.Timestamp.today()).date
    px = {s: pd.Series(100 * np.cumprod(1 + np.concatenate([r.to_numpy(), rng.normal(0, 0.01, len(later))])),
                       index=list(days) + list(later)) for s, r in rets.items()}

    def fetch(symbol, start):
        s = px[symbol]
        s = s[s.index >= start]
        return pd.DataFrame({"close": s, "adj_close": s, "dividend": 0.0, "split": 0.0})

    monkeypatch.setattr(history, "fetch", fetch)
    monkeypatch.setattr(factors, "load", lambda cache_dir: ("2025-12", f))
    for sym, q, p in (("AAA", 100, 50.0), ("BBB", 40, 120.0)):
        assert client.post("/api/ledger/trades", json={"symbol": sym, "side": "BUY", "quantity": q, "price": p,
                                                        "traded_at": "2022-01-04T10:00:00"}).status_code == 201
    return client, loads


def test_factor_endpoint_reports_portfolio_and_holding_loadings(market):
    client, loads = market
    res = client.get("/api/factors", params={"window": 756})
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["release"] == "2025-12" and d["data_to"] == "2025-12-31" and d["observations"] == 756
    by = {h["symbol"]: h for h in d["holdings"]}
    for sym in ("AAA.NS", "BBB.NS"):
        got = [by[sym]["loadings"][k]["coef"] for k in ("market", "size", "value", "momentum")]
        assert got == pytest.approx(loads[sym], abs=0.08)
    w = {h["symbol"]: h["weight"] for h in d["holdings"]}
    assert sum(w.values()) == pytest.approx(1.0)
    # the portfolio's loadings are the value-weighted holdings' loadings (OLS is linear)
    for k in ("market", "size", "value", "momentum"):
        assert d["portfolio"]["loadings"][k]["coef"] == pytest.approx(
            sum(w[s] * by[s]["loadings"][k]["coef"] for s in w), abs=1e-9)
    assert 0 < d["portfolio"]["r2"] <= 1 and "t" in d["portfolio"]["alpha"]
    assert any("31 Dec 2025" in x for x in d["notes"])


def test_factor_window_options_and_errors(market, monkeypatch):
    client, _ = market
    assert client.get("/api/factors", params={"window": 100}).status_code == 422
    assert client.get("/api/factors", params={"window": 252}).json()["observations"] == 252

    def unavailable(cache_dir):
        raise OSError("offline")

    monkeypatch.setattr(factors, "load", unavailable)
    res = client.get("/api/factors")
    assert res.status_code == 503 and "IIM Ahmedabad" in res.json()["detail"]


def test_factor_endpoint_without_holdings(client, monkeypatch):
    monkeypatch.setattr(factors, "load", lambda cache_dir: ("2025-12", factor_frame(pd.bdate_range(end="2025-12-31", periods=300).date)))
    d = client.get("/api/factors").json()
    assert d["holdings"] == [] and d["portfolio"] is None
