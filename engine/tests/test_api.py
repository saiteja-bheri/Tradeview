import re

import pytest

from app.market import history
from tests.conftest import fake_fetch


def upload(client, data):
    return client.post("/api/ledger/import", files={"file": ("tradebook.csv", data, "text/csv")})


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_import_is_idempotent(client, upstox_csv):
    first = upload(client, upstox_csv).json()
    assert (first["imported"], first["duplicates"], len(first["skipped"])) == (3, 0, 1)
    second = upload(client, upstox_csv).json()
    assert (second["imported"], second["duplicates"]) == (0, 3)
    assert len(client.get("/api/ledger/trades").json()) == 3


def test_holdings_without_prices_still_lists_positions(client, upstox_csv):
    upload(client, upstox_csv)
    data = client.get("/api/portfolio/holdings").json()
    rel = next(h for h in data["holdings"] if h["symbol"] == "RELIANCE.NS")
    assert rel["quantity"] == 6 and rel["avg_cost"] == 1250.0 and rel["last"] is None
    assert data["realized_pnl"] == pytest.approx(4 * 50.0)


def test_metrics_end_to_end_and_recalculation(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)

    base = client.get("/api/metrics").json()
    m = base["metrics"]
    assert base["observations"] == 252 and base["warnings"] == []
    assert all(m[k] is not None for k in ("beta", "jensens_alpha_annualized", "sharpe",
                                          "sortino", "max_drawdown", "var"))
    assert 0.8 < m["beta"] < 1.6  # assets are built as 1.2x market plus noise
    assert sum(h["weight"] for h in base["holdings"]) == pytest.approx(1.0)
    assert sum(h["component_var"] for h in base["holdings"]) == pytest.approx(m["var"])

    # 99% VaR = 95% VaR * z99/z95
    v99 = client.get("/api/metrics", params={"confidence": 0.99}).json()["metrics"]["var"]
    assert v99 == pytest.approx(m["var"] * 2.3263479 / 1.6448536, rel=1e-6)

    # benchmark swap persists through settings and changes the params used
    assert client.put("/api/settings", json={"benchmark": "^BSESN"}).json()["benchmark"] == "^BSESN"
    assert client.get("/api/metrics").json()["params"]["benchmark"] == "^BSESN"
    assert client.put("/api/settings", json={"benchmark": "not a symbol!"}).status_code == 400
    assert client.get("/api/metrics", params={"confidence": 1.5}).status_code == 400


def test_manual_bonus_adjusts_position_and_blocks_double_entry(client, upstox_csv):
    upload(client, upstox_csv)
    body = {"symbol": "TCS.NS", "ex_date": "2025-06-01", "kind": "bonus", "value": 2.0}
    assert client.post("/api/corporate-actions", json=body).status_code == 201
    assert client.post("/api/corporate-actions", json={**body, "kind": "split"}).status_code == 409
    tcs = next(h for h in client.get("/api/portfolio/holdings").json()["holdings"]
               if h["symbol"] == "TCS.NS")
    assert tcs["quantity"] == 10 and tcs["avg_cost"] == 2000.0


def test_token_is_enforced(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app(db_url=f"sqlite:///{(tmp_path / 't.sqlite3').as_posix()}", token="secret")
    with TestClient(app) as c:
        assert c.get("/api/settings").status_code == 401
        assert c.get("/api/settings", headers={"x-qt-token": "secret"}).status_code == 200


def test_no_execution_surface(client):
    """Zero-execution guarantee: no route may look like order routing."""
    banned = re.compile(r"order|execut|place|buy|sell|webhook", re.I)
    paths = list(client.get("/openapi.json").json()["paths"])
    assert "/api/metrics" in paths
    assert not [p for p in paths if banned.search(p)]


def test_search_finds_stocks_by_name_and_ticker(client, upstox_csv, monkeypatch):
    from app.market import search

    calls = []

    def fake_lookup(query, limit):
        calls.append(query)
        return [
            {"symbol": "TATAMOTORS.NS", "longname": "Tata Motors Limited", "quoteType": "EQUITY"},
            {"symbol": "TATAMOTORS.BO", "shortname": "TATA MOTORS LTD", "quoteType": "EQUITY"},
            {"symbol": "TTM", "longname": "Tata Motors ADR", "quoteType": "EQUITY"},
            {"symbol": "TATAGOLD.NS", "longname": "Tata Gold ETF", "quoteType": "ETF"},
        ]

    search._CACHE.clear()
    monkeypatch.setattr(search, "yahoo_lookup", fake_lookup)
    upload(client, upstox_csv)

    data = client.get("/api/search", params={"q": "tata motors"}).json()
    assert data["online"] is True
    # Indian listings first, then international ones (the NYSE ADR); ETFs are classified.
    assert [r["symbol"] for r in data["results"]] == ["TATAMOTORS.NS", "TATAMOTORS.BO", "TTM", "TATAGOLD.NS"]
    assert (data["results"][2]["market"], data["results"][2]["currency"]) == ("US", "USD")
    assert (data["results"][0]["market"], data["results"][0]["exchange"]) == ("INDIA", "NSE")
    us_only = client.get("/api/search", params={"q": "tata motors", "market": "US"}).json()["results"]
    assert [r["symbol"] for r in us_only] == ["TTM"]
    assert data["results"][0] == {"symbol": "TATAMOTORS.NS", "name": "Tata Motors Limited",
                                  "exchange": "NSE", "held": False, "asset_class": "equity",
                                  "market": "INDIA", "currency": "INR"}
    assert data["results"][3]["asset_class"] == "gold"

    client.get("/api/search", params={"q": "Tata  Motors"})
    assert calls == ["tata motors"]  # repeated query is served from the cache

    assert client.get("/api/search", params={"q": "  "}).json()["results"] == []


def test_search_works_offline_from_the_ledger(client, upstox_csv, monkeypatch):
    from app.market import search

    def offline(query, limit):
        raise ConnectionError("no network")

    search._CACHE.clear()
    monkeypatch.setattr(search, "yahoo_lookup", offline)
    upload(client, upstox_csv)

    data = client.get("/api/search", params={"q": "relia"}).json()
    assert data["online"] is False
    assert data["results"][0]["symbol"] == "RELIANCE.NS" and data["results"][0]["held"] is True


def test_manual_trades_can_be_recorded_amended_and_removed(client, upstox_csv):
    upload(client, upstox_csv)
    body = {"symbol": "infy", "side": "BUY", "quantity": 20, "price": 1500.0,
            "traded_at": "2025-03-03T10:00:00", "name": "Infosys Limited"}
    made = client.post("/api/ledger/trades", json=body)
    assert made.status_code == 201
    trade = made.json()
    assert (trade["symbol"], trade["broker"], trade["name"]) == ("INFY.NS", "manual", "Infosys Limited")

    def holding(symbol):
        rows = client.get("/api/portfolio/holdings").json()["holdings"]
        return next((h for h in rows if h["symbol"] == symbol), None)

    assert holding("INFY.NS")["quantity"] == 20

    amended = client.put(f"/api/ledger/trades/{trade['id']}", json={**body, "quantity": 15, "price": 1400.0})
    assert amended.status_code == 200
    assert (holding("INFY.NS")["quantity"], holding("INFY.NS")["avg_cost"]) == (15, 1400.0)

    # an imported row can be corrected too
    rel_sale = next(t for t in client.get("/api/ledger/trades").json()
                    if t["symbol"] == "RELIANCE.NS" and t["side"] == "SELL")
    fix = {"symbol": "RELIANCE.NS", "side": "SELL", "quantity": 5, "price": 1300.0,
           "traded_at": rel_sale["traded_at"]}
    assert client.put(f"/api/ledger/trades/{rel_sale['id']}", json=fix).status_code == 200
    assert holding("RELIANCE.NS")["quantity"] == 5

    assert client.delete(f"/api/ledger/trades/{trade['id']}").status_code == 200
    assert holding("INFY.NS") is None
    assert client.delete(f"/api/ledger/trades/{trade['id']}").status_code == 404

    for bad in ({**body, "quantity": 0}, {**body, "price": -1}, {**body, "side": "SHORT"},
                {**body, "symbol": "NIFTY 23000 CE"}):
        assert client.post("/api/ledger/trades", json=bad).status_code in (400, 422)


def test_export_round_trips_and_applies_edits_made_in_the_file(client, upstox_csv, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app

    upload(client, upstox_csv)
    client.post("/api/ledger/trades", json={"symbol": "INFY.BO", "side": "BUY", "quantity": 20,
                                             "price": 1500.5, "traded_at": "2025-03-03T10:00:00"})
    res = client.get("/api/ledger/export")
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    text = res.text
    assert text.splitlines()[0].startswith("Date,Company,Amount,Exchange")
    assert len(text.splitlines()) == 5

    # importing the export into the same ledger changes nothing
    again = upload(client, text.encode()).json()
    assert (again["imported"], again["updated"], again["duplicates"]) == (0, 0, 4)

    # into an empty ledger it rebuilds the same positions, manual rows included
    app = create_app(db_url=f"sqlite:///{(tmp_path / 'copy.sqlite3').as_posix()}", token="")
    with TestClient(app) as other:
        assert upload(other, text.encode()).json()["imported"] == 4
        copy = {h["symbol"]: h["quantity"] for h in other.get("/api/portfolio/holdings").json()["holdings"]}
        assert {t["broker"] for t in other.get("/api/ledger/trades").json()} == {"upstox", "manual"}
    mine = {h["symbol"]: h["quantity"] for h in client.get("/api/portfolio/holdings").json()["holdings"]}
    assert copy == mine == {"RELIANCE.NS": 6, "TCS.NS": 5, "INFY.BO": 20}

    # a row edited in the file updates its ledger entry instead of adding a second one
    edited = text.replace(",20,1500.5,", ",25,1500.5,")
    assert edited != text
    result = upload(client, edited.encode()).json()
    assert (result["imported"], result["updated"], result["duplicates"]) == (0, 1, 3)
    assert len(client.get("/api/ledger/trades").json()) == 4
    infy = next(h for h in client.get("/api/portfolio/holdings").json()["holdings"] if h["symbol"] == "INFY.BO")
    assert infy["quantity"] == 25


def test_any_benchmark_can_be_chosen(client, upstox_csv, monkeypatch):
    from app.market import search

    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)

    saved = client.put("/api/settings", json={"benchmark": "^crsldx"}).json()
    assert (saved["benchmark"], saved["benchmark_name"]) == ("^CRSLDX", "NIFTY 500")
    data = client.get("/api/metrics").json()
    assert data["params"]["benchmark"] == "^CRSLDX" and data["metrics"]["beta"] is not None

    fund = {"benchmark": "0P0000YWL1.BO", "benchmark_name": "Parag Parikh Flexi Cap Dir Gr"}
    assert client.put("/api/settings", json=fund).json()["benchmark_name"] == fund["benchmark_name"]
    assert client.get("/api/metrics").json()["metrics"]["beta"] is not None
    # switching again without a name must not keep the fund's name
    assert client.put("/api/settings", json={"benchmark": "^NSEBANK"}).json()["benchmark_name"] == "NIFTY BANK"

    presets = client.get("/api/benchmarks").json()["results"]
    assert {"^NSEI", "^BSESN", "^CRSLDX", "^NSEBANK"} <= {p["symbol"] for p in presets}

    def fake_lookup(query, limit):
        return [
            {"symbol": "SPY", "longname": "SPDR S&P 500 ETF", "quoteType": "ETF", "exchange": "PCX"},
            {"symbol": "0P0000YWL1.BO", "longname": "Parag Parikh Flexi Cap Dir Gr",
             "quoteType": "MUTUALFUND", "exchange": "BSE"},
            {"symbol": "X=F", "longname": "Some future", "quoteType": "FUTURE", "exchange": "CME"},
        ]

    search._CACHE.clear()
    monkeypatch.setattr(search, "yahoo_lookup", fake_lookup)
    found = client.get("/api/benchmarks", params={"q": "flexi"}).json()["results"]
    assert [(r["symbol"], r["kind"]) for r in found] == [("0P0000YWL1.BO", "FUND"), ("SPY", "ETF")]


def test_covariance_horizon_and_lookback_options(client, upstox_csv, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    upload(client, upstox_csv)

    one = client.get("/api/metrics").json()["covariance"]
    assert one["horizon_days"] == 1 and one["observations"] == 252

    client.put("/api/settings", json={"cov_horizon_days": 10})
    ten = client.get("/api/metrics").json()["covariance"]
    assert ten["horizon_days"] == 10 and ten["observations"] == 243
    # ten-day variance is roughly ten times daily variance for near-independent returns
    assert 5 < ten["matrix"][0][0] / one["matrix"][0][0] < 20
    assert ten["annualized"][0][0] == pytest.approx(ten["matrix"][0][0] * 25.2)
    assert ten["correlation"][0][0] == pytest.approx(1.0)
    assert ten["correlation"][0][1] == pytest.approx(ten["correlation"][1][0])

    short = client.get("/api/metrics", params={"lookback_days": 63}).json()
    assert short["observations"] == 63
    # 63 days hold only ~6 independent 10-day periods: said, not hidden
    assert short["warnings"] == [w for w in short["warnings"] if "non-overlapping" in w] and short["warnings"]
    long = client.get("/api/metrics", params={"lookback_days": 1260}).json()
    assert long["observations"] == 299 and any("only 299" in w for w in long["warnings"])
    assert client.put("/api/settings", json={"cov_horizon_days": 0}).status_code == 400
    assert client.put("/api/settings", json={"lookback_days": 5000}).status_code == 400

    # Month-to-year horizons, on their own covariance window.
    assert client.put("/api/settings", json={"cov_horizon_days": 252}).status_code == 200
    assert client.put("/api/settings", json={"cov_horizon_days": 253}).status_code == 400
    client.put("/api/settings", json={"cov_horizon_days": 21, "lookback_days": 63, "cov_lookback_days": 252})
    month = client.get("/api/metrics").json()
    cov = month["covariance"]
    assert month["observations"] == 63                     # risk ratios keep their own lookback
    assert cov["window_days"] == 252 and cov["observations"] == 252 - 21 + 1
    assert cov["independent_periods"] == 12
    assert client.put("/api/settings", json={"cov_lookback_days": 30}).status_code == 400
    # A one-month risk lookback is offered in the UI, so it must produce metrics.
    client.put("/api/settings", json={"lookback_days": 21})
    assert client.get("/api/metrics").json()["metrics"]["sharpe"] is not None
