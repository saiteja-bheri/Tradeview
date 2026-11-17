"""Fallback feed: polls Yahoo Finance for delayed quotes. Used when no Upstox
access token is configured, so the live pipeline still works out of the box."""
from __future__ import annotations

import asyncio
import math


def fetch_quotes(symbols: list[str]) -> dict[str, tuple[float, float | None]]:
    import yfinance as yf

    out: dict[str, tuple[float, float | None]] = {}
    for symbol in symbols:
        try:
            info = yf.Ticker(symbol).fast_info
            last, prev = info.last_price, info.previous_close
            last = float(last) if last is not None else math.nan
            prev = float(prev) if prev is not None else math.nan
            if math.isfinite(last) and last > 0:      # Yahoo returns NaN for halted/unknown symbols
                out[symbol] = (last, prev if math.isfinite(prev) and prev > 0 else None)
        except Exception:
            continue  # one bad symbol must not stop the rest
    return out


class YahooPollFeed:
    name = "yahoo-delayed"
    retry_seconds = 30.0

    def __init__(self, interval: float = 15.0, fetcher=fetch_quotes):
        self.interval = interval
        self.fetcher = fetcher

    async def run(self, hub) -> None:
        while True:
            # Holdings plus the benchmark, so beta and alpha can be recomputed intraday.
            symbols = await asyncio.to_thread(getattr(hub, "tracked_symbols", hub.held_symbols))
            if symbols:
                quotes = await asyncio.to_thread(self.fetcher, symbols)
                for symbol, (last, prev) in quotes.items():
                    hub.on_quote(symbol, last, prev)
                missing = [s for s in symbols if s not in quotes]
                if quotes:
                    hub.set_status("live", f"No quote for {', '.join(missing)}" if missing else "")
                else:
                    hub.set_status("error", "Yahoo returned no quotes")
            else:
                hub.set_status("live", "No holdings to price")
            await asyncio.sleep(self.interval)
