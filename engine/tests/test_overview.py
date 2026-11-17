"""Markets overview: index levels, world indices and the day's movers."""
import pytest

from app import config
from app.market import overview
from tests.conftest import fake_fetch


def fake_quotes(symbols):
    """Deterministic (last, prev_close) per symbol: change between -5% and +5%."""
    out = {}
    for s in symbols:
        step = (sum(map(ord, s)) % 11) - 5          # -5 .. +5
        out[s] = (100.0 + step, 100.0)
    return out


@pytest.fixture
def market(client, monkeypatch):
    overview._CACHE.clear()
    calls = []

    def counting(symbols):
        calls.append(list(symbols))
        return fake_quotes(symbols)

    client.app.state.price_fetcher = fake_fetch
    client.app.state.quote_fetcher = counting
    return client, calls


def upload(client, data):
    return client.post("/api/ledger/import", files={"file": ("tradebook.csv", data, "text/csv")})


def test_overview_returns_indexes_global_and_movers(market):
    client, _ = market
    data = client.get("/api/markets/overview", params={"universe": "nifty50", "window": 63}).json()
    assert data["online"] is True
    assert len(data["global"]) == len(config.GLOBAL_INDICES) == 12
    for row in data["global"] + data["indexes"]:
        last, prev = fake_quotes([row["symbol"]])[row["symbol"]]
        assert row["change_pct"] == pytest.approx(last / prev - 1)
    assert [i["symbol"] for i in data["indexes"]][:3] == ["^NSEI", "^BSESN", "^NSEBANK"]
    series = data["indexes"][0]["series"]
    assert 0 < len(series) <= 63 and series[0]["pct"] == 0
    gainers, losers = data["movers"]["gainers"], data["movers"]["losers"]
    assert len(gainers) == len(losers) == 5
    assert [g["change_pct"] for g in gainers] == sorted((g["change_pct"] for g in gainers), reverse=True)
    assert [x["change_pct"] for x in losers] == sorted(x["change_pct"] for x in losers)
    assert {m["symbol"] for m in gainers + losers} <= set(config.NIFTY50)


def test_nifty50_list_has_fifty_nse_symbols():
    assert len(config.NIFTY50) == len(set(config.NIFTY50)) == 50
    assert all(s.endswith(".NS") for s in config.NIFTY50)


def test_mine_universe_is_holdings_plus_watchlist(market, upstox_csv):
    client, _ = market
    upload(client, upstox_csv)
    assert client.put("/api/watchlist/INFY.NS", json={"starred": True}).status_code == 200
    movers = client.get("/api/markets/overview", params={"universe": "mine"}).json()["movers"]
    symbols = {m["symbol"] for m in movers["gainers"] + movers["losers"]}
    assert movers["universe"] == "mine"
    assert symbols and symbols <= {"RELIANCE.NS", "TCS.NS", "INFY.NS"}


def test_quotes_are_cached_for_five_minutes(market, monkeypatch):
    client, calls = market
    client.get("/api/markets/overview")
    first = len(calls)
    client.get("/api/markets/overview")
    assert len(calls) == first
    later = overview.time.monotonic() + 301
    monkeypatch.setattr(overview.time, "monotonic", lambda: later)
    client.get("/api/markets/overview")
    assert len(calls) > first


def test_offline_returns_online_false(market):
    client, _ = market

    def offline(symbols):
        raise OSError("no network")

    client.app.state.quote_fetcher = offline
    res = client.get("/api/markets/overview")
    assert res.status_code == 200
    data = res.json()
    assert data["online"] is False and data["global"] == [] and data["movers"]["gainers"] == []


def test_bad_universe_or_window_is_refused(market):
    client, _ = market
    assert client.get("/api/markets/overview", params={"universe": "everything"}).status_code == 422
    assert client.get("/api/markets/overview", params={"window": 7}).status_code == 422
