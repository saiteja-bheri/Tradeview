"""Zerodha through Kite Connect (read-only use).

Login: Kite sends you back to your app's redirect URL with a request_token.
The desktop engine runs on a different port every launch, so instead of
catching that redirect, the user pastes the address they land on; the engine
exchanges the request_token for the day's access token. Sessions end at about
06:00 every morning.

Reads: holdings (any plan, including the free Personal plan) and the day's
trades. Prices: only with the paid Kite Connect plan."""
from __future__ import annotations

import hashlib
import urllib.parse
from datetime import datetime
from pathlib import Path

from app.brokers import http
from app.brokers.base import BrokerError, Field, Holding, Source, UnavailableFeed
from app.ledger.upstox import NON_EQUITY_MARKERS, ParsedTrade
from app.ledger.zerodha import trade_key
from app.market import symbols

API = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login"


def request_token_from(value: str) -> str:
    """Accepts the full redirect address or just the request_token."""
    value = value.strip()
    if "request_token=" in value:
        query = urllib.parse.urlsplit(value).query or value.split("?", 1)[-1]
        token = urllib.parse.parse_qs(query).get("request_token", [""])[0]
    else:
        token = value
    if not token or any(c.isspace() or c in "/?&=" for c in token):
        raise BrokerError("Paste the address Kite sent you to after login (it contains request_token=…)",
                          status=400)
    return token


class ZerodhaSource(Source):
    id = "zerodha"
    label = "Zerodha"
    fields = (
        Field("api_key", "API key", secret=False, help="From developers.kite.trade > your app."),
        Field("api_secret", "API secret", help="Shown once when you create the app."),
    )
    capabilities = frozenset({"csv", "holdings", "trades", "live"})
    login = "redirect"
    notes = ("Import full history with IMPORT CSV (Console > Reports > Tradebook). SYNC adds today's "
             "trades and checks the ledger against your Zerodha holdings.")
    live_note = "Real-time, streaming. Needs the paid Kite Connect plan; the free Personal plan has no prices."

    def _headers(self) -> dict[str, str]:
        token = self.session_token()
        if not token:
            raise BrokerError("No Zerodha session today. Click LOG IN under Zerodha first.", status=401)
        return {"X-Kite-Version": "3", "Authorization": f"token {self.value('api_key')}:{token}"}

    def _get(self, path: str) -> list | dict:
        try:
            body = http.call("GET", API + path, self._headers())
        except BrokerError as exc:
            if exc.status in (401, 403):
                self.end_session()
                raise BrokerError("Zerodha ended the session. Log in again.", status=401) from exc
            raise
        return body.get("data") or []

    def login_url(self) -> str | None:
        key = self.value("api_key")
        if not key:
            raise BrokerError("Save your Zerodha API key first", status=400)
        return f"{LOGIN}?{urllib.parse.urlencode({'v': 3, 'api_key': key})}"

    def start_session(self, value: str | None) -> None:
        key, secret = self.value("api_key"), self.value("api_secret")
        if not (key and secret):
            raise BrokerError("Save your Zerodha API key and secret first", status=400)
        request_token = request_token_from(value or "")
        checksum = hashlib.sha256(f"{key}{request_token}{secret}".encode()).hexdigest()
        body = http.call("POST", f"{API}/session/token", {"X-Kite-Version": "3"},
                         form={"api_key": key, "request_token": request_token, "checksum": checksum})
        access = (body.get("data") or {}).get("access_token")
        if not access:
            raise BrokerError("Kite did not return an access token; try logging in again")
        self._store_session(access)

    def fetch_holdings(self) -> list[Holding]:
        out = []
        for h in self._get("/portfolio/holdings"):
            # T1 shares are bought but not yet settled; the ledger already counts them.
            qty = float(h.get("quantity") or 0) + float(h.get("t1_quantity") or 0)
            if qty <= 0:
                continue
            out.append(Holding(symbol=symbols.to_yahoo(h["tradingsymbol"], h.get("exchange", "NSE")),
                               isin=(h.get("isin") or "").upper(), name="",
                               quantity=qty, avg_price=float(h.get("average_price") or 0)))
        return out

    def fetch_trades(self) -> list[ParsedTrade]:
        out = []
        for t in self._get("/trades"):
            exchange = (t.get("exchange") or "").upper()
            if exchange not in ("NSE", "BSE"):
                continue
            if any(m in str(t.get("segment", "")).upper() for m in NON_EQUITY_MARKERS):
                continue
            side = "BUY" if str(t.get("transaction_type")).upper() == "BUY" else "SELL"
            stamp = t.get("fill_timestamp") or t.get("exchange_timestamp") or t.get("order_timestamp")
            traded_at = datetime.fromisoformat(str(stamp)) if stamp else datetime.now()
            out.append(ParsedTrade(
                trade_id=trade_key(exchange, str(t["trade_id"])),
                symbol=symbols.to_yahoo(t["tradingsymbol"], exchange), name="", exchange=exchange,
                scrip_code=symbols.clean_trading_symbol(t["tradingsymbol"]), side=side,
                quantity=float(t["quantity"]), price=float(t["average_price"]),
                traded_at=traded_at.replace(tzinfo=None), broker=self.id,
            ))
        return out

    def make_feed(self, cache_dir: Path):
        token = self.session_token()
        if not (self.value("api_key") and token):
            return UnavailableFeed(self.id, "Log in to Zerodha under CONNECT to stream its prices.")
        from app.market.feeds.zerodha import ZerodhaFeed

        return ZerodhaFeed(self.value("api_key") or "", token, cache_dir)
