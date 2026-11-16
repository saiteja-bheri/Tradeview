import asyncio
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.market.feeds.upstox import build_instrument_map, instrument_key
from app.market.feeds.upstox_proto import decode_feed_response


# --- tiny protobuf encoder, so the decoder is tested against real wire bytes ---

def varint(n: int) -> bytes:
    out = b""
    while True:
        byte, n = n & 0x7F, n >> 7
        out += bytes([byte | (0x80 if n else 0)])
        if not n:
            return out


def field(number: int, wire: int, payload: bytes) -> bytes:
    return varint(number << 3 | wire) + payload


def blob(number: int, payload: bytes) -> bytes:
    return field(number, 2, varint(len(payload)) + payload)


def ltpc(ltp: float, cp: float, ltt: int = 1740729552723) -> bytes:
    return (field(1, 1, struct.pack("<d", ltp)) + field(2, 0, varint(ltt))
            + field(3, 0, varint(75)) + field(4, 1, struct.pack("<d", cp)))


def feed_entry(key: str, feed: bytes) -> bytes:
    return blob(2, blob(1, key.encode()) + blob(2, feed))


def test_decode_ltpc_feed():
    msg = (field(1, 0, varint(1))                                   # type = live_feed
           + feed_entry("NSE_EQ|INE002A01018", blob(1, ltpc(1336.9, 1320.5)))
           + feed_entry("NSE_EQ|INE467B01029", blob(1, ltpc(2410.1, 2400.0)))
           + field(3, 0, varint(1740729566039)))                    # currentTs
    out = decode_feed_response(msg)
    assert out["NSE_EQ|INE002A01018"] == {"ltp": 1336.9, "cp": 1320.5, "ltt": 1740729552723}
    assert out["NSE_EQ|INE467B01029"]["ltp"] == 2410.1


def test_decode_full_and_greeks_feeds_and_market_info():
    full = blob(2, blob(1, blob(1, ltpc(100.5, 99.0))))     # fullFeed.marketFF.ltpc
    index = blob(2, blob(2, blob(1, ltpc(24000.0, 23900.0))))  # fullFeed.indexFF.ltpc
    greeks = blob(3, blob(1, ltpc(12.25, 11.0)))            # firstLevelWithGreeks.ltpc
    msg = feed_entry("A", full) + feed_entry("B", index) + feed_entry("C", greeks)
    out = decode_feed_response(msg)
    assert (out["A"]["ltp"], out["B"]["ltp"], out["C"]["ltp"]) == (100.5, 24000.0, 12.25)
    # a market_info message carries no feeds
    assert decode_feed_response(field(1, 0, varint(2)) + blob(4, b"")) == {}


def test_instrument_key_lookup():
    rows = [
        {"segment": "NSE_EQ", "trading_symbol": "RELIANCE", "exchange_token": "2885",
         "instrument_key": "NSE_EQ|INE002A01018"},
        {"segment": "NSE_FO", "trading_symbol": "RELIANCE", "instrument_key": "NSE_FO|1"},
        {"segment": "BSE_EQ", "trading_symbol": "RELIANCE", "exchange_token": "500325",
         "instrument_key": "BSE_EQ|INE002A01018"},
    ]
    maps = {"NSE_EQ": build_instrument_map(rows, "NSE_EQ"), "BSE_EQ": build_instrument_map(rows, "BSE_EQ")}
    assert instrument_key("RELIANCE.NS", maps) == "NSE_EQ|INE002A01018"
    assert instrument_key("500325.BO", maps) == "BSE_EQ|INE002A01018"
    assert instrument_key("RELIANCE.BO", maps) == "BSE_EQ|INE002A01018"
    assert instrument_key("NOSUCH.NS", maps) is None and instrument_key("^NSEI", maps) is None


class FakeFeed:
    name = "fake"
    retry_seconds = 0.01

    async def run(self, hub):
        hub.on_quote("RELIANCE.NS", 1300.0, 1280.0)
        hub.set_status("live")
        await asyncio.Event().wait()


def make(tmp_path, **kw):
    return create_app(db_url=f"sqlite:///{(tmp_path / 'live.sqlite3').as_posix()}", **kw)


def test_ws_snapshot_marks_portfolio_to_market(tmp_path, upstox_csv):
    with TestClient(make(tmp_path, token="", feed=FakeFeed())) as client:
        client.post("/api/ledger/import", files={"file": ("t.csv", upstox_csv, "text/csv")})
        with client.websocket_connect("/ws/ticks") as ws:
            snap = ws.receive_json()
    assert snap["status"] == {"source": "fake", "state": "live", "detail": ""}
    quote = snap["quotes"]["RELIANCE.NS"]
    assert quote["ltp"] == 1300.0 and quote["change"] == 20.0
    assert quote["change_pct"] == pytest.approx(20 / 1280)
    port = snap["portfolio"]
    assert (port["held"], port["priced"]) == (2, 1)          # TCS has no quote yet
    rel = port["holdings"]["RELIANCE.NS"]                    # 6 shares, cost 1250
    assert rel == {"value": 7800.0, "unrealized_pnl": 300.0, "day_pnl": 120.0}
    assert port["day_pnl"] == 120.0


def test_ws_requires_token(tmp_path):
    with TestClient(make(tmp_path, token="secret", feed=FakeFeed())) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/ticks"):
                pass
        with client.websocket_connect("/ws/ticks?token=secret") as ws:
            assert ws.receive_json()["type"] == "snapshot"


def test_ws_without_feed_reports_off(client):
    with client.websocket_connect("/ws/ticks") as ws:
        assert ws.receive_json()["status"]["state"] == "off"


def test_feed_failure_becomes_status(tmp_path):
    class Broken(FakeFeed):
        async def run(self, hub):
            raise RuntimeError("token expired")

    with TestClient(make(tmp_path, token="", feed=Broken())) as client:
        with client.websocket_connect("/ws/ticks") as ws:
            assert ws.receive_json()["status"] == {"source": "fake", "state": "error",
                                                   "detail": "token expired"}


class NamedFeed(FakeFeed):
    def __init__(self, name):
        self.name = name

    async def run(self, hub):
        hub.set_status("live")
        await asyncio.Event().wait()


def test_saving_token_switches_feed_and_never_leaks_it(tmp_path):
    from app.secrets import MemoryStore

    store = MemoryStore()
    factory = lambda ctx: NamedFeed(  # noqa: E731
        "upstox" if ctx.sources["upstox"].configured() else "yahoo-delayed")
    secret = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.fake.fake"
    with TestClient(make(tmp_path, token="", token_store=store, feed_factory=factory)) as client:
        assert client.get("/api/upstox").json()["configured"] is False
        assert client.put("/api/upstox/token", json={"token": "short"}).status_code == 422
        assert client.put("/api/upstox/token", json={"token": "has a space " * 3}).status_code == 400

        saved = client.put("/api/upstox/token", json={"token": f"  {secret}\n"})
        assert saved.status_code == 200 and secret not in saved.text
        assert saved.json()["configured"] is True and store.get() == secret
        with client.websocket_connect("/ws/ticks") as ws:
            assert ws.receive_json()["status"]["source"] == "upstox"
        assert secret not in client.get("/api/upstox").text

        removed = client.delete("/api/upstox/token").json()
        assert removed["configured"] is False and store.get() is None
        with client.websocket_connect("/ws/ticks") as ws:
            assert ws.receive_json()["status"]["source"] == "yahoo-delayed"


def test_upstox_feed_without_token_fails_before_any_network_call(tmp_path, monkeypatch):
    from app.market.feeds import upstox

    def no_network(*a, **k):
        raise AssertionError("network must not be touched without a token")

    monkeypatch.setattr(upstox, "_get", no_network)
    with pytest.raises(upstox.FeedAuthError):
        asyncio.run(upstox.UpstoxFeed("", tmp_path).run(hub=None))


def test_upstox_module_is_get_only():
    """An Analytics Token can only call GET endpoints, and so can this module."""
    text = (Path(__file__).parents[1] / "app" / "market" / "feeds" / "upstox.py").read_text()
    assert text.count("urlopen(") == 1 and 'method="GET"' in text
    assert not [verb for verb in ('"POST"', '"PUT"', '"DELETE"', '"PATCH"', "data=") if verb in text]


def test_source_has_no_trading_endpoints():
    """Zero-execution guarantee: the engine never references Upstox order,
    funds or portfolio APIs, only the market data feed and instrument list."""
    banned = ("/order", "place_order", "/v2/portfolio", "/user/get-funds", "gtt")
    for path in (Path(__file__).parents[1] / "app").rglob("*.py"):
        text = path.read_text().lower()
        assert not [b for b in banned if b in text], path
