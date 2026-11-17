"""Upstox Market Data Feed V3 adapter (streaming, read-only).

Talks to exactly two Upstox endpoints, both with GET: the feed authorize call
and the public instrument list. It never touches trading, portfolio or funds
endpoints. The intended credential is an Upstox Analytics Token: read-only,
valid for a year, and unable to place or modify anything by design. A daily
OAuth access token also works."""
from __future__ import annotations

import asyncio
import gzip
import json
import urllib.error
import urllib.request
import uuid
from datetime import date
from pathlib import Path

from app.market.feeds.upstox_proto import decode_feed_response

AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz"
SEGMENTS = {"NS": ("NSE", "NSE_EQ"), "BO": ("BSE", "BSE_EQ")}


# Upstox's API sits behind Cloudflare, which refuses Python's default
# "Python-urllib" signature with error 1010 before Upstox sees the token.
USER_AGENT = "QuantTerminal/0.5 (read-only analytics)"


class FeedAuthError(RuntimeError):
    retry_seconds = 60.0


def _get(url: str, headers: dict[str, str] | None = None, timeout: float = 30) -> bytes:
    """The only way this module talks to Upstox: a plain GET."""
    headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as res:
        return res.read()


def build_instrument_map(rows: list[dict], segment: str) -> dict[str, str]:
    """{TRADING_SYMBOL or exchange token: instrument_key} for one cash segment."""
    out: dict[str, str] = {}
    for row in rows:
        if row.get("segment") != segment or not row.get("instrument_key"):
            continue
        for field in ("exchange_token", "trading_symbol"):  # trading symbol wins on a clash
            if row.get(field):
                out[str(row[field]).upper()] = row["instrument_key"]
    return out


def instrument_key(symbol: str, maps: dict[str, dict[str, str]]) -> str | None:
    """RELIANCE.NS -> NSE_EQ|INE002A01018 ; 500325.BO -> BSE_EQ|..."""
    base, _, suffix = symbol.rpartition(".")
    if suffix not in SEGMENTS:
        return None
    return maps.get(SEGMENTS[suffix][1], {}).get(base.upper())


class UpstoxFeed:
    name = "upstox"
    retry_seconds = 10.0

    def __init__(self, access_token: str, cache_dir: Path, resubscribe_seconds: float = 15.0):
        self._token = access_token
        self._cache = Path(cache_dir) / "upstox_instruments.json"
        self._resubscribe = resubscribe_seconds

    def _instrument_maps(self) -> dict[str, dict[str, str]]:
        today = date.today().isoformat()
        try:
            cached = json.loads(self._cache.read_text())
            if cached.get("date") == today:
                return cached["maps"]
        except (OSError, ValueError, KeyError):
            pass
        maps: dict[str, dict[str, str]] = {}
        for exchange, segment in SEGMENTS.values():
            raw = _get(INSTRUMENTS_URL.format(exchange=exchange), timeout=60)
            rows = json.loads(gzip.decompress(raw))
            maps[segment] = build_instrument_map(rows, segment)
        try:
            self._cache.write_text(json.dumps({"date": today, "maps": maps}))
        except OSError:
            pass
        return maps

    def _authorize(self) -> str:
        if not self._token:
            raise FeedAuthError("No Upstox token set. Add your Analytics Token under Settings → Connections → Upstox.")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        try:
            body = json.loads(_get(AUTHORIZE_URL, headers, timeout=20))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(2000).decode("utf-8", "replace").lower()
            except Exception:
                detail = ""
            if exc.code == 403 and ("cloudflare" in detail or "error 1010" in detail):
                raise FeedAuthError(
                    "Upstox's firewall (Cloudflare) refused the connection before checking the "
                    "token. This is not a token problem; try again later or switch LIVE PRICES "
                    "FROM to Yahoo."
                ) from exc
            if exc.code in (401, 403):
                raise FeedAuthError(
                    "Upstox rejected the token. Generate a new Analytics Token in the "
                    "Upstox Developer Apps page and save it under Settings → Connections → Upstox."
                ) from exc
            if exc.code == 429:
                raise FeedAuthError("Upstox rate limit reached; retrying in a minute") from exc
            raise RuntimeError(f"Upstox feed authorize failed (HTTP {exc.code})") from exc
        url = (body.get("data") or {}).get("authorized_redirect_uri")
        if not url:
            raise RuntimeError("Upstox feed authorize returned no WebSocket address")
        return url

    async def run(self, hub) -> None:
        import websockets

        # The authorized address is single-use, so every (re)connect asks for a new one.
        url = await asyncio.to_thread(self._authorize)
        maps = await asyncio.to_thread(self._instrument_maps)
        by_key: dict[str, str] = {}

        async with websockets.connect(url, max_size=None, user_agent_header=USER_AGENT) as ws:
            async def keep_subscribed() -> None:
                while True:
                    symbols = await asyncio.to_thread(hub.held_symbols)
                    unmapped, new_keys = [], []
                    for symbol in symbols:
                        key = instrument_key(symbol, maps)
                        if key is None:
                            unmapped.append(symbol)
                        elif key not in by_key:
                            by_key[key] = symbol
                            new_keys.append(key)
                    if new_keys:
                        request = {"guid": uuid.uuid4().hex, "method": "sub",
                                   "data": {"mode": "ltpc", "instrumentKeys": new_keys}}
                        await ws.send(json.dumps(request).encode("utf-8"))  # must be a binary frame
                    hub.set_status(
                        "live", f"No Upstox instrument for {', '.join(unmapped)}" if unmapped else ""
                    )
                    await asyncio.sleep(self._resubscribe)

            subscriber = asyncio.create_task(keep_subscribed())
            try:
                async for message in ws:
                    if isinstance(message, str):
                        continue
                    for key, q in decode_feed_response(message).items():
                        symbol = by_key.get(key)
                        if symbol:
                            hub.on_quote(symbol, q["ltp"], q["cp"], q["ltt"] / 1000 if q["ltt"] else None)
                    if subscriber.done():
                        subscriber.result()  # surface a subscribe failure
            finally:
                subscriber.cancel()
