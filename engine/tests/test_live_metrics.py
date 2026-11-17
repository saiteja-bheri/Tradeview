"""Beta on mismatched calendars, live recomputation, rolling metrics, the
live stream's resilience, and the optimiser's custom constraints."""
import asyncio
import json
import math
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.market import history
from app.market.live import LiveHub
from app.quant import metrics as qm
from app.quant import optimizer
from app.quant import service
from tests.conftest import fake_fetch
from tests.test_api import upload


# ------------------------------------------------------------ calendar alignment

def test_aligned_returns_uses_benchmark_calendar():
    """A benchmark closed on days the stock trades must not create zero
    benchmark returns: that would pull beta towards zero."""
    days = pd.bdate_range("2024-01-01", periods=400).date
    rng = np.random.default_rng(3)
    m = rng.normal(0.0005, 0.01, len(days))
    stock = 1.5 * m + rng.normal(0, 0.002, len(days))
    prices = pd.DataFrame({"S": 100 * np.cumprod(1 + stock), "B": 100 * np.cumprod(1 + m)}, index=days)
    # The benchmark's market is shut every Friday; the stock's is not.
    fridays = [d for d in days if d.weekday() == 4]
    prices.loc[fridays, "B"] = np.nan

    naive = prices.ffill(limit=5).pct_change(fill_method=None).dropna()
    aligned = qm.aligned_returns(prices, ["S", "B"], "B")
    assert not any(d.weekday() == 4 for d in aligned.index)
    b_naive = qm.beta(naive["S"], naive["B"])
    b_aligned = qm.beta(aligned["S"], aligned["B"])
    assert b_aligned == pytest.approx(1.5, abs=0.1)
    assert b_naive < b_aligned - 0.2            # the old way was biased low


def test_rolling_metrics_match_point_metrics():
    rng = np.random.default_rng(1)
    b = pd.Series(rng.normal(0.0004, 0.01, 300))
    r = 0.8 * b + rng.normal(0.0002, 0.006, 300)
    roll = qm.rolling_metrics(r, b, 0.065, 63)
    assert len(roll) == 300 - 63 + 1
    tail_r, tail_b = r.iloc[-63:], b.iloc[-63:]
    last = roll.iloc[-1]
    assert last["sharpe"] == pytest.approx(qm.sharpe_ratio(tail_r, 0.065))
    assert last["sortino"] == pytest.approx(qm.sortino_ratio(tail_r, 0.065))
    assert last["beta"] == pytest.approx(qm.beta(tail_r, tail_b))
    assert last["alpha"] == pytest.approx(qm.jensens_alpha_annualized(tail_r, tail_b, 0.065))
    assert last["volatility"] == pytest.approx(qm.annualized_volatility(tail_r))


# ------------------------------------------------------------ benchmark & live

def test_benchmark_change_recomputes_beta(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)
    nifty = client.get("/api/metrics").json()
    client.put("/api/settings", json={"benchmark": "RELIANCE.NS"})   # a holding as benchmark
    rel = client.get("/api/metrics").json()
    assert rel["params"]["benchmark"] == "RELIANCE.NS"
    assert rel["metrics"]["beta"] != pytest.approx(nifty["metrics"]["beta"])
    row = next(h for h in rel["holdings"] if h["symbol"] == "RELIANCE.NS")
    assert row["beta"] == pytest.approx(1.0)                      # itself against itself


def test_live_quotes_move_beta_and_sharpe(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)
    base = client.get("/api/metrics", params={"live": "false"}).json()
    assert base["live"] is False
    held = [h["symbol"] for h in base["holdings"] if h["value"]]
    hub = client.app.state.hub
    assert hub is None                                            # tests run without a feed

    # Feed the live bar straight through the service: benchmark +5%, holdings flat.
    with client.app.state.sessionmaker() as s:
        close, _ = history.load_prices(s, held + ["^NSEI"])
        last = {c: float(close[c].dropna().iloc[-1]) for c in close.columns}
        now = time.time()
        quotes = {c: {"ltp": last[c] * (1.05 if c == "^NSEI" else 1.0), "ts": now} for c in last}
        live = service.compute(s, refresh=False, quotes=quotes)
        assert live["live"] is True
        assert live["metrics"]["beta"] != pytest.approx(base["metrics"]["beta"])
        assert live["as_of"] == date.today().isoformat()

        # A missing quote for a listed holding means no live bar (no fake 0% day).
        partial = {k: v for k, v in quotes.items() if k != held[0]}
        assert service.compute(s, refresh=False, quotes=partial)["live"] is False
        # Stale quotes (yesterday) are ignored.
        old = {k: {**v, "ts": now - 2 * 86400} for k, v in quotes.items()}
        assert service.compute(s, refresh=False, quotes=old)["live"] is False


def test_rolling_endpoint(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)
    client.get("/api/metrics")                   # downloads prices; /rolling reads the cache only
    r = client.get("/api/rolling", params={"window": 63}).json()
    assert r["window"] == 63 and len(r["dates"]) == len(r["series"]["sharpe"]) > 100
    m = client.get("/api/metrics", params={"lookback_days": 63}).json()["metrics"]
    assert r["series"]["sharpe"][-1] == pytest.approx(m["sharpe"])
    assert r["series"]["beta"][-1] == pytest.approx(m["beta"])
    assert client.get("/api/rolling", params={"window": 5}).status_code == 422


# ------------------------------------------------------------ live stream

class _Feed:
    name = "test"
    retry_seconds = 0.01

    async def run(self, hub):
        await asyncio.sleep(3600)


def _hub(client):
    return LiveHub(client.app.state.sessionmaker, _Feed())


def test_nan_quotes_are_dropped_and_snapshot_is_strict_json(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)
    hub = _hub(client)
    hub.on_quote("RELIANCE.NS", float("nan"), 100.0)
    hub.on_quote("TCS.NS", "bad", None)
    hub.on_quote("INFY.NS", 1500.0, float("nan"))
    assert set(hub.quotes) == {"INFY.NS"}
    assert hub.quotes["INFY.NS"]["prev_close"] is None and hub.quotes["INFY.NS"]["change"] is None
    json.dumps(hub.safe_snapshot(), allow_nan=False)              # raises on NaN


def test_broadcast_survives_snapshot_failure(client, monkeypatch):
    hub = _hub(client)
    sent: list[str] = []

    class WS:
        async def send_text(self, text):
            sent.append(text)

    calls = {"n": 0}

    def boom(quotes=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return {"type": "snapshot", "status": hub.status, "quotes": quotes, "portfolio": None}

    monkeypatch.setattr(hub, "snapshot", boom)
    monkeypatch.setattr("app.market.live.BROADCAST_INTERVAL", 0.01)

    async def scenario():
        await hub.start()
        hub.clients.add(WS())
        hub.on_quote("X.NS", 10.0, 9.0)
        await asyncio.sleep(0.1)
        hub.on_quote("X.NS", 11.0, 9.0)
        await asyncio.sleep(0.1)
        await hub.stop()

    asyncio.run(scenario())
    assert len(sent) >= 2                                         # the loop kept going
    first = json.loads(sent[0])
    assert first["portfolio"] is None and "Portfolio not updated" in first["status"]["detail"]
    assert json.loads(sent[-1])["quotes"]["X.NS"]["ltp"] == 11.0


# ------------------------------------------------------------ optimiser options

def _returns(n=300, k=4, seed=5):
    rng = np.random.default_rng(seed)
    return rng.normal([0.0002, 0.0006, 0.0009, 0.0004][:k], [0.008, 0.012, 0.02, 0.01][:k], (n, k))


def test_optimiser_min_weight_and_targets():
    x = _returns()
    syms = ["A", "B", "C", "D"]
    r = optimizer.optimise(x, syms, 0.05, 0.6, min_weight=0.1, frontier_points=12)
    for p in ("max_sharpe", "min_variance"):
        w = r["portfolios"][p]["weights"]
        assert min(w.values()) >= 0.1 - 1e-6 and max(w.values()) <= 0.6 + 1e-6
    assert all("weights" in f and f["sharpe"] is not None for f in r["frontier"])
    # The tangency portfolio has the best Sharpe of every frontier point.
    best = max(f["sharpe"] for f in r["frontier"])
    assert r["portfolios"]["max_sharpe"]["sharpe"] >= best - 1e-4

    lo, hi = r["frontier"][0]["return"], r["frontier"][-1]["return"]
    mid = (lo + hi) / 2
    t = optimizer.optimise(x, syms, 0.05, 0.6, min_weight=0.1, target_return=mid)["portfolios"]["target"]
    assert t["return"] == pytest.approx(mid, abs=1e-4)
    vol_budget = r["portfolios"]["min_variance"]["volatility"] * 1.2
    tv = optimizer.optimise(x, syms, 0.05, 0.6, target_volatility=vol_budget)["portfolios"]["target"]
    assert tv["volatility"] <= vol_budget + 1e-4

    unreachable = optimizer.optimise(x, syms, 0.05, 0.6, target_return=5.0)
    assert "target" not in unreachable["portfolios"] and "outside" in unreachable["target_note"]
    # A floor above 1/n cannot be met; it is lowered to 1/n.
    assert optimizer.optimise(x, syms, 0.05, 1.0, min_weight=0.4)["min_weight"] == pytest.approx(0.25)


def test_optimiser_endpoint_options(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)
    held = [h["symbol"] for h in client.get("/api/metrics").json()["holdings"]]
    body = {"lookback_days": 252, "max_weight": 1, "risk_free_rate": 0.0, "min_weight": 0.1}
    r = client.post("/api/optimizer", json=body).json()
    assert r["risk_free_rate"] == 0.0 and r["min_weight"] == pytest.approx(0.1)
    # Excluding leaves fewer than two stocks here, which is refused clearly.
    gone = client.post("/api/optimizer", json={**body, "exclude": [held[0]]})
    assert gone.status_code == 400
