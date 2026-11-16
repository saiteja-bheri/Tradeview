"""News feed and events: cached locally, only for held/watched/starred stocks. No network."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.db.models import Instrument
from app.main import create_app
from app.market import history
from tests.test_tracking import DAYS, market

CALLS: list[tuple[str, str]] = []


def fake_news(symbol):
    CALLS.append(("news", symbol))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    shared = {"id": "story-1", "title": "Indian IT stocks rally on strong guidance", "summary": "IT services firms rose.",
              "publisher": "Wire", "url": "https://example.com/it-rally", "published_at": now - timedelta(hours=1)}
    own = {"id": f"{symbol}-2", "title": f"{symbol} announces buyback", "summary": "", "publisher": "Desk",
           "url": "https://example.com/b", "published_at": now - timedelta(hours=3)}
    old = {"id": f"{symbol}-old", "title": "Ancient news", "summary": "", "publisher": "Desk", "url": "",
           "published_at": now - timedelta(days=90)}
    return [shared, own, old] if symbol in ("INFY.NS", "TCS.NS") else [own]


GOOGLE_RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Infosys wins large deal - The Hindu BusinessLine</title><link>https://news.google.com/a1</link>
<guid>g1</guid><pubDate>{when}</pubDate><description>&lt;a href="x"&gt;Infosys wins&lt;/a&gt;</description>
<source url="https://www.thehindubusinessline.com">The Hindu BusinessLine</source></item>
<item><title>Indian IT stocks rally on strong guidance - Reuters</title><link>https://news.google.com/a2</link>
<guid>g2</guid><pubDate>{when}</pubDate><source url="https://reuters.com">Reuters</source></item>
</channel></rss>"""

WIRE_RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title><![CDATA[Tata Consultancy Services shares jump after results]]></title>
<link>https://economictimes.indiatimes.com/tcs</link><guid>w1</guid><pubDate>{when}</pubDate>
<description><![CDATA[<p>TCS beat estimates.</p>]]></description></item>
<item><title>Sensex ends flat as oil rises</title><link>https://economictimes.indiatimes.com/mkt</link>
<guid>w2</guid><pubDate>{when}</pubDate><description>Markets were quiet.</description></item>
<item><title>Bankers ITCH for rate cuts</title><link>https://economictimes.indiatimes.com/x</link>
<guid>w3</guid><pubDate>{when}</pubDate><description>No company here.</description></item>
</channel></rss>"""


def fake_rss(url):
    CALLS.append(("rss", url))
    when = format_datetime(datetime.now(timezone.utc) - timedelta(hours=2)).encode()
    if "news.google.com" in url:
        return GOOGLE_RSS.replace(b"{when}", when) if "Infosys" in unquote(url) else b"<rss><channel/></rss>"
    if "economictimes" in url:
        return WIRE_RSS.replace(b"{when}", when)
    if "cnbc.com" in url:                      # a US wire: its general stories are not Nifty market news
        return (b'<rss><channel><item><title>Actor cast in spy film</title><guid>c1</guid><pubDate>' + when +
                b'</pubDate></item><item><title>Infosys ADRs climb in New York</title><guid>c2</guid><pubDate>' +
                when + b'</pubDate></item></channel></rss>')
    return b"<rss><channel/></rss>"


def fake_events(symbol):
    CALLS.append(("events", symbol))
    soon = (date.today() + timedelta(days=10)).isoformat()
    return {"earnings": soon, "earnings_eps_estimate": 18.5, "ex_dividend": None, "dividend_paid": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    CALLS.clear()
    monkeypatch.setattr(history, "fetch", market)
    app = create_app(db_url=f"sqlite:///{(tmp_path / 'n.sqlite3').as_posix()}", token="")
    app.state.news_fetcher, app.state.event_fetcher, app.state.rss_get = fake_news, fake_events, fake_rss
    with TestClient(app) as c:
        yield c


def buy(client, symbol, when=None):
    client.post("/api/ledger/trades", json={"symbol": symbol, "side": "BUY", "quantity": 1, "price": 100,
                                           "traded_at": f"{when or DAYS[-50]}T10:00:00"})


def test_feed_covers_holdings_watchlist_and_market_only(client):
    buy(client, "INFY.NS")
    buy(client, "TCS.NS")
    client.put("/api/watchlist/AAPL", json={"watched": True})
    client.post("/api/watchlist/MSFT/view", json={})                     # history only: no news for it
    r = client.get("/api/news").json()
    covered = {c["symbol"]: c["why"] for c in r["covered"]}
    assert covered == {"INFY.NS": "held", "TCS.NS": "held", "AAPL": "watched", "^NSEI": "market"}
    assert ("news", "MSFT") not in CALLS
    shared = next(i for i in r["items"] if i["id"] == "story-1")
    assert sorted(shared["symbols"]) == ["INFY.NS", "TCS.NS"]              # one story, shown once
    assert not any(i["title"] == "Ancient news" for i in r["items"])       # older than 30 days dropped
    assert r["items"] == sorted(r["items"], key=lambda i: i["published_at"], reverse=True)
    earnings = [e for e in r["events"] if e["kind"] == "earnings"]
    assert {e["symbol"] for e in earnings} == {"INFY.NS", "TCS.NS", "AAPL", "^NSEI"}
    assert "EPS estimate 18.50" in earnings[0]["text"]


def test_feed_is_served_from_the_cache_until_stale(client):
    buy(client, "INFY.NS")
    client.get("/api/news")
    first = len(CALLS)
    again = client.get("/api/news").json()
    assert len(CALLS) == first and again["downloaded_news"] == 0          # within 30 minutes: local
    assert again["items"]
    client.get("/api/news", params={"force": "true"})
    assert len(CALLS) > first


def test_scopes_and_app_events(client):
    buy(client, "INFY.NS")
    client.put("/api/watchlist/AAPL", json={"watched": True})
    client.put("/api/bonds/GOI2027", json={"name": "GS 2027", "coupon_rate": 7, "frequency": 2,
                                           "maturity": (date.today() + timedelta(days=20)).isoformat()})
    client.post("/api/corporate-actions", json={"symbol": "INFY.NS", "kind": "split", "value": 2,
                                                "ex_date": (date.today() + timedelta(days=5)).isoformat()})
    port = client.get("/api/news", params={"scope": "portfolio"}).json()
    assert {c["symbol"] for c in port["covered"]} == {"INFY.NS", "^NSEI"}
    watch = client.get("/api/news", params={"scope": "watchlist"}).json()
    assert {c["symbol"] for c in watch["covered"]} == {"AAPL"}
    kinds = {(e["symbol"], e["kind"]) for e in port["events"]}
    assert ("INFY.NS", "split") in kinds and ("BOND:GOI2027", "maturity") in kinds


def name(client, symbol, text):
    with client.app.state.sessionmaker() as s:
        s.get(Instrument, symbol).name = text
        s.commit()


def test_google_news_and_wires_are_mapped_to_your_stocks(client):
    buy(client, "INFY.NS")
    buy(client, "TCS.NS")
    name(client, "INFY.NS", "Infosys Limited")
    name(client, "TCS.NS", "Tata Consultancy Services Ltd")
    r = client.get("/api/news").json()
    assert not r["errors"]
    by_title = {i["title"]: i for i in r["items"]}
    deal = by_title["Infosys wins large deal"]                         # outlet suffix stripped
    assert deal["publisher"] == "The Hindu BusinessLine" and deal["source"] == "google"
    assert deal["symbols"] == ["INFY.NS"] and deal["summary"] == ""
    # Same story from Yahoo and Google News is shown once, with both sources.
    rally = by_title["Indian IT stocks rally on strong guidance"]
    assert sorted(rally["sources"]) == ["google", "yahoo"]
    tcs = by_title["Tata Consultancy Services shares jump after results"]
    assert tcs["symbols"] == ["TCS.NS"] and tcs["publisher"] == "Economic Times"
    assert tcs["summary"] == "TCS beat estimates."                    # HTML stripped
    assert by_title["Sensex ends flat as oil rises"]["symbols"] == ["^NSEI"]     # market news
    assert by_title["Bankers ITCH for rate cuts"]["symbols"] == ["^NSEI"]        # no false ticker hit
    assert "Actor cast in spy film" not in by_title
    assert by_title["Infosys ADRs climb in New York"]["symbols"] == ["INFY.NS"]
    counts = {x["id"]: x["count"] for x in r["sources"]}
    assert counts["google"] == 2 and counts["et"] == 3
    # Wires are downloaded once each, not once per stock; Google once per stock.
    rss = [u for k, u in CALLS if k == "rss"]
    assert sum("economictimes" in u for u in rss) == 1
    assert sum("news.google.com" in u for u in rss) == 3                # INFY, TCS, the benchmark
    assert any("hl=en-IN" in u and "Nifty" in unquote(u) for u in rss)


def test_sources_can_be_switched_off_and_filtered(client):
    buy(client, "INFY.NS")
    name(client, "INFY.NS", "Infosys Limited")
    assert {x["id"] for x in client.get("/api/news/sources").json() if x["enabled"]} >= {"yahoo", "google", "et"}
    assert client.put("/api/news/sources", json={"enabled": ["nope"]}).status_code == 400
    on = client.put("/api/news/sources", json={"enabled": ["yahoo", "et"]}).json()
    assert [x["id"] for x in on if x["enabled"]] == ["yahoo", "et"]
    r = client.get("/api/news").json()
    assert not any("news.google.com" in u for k, u in CALLS if k == "rss")      # switched off: not downloaded
    assert {i["source"] for i in r["items"]} == {"yahoo", "et"}
    only = client.get("/api/news", params={"sources": "et"}).json()
    assert only["items"] and {i["source"] for i in only["items"]} == {"et"}
    assert client.get("/api/news", params={"sources": "google"}).json()["items"] == []  # not enabled


def test_a_failing_source_does_not_block_the_others(client, monkeypatch):
    buy(client, "INFY.NS")

    def broken(url):
        raise OSError("feed down")

    client.app.state.rss_get = broken
    r = client.get("/api/news").json()
    assert r["items"] and any("feed down" in e for e in r["errors"])    # Yahoo still shown
    again = client.get("/api/news").json()
    assert again["downloaded_news"] == 0                                # not retried until stale or REFRESH
