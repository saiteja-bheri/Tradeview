"""Upstox: trade-book CSV import and the streaming price feed.

The credential is an Upstox Analytics Token, which only reaches market data.
That is deliberate: it cannot read or change anything in the account, so
Upstox offers no holdings sync here. Import the trade book instead."""
from __future__ import annotations

from pathlib import Path

from app.brokers.base import Field, Source


class UpstoxSource(Source):
    id = "upstox"
    label = "Upstox"
    fields = (Field("token", "Analytics token",
                    help="Upstox Developer Apps > Analytics tab. Read-only, valid for one year."),)
    capabilities = frozenset({"csv", "live"})
    notes = ("Import trades with IMPORT CSV (Upstox trade book). The Analytics Token streams "
             "real-time prices and can't see or change your account.")
    live_note = "Real-time, streaming."

    def make_feed(self, cache_dir: Path):
        from app.market.feeds.upstox import UpstoxFeed

        return UpstoxFeed(self.value("token") or "", cache_dir)
