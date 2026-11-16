"""Zerodha Kite Connect streaming quotes (read-only).

Live data needs the paid Kite Connect plan; the free Personal plan has no
market data, and Kite then refuses the WebSocket. The adapter talks to two
things only: the instrument list (GET) and the quote WebSocket, on which it
only ever sends 'subscribe' and 'mode' messages. Ticks are decoded here from
Kite's binary format, so the kiteconnect SDK is not needed."""
from __future__ import annotations

import asyncio
import csv
import io
import json
from datetime import date
from pathlib import Path

from app.brokers import http
from app.brokers.base import BrokerError, FeedUnavailable
from app.market import symbols

API = "https://api.kite.trade"
WS = "wss://ws.kite.trade"
EXCHANGES = ("NSE", "BSE")


class ZerodhaAuthError(FeedUnavailable):
    retry_seconds = 120.0


def headers(api_key: str, access_token: str) -> dict[str, str]:
    return {"X-Kite-Version": "3", "Authorization": f"token {api_key}:{access_token}"}


def build_token_map(csv_text: str, exchange: str) -> dict[str, int]:
    """{TRADINGSYMBOL or exchange token: instrument_token} for one exchange's equities."""
    out: dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("exchange") != exchange or row.get("instrument_type") != "EQ":
            continue
        token = int(row["instrument_token"])
        if row.get("exchange_token"):
            out.setdefault(row["exchange_token"].upper(), token)
        if row.get("tradingsymbol"):
            out[symbols.clean_trading_symbol(row["tradingsymbol"])] = token  # symbol wins on a clash
    return out


def token_for(symbol: str, maps: dict[str, dict[str, int]]) -> int | None:
    base, exchange = symbols.split(symbol)
    return maps.get(exchange, {}).get(base) if exchange else None


def _int(buf: bytes, start: int) -> int:
    return int.from_bytes(buf[start:start + 4], "big", signed=True)


def parse_ticks(buf: bytes) -> list[dict]:
    """Kite binary frame -> [{token, ltp, close}]. A 1-byte frame is a heartbeat."""
    if len(buf) < 4:
        return []
    count, i, out = int.from_bytes(buf[:2], "big"), 2, []
    for _ in range(count):
        if i + 2 > len(buf):
            break
        size = int.from_bytes(buf[i:i + 2], "big")
        packet = buf[i + 2:i + 2 + size]
        i += 2 + size
        if len(packet) < 8:
            continue
        token = _int(packet, 0)
        segment = token & 0xFF
        divisor = 10_000_000.0 if segment == 3 else 10_000.0 if segment == 6 else 100.0
        close = None
        if size in (28, 32):          # index quote / full: close sits at bytes 20-24
            close = _int(packet, 20) / divisor
        elif size >= 44:              # equity quote / full: close sits at bytes 40-44
            close = _int(packet, 40) / divisor
        out.append({"token": token, "ltp": _int(packet, 4) / divisor, "close": close})
    return out


class ZerodhaFeed:
    name = "zerodha"
    retry_seconds = 15.0

    def __init__(self, api_key: str, access_token: str, cache_dir: Path, resubscribe_seconds: float = 15.0):
        self._key = api_key
        self._token = access_token
        self._cache = Path(cache_dir) / "zerodha_instruments.json"
        self._resubscribe = resubscribe_seconds

    def _maps(self) -> dict[str, dict[str, int]]:
        today = date.today().isoformat()
        try:
            cached = json.loads(self._cache.read_text())
            if cached.get("date") == today:
                return cached["maps"]
        except (OSError, ValueError, KeyError):
            pass
        maps = {}
        for exchange in EXCHANGES:
            try:
                raw = http.get_bytes(f"{API}/instruments/{exchange}", headers(self._key, self._token), timeout=60)
            except BrokerError as exc:
                if exc.status in (401, 403):
                    raise ZerodhaAuthError("Zerodha session expired. Log in again under CONNECT.") from exc
                raise
            maps[exchange] = build_token_map(raw.decode("utf-8", "replace"), exchange)
        try:
            self._cache.write_text(json.dumps({"date": today, "maps": maps}))
        except OSError:
            pass
        return maps

    async def run(self, hub) -> None:
        import websockets

        if not (self._key and self._token):
            raise ZerodhaAuthError("Log in to Zerodha under CONNECT to stream its prices.")
        maps = await asyncio.to_thread(self._maps)
        by_token: dict[int, str] = {}
        url = f"{WS}?api_key={self._key}&access_token={self._token}"
        try:
            ws_cm = websockets.connect(url, max_size=None)
            ws = await ws_cm.__aenter__()
        except Exception as exc:
            code = getattr(getattr(exc, "response", None), "status_code", None) or getattr(exc, "status_code", None)
            if code in (401, 403):
                raise ZerodhaAuthError(
                    "Kite refused the price stream. Live data needs the Kite Connect plan, "
                    "and the session must be from today."
                ) from exc
            raise
        try:
            async def keep_subscribed() -> None:
                while True:
                    held = await asyncio.to_thread(hub.held_symbols)
                    unmapped, fresh = [], []
                    for symbol in held:
                        token = token_for(symbol, maps)
                        if token is None:
                            unmapped.append(symbol)
                        elif token not in by_token:
                            by_token[token] = symbol
                            fresh.append(token)
                    if fresh:
                        await ws.send(json.dumps({"a": "subscribe", "v": fresh}))
                        await ws.send(json.dumps({"a": "mode", "v": ["quote", fresh]}))
                    hub.set_status("live", f"No Zerodha instrument for {', '.join(unmapped)}" if unmapped else "")
                    await asyncio.sleep(self._resubscribe)

            subscriber = asyncio.create_task(keep_subscribed())
            try:
                async for message in ws:
                    if isinstance(message, str):
                        continue  # text frames carry account notices, not prices
                    for tick in parse_ticks(message):
                        symbol = by_token.get(tick["token"])
                        if symbol:
                            hub.on_quote(symbol, tick["ltp"], tick["close"])
                    if subscriber.done():
                        subscriber.result()
            finally:
                subscriber.cancel()
        finally:
            await ws_cm.__aexit__(None, None, None)
