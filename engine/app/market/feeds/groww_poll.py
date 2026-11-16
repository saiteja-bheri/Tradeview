"""Groww last-traded prices, polled (read-only).

Groww's API is reached through its official `growwapi` SDK. I found no
documented streaming feed for it, so this polls the LTP call for held symbols
in batches. The LTP call carries no previous close, so day P&L stays blank on
this source while value and unrealized P&L update."""
from __future__ import annotations

import asyncio
from typing import Callable

from app.market import symbols

BATCH = 50


def groww_key(symbol: str) -> str | None:
    base, exchange = symbols.split(symbol)
    return f"{exchange}_{base}" if exchange else None


class GrowwPollFeed:
    name = "groww"
    retry_seconds = 30.0

    def __init__(self, client_factory: Callable[[], object], interval: float = 5.0):
        self._client_factory = client_factory
        self.interval = interval

    def _fetch(self, client, keys: list[str]) -> dict[str, float]:
        segment = getattr(client, "SEGMENT_CASH", "CASH")
        prices: dict[str, float] = {}
        for i in range(0, len(keys), BATCH):
            reply = client.get_ltp(segment=segment, exchange_trading_symbols=tuple(keys[i:i + BATCH]))
            for key, value in (reply or {}).items():
                try:
                    prices[key] = float(value)
                except (TypeError, ValueError):
                    continue
        return prices

    async def run(self, hub) -> None:
        client = await asyncio.to_thread(self._client_factory)
        while True:
            held = await asyncio.to_thread(hub.held_symbols)
            keys = {groww_key(s): s for s in held if groww_key(s)}
            if keys:
                prices = await asyncio.to_thread(self._fetch, client, list(keys))
                for key, ltp in prices.items():
                    if key in keys:
                        hub.on_quote(keys[key], ltp, None)
                missing = [s for k, s in keys.items() if k not in prices]
                hub.set_status("live", f"No Groww price for {', '.join(missing)}" if missing else "")
            else:
                hub.set_status("live", "No holdings to price")
            await asyncio.sleep(self.interval)
