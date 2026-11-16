"""BSE India quotes, polled. EXPERIMENTAL.

Uses the community `bse` package through app.market.bse_india (BSE has no
official public API). Scrip codes come from BSE's own lookup, by ISIN when the
ledger knows it, and are cached. NSE holdings are priced from their BSE listing."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable

from app.market import symbols
from app.market.bse_india import BseClient


class BsePollFeed:
    name = "bse"
    retry_seconds = 60.0

    def __init__(self, cache_dir: Path, client: BseClient | None = None, interval: float = 20.0,
                 isin_of: Callable[[], dict[str, str]] | None = None):
        self._client = client or BseClient(cache_dir)
        self.interval = interval
        self._isin_of = isin_of or (lambda: {})

    def _poll(self, held: list[str]) -> tuple[dict[str, dict], list[str]]:
        isins = self._isin_of()
        quotes, missing = {}, []
        for symbol in held:
            if symbols.namespace(symbol) or not symbols.split(symbol)[1]:
                continue  # funds, commodities and bonds are not BSE equities
            try:
                code = self._client.code_for(symbol, isins.get(symbol, ""))
                q = self._client.quote(code) if code else {}
            except RuntimeError:
                raise  # package missing: surface it as the feed status
            except Exception:
                q = {}
            if q.get("ltp"):
                quotes[symbol] = q
            else:
                missing.append(symbol)
        return quotes, missing

    async def run(self, hub) -> None:
        try:
            while True:
                held = await asyncio.to_thread(hub.held_symbols)
                quotes, missing = await asyncio.to_thread(self._poll, held)
                for symbol, q in quotes.items():
                    hub.on_quote(symbol, q["ltp"], q.get("prev_close"))
                if quotes:
                    hub.set_status("live", f"No BSE price for {', '.join(missing)}" if missing else "")
                elif held:
                    hub.set_status("error", "BSE returned no prices (the unofficial source may have changed)")
                else:
                    hub.set_status("live", "No holdings to price")
                await asyncio.sleep(self.interval)
        finally:
            self._client.close()
