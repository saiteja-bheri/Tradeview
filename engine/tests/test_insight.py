import pytest
from fastapi.testclient import TestClient

from app.ai import memo
from app.ai.gemini import InsightError
from app.main import create_app
from app.market import history
from app.secrets import MemoryStore
from tests.conftest import fake_fetch

KEY = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE12345"

DATA = {
    "as_of": "2026-11-13", "observations": 252,
    "params": {"benchmark": "^NSEI", "confidence": 0.95, "horizon_days": 1},
    "portfolio_value": 20000.0, "net_delta": 20000.0, "unrealized_pnl": -5000.0,
    "metrics": {"var": 450.0, "var_pct": 0.0225, "beta": 0.8643, "jensens_alpha_annualized": -0.1188,
                "sharpe": -0.877, "sortino": -1.2099, "max_drawdown": -0.3216, "volatility_annualized": 0.2159},
    "holdings": [
        {"symbol": "RELIANCE.NS", "weight": 0.4, "beta": 0.9685, "component_var": 112.5,
         "value": 8000.0, "unrealized_pnl": 500.0},
        {"symbol": "TCS.NS", "weight": 0.6, "beta": 0.7949, "component_var": 337.5,
         "value": 12000.0, "unrealized_pnl": -5500.0},
        {"symbol": "NOPRICE.NS", "weight": None, "beta": None, "component_var": None,
         "value": None, "unrealized_pnl": None},
    ],
}


def test_payload_is_rounded_and_contains_no_quantities_or_costs():
    p = memo.build_payload(DATA)
    assert p["benchmark"] == "NIFTY 50" and p["var_confidence_pct"] == 95.0
    assert p["portfolio"]["value_at_risk_inr"] == 450 and p["portfolio"]["value_at_risk_pct_of_value"] == 2.25
    assert p["portfolio"]["max_drawdown_pct"] == -32.16 and p["portfolio"]["beta"] == 0.86
    assert p["portfolio"]["unrealized_return_pct"] == -20.0           # -5000 on a 25000 cost
    tcs, rel = p["holdings"]                                           # sorted by weight
    assert tcs == {"symbol": "TCS", "weight_pct": 60.0, "beta": 0.79,
                   "share_of_var_pct": 75.0, "unrealized_return_pct": -31.43}
    assert rel["share_of_var_pct"] == 25.0 and len(p["holdings"]) == 2  # unpriced holding dropped
    flat = str(p)
    assert "quantity" not in flat and "avg_cost" not in flat and "trade" not in flat


def test_number_check_accepts_supplied_figures_and_flags_invented_ones():
    p = memo.build_payload(DATA)
    ok = ("RISK POSTURE\nOne-day 95% VaR is INR 450 (2.25% of value). Beta 0.86 versus NIFTY 50. "
          "TCS is 60% of the book and 75.0% of VaR; drawdown reached -32.16%, about 32%. "
          "1. Two of 2 holdings carry the risk.")
    assert memo.unverified_numbers(ok, p) == []
    bad = "VaR of 450 implies a 10-day VaR near 1,423 and a hedge ratio of 0.74."
    assert memo.unverified_numbers(bad, p) == ["1,423", "0.74"]


@pytest.fixture
def insight(tmp_path, monkeypatch, upstox_csv):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    calls = []

    def generator(api_key, model, system, payload):
        calls.append({"api_key": api_key, "model": model, "system": system, "payload": payload})
        if api_key.endswith("BAD"):
            raise InsightError("Gemini rejected the API key. Check it and save it again.", 401)
        var = payload["portfolio"]["value_at_risk_inr"]
        return f"RISK POSTURE\nVaR is {var:,.0f}.\nHEDGING CONSIDERATIONS\nA hedge ratio of 0.7312 could apply."

    app = create_app(db_url=f"sqlite:///{(tmp_path / 'i.sqlite3').as_posix()}", token="",
                     gemini_store=MemoryStore(), memo_generator=generator)
    with TestClient(app) as client:
        client.post("/api/ledger/import", files={"file": ("t.csv", upstox_csv, "text/csv")})
        yield client, calls


def test_memo_flow_sends_only_the_risk_payload(insight):
    client, calls = insight
    assert client.post("/api/insight/memo").status_code == 409            # no key yet
    assert client.put("/api/insight/key", json={"key": KEY}).json() == {
        "configured": True, "source": "memory", "model": "gemini-3.8-flash",
        "frequency": "hourly", "last_at": None, "next_at": None}
    assert client.get("/api/insight/preview").status_code == 409          # no prices yet
    client.get("/api/metrics")                                            # loads (fake) prices

    preview = client.get("/api/insight/preview").json()
    res = client.post("/api/insight/memo")
    assert res.status_code == 200 and KEY not in res.text
    body = res.json()
    assert calls[-1]["payload"] == preview == body["payload"]             # what you preview is what is sent
    assert "Do not calculate" in calls[-1]["system"]
    assert set(preview) == {"as_of", "benchmark", "var_confidence_pct", "var_horizon_days",
                            "lookback_trading_days", "portfolio", "holdings"}
    assert body["unverified_numbers"] == ["0.7312"]                       # the invented figure is flagged

    history_rows = client.get("/api/insight/memos").json()
    assert len(history_rows) == 1 and history_rows[0]["text"] == body["text"]
    assert body["cached"] is False and body["next_at"] is not None


def test_memo_is_generated_at_most_once_per_window(insight):
    from datetime import datetime, timedelta

    from app.db.models import Memo

    client, calls = insight
    client.put("/api/insight/key", json={"key": KEY})
    client.get("/api/metrics")
    first = client.post("/api/insight/memo").json()
    again = client.post("/api/insight/memo").json()
    assert len(calls) == 1                                                # Gemini called once
    assert again["cached"] is True and again["id"] == first["id"]
    state = client.get("/api/insight").json()
    assert state["frequency"] == "hourly" and state["next_at"] == again["next_at"]

    client.put("/api/settings", json={"insight_frequency": "daily"})
    with client.app.state.sessionmaker() as s:                            # two hours later
        m = s.get(Memo, first["id"])
        m.created_at = datetime.now() - timedelta(hours=2)
        s.commit()
    assert client.post("/api/insight/memo").json()["cached"] is True      # daily: still waiting
    client.put("/api/settings", json={"insight_frequency": "hourly"})
    assert client.post("/api/insight/memo").json()["cached"] is False     # hourly: due again
    assert len(calls) == 2
    assert client.put("/api/settings", json={"insight_frequency": "weekly"}).status_code == 400


def test_bad_key_is_reported_and_nothing_is_stored(insight):
    client, _ = insight
    client.get("/api/metrics")
    client.put("/api/insight/key", json={"key": KEY[:-3] + "BAD"})
    res = client.post("/api/insight/memo")
    assert res.status_code == 401 and "rejected" in res.json()["detail"]
    assert client.get("/api/insight/memos").json() == []
    assert client.delete("/api/insight/key").json()["configured"] is False
