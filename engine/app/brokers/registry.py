"""All sources the app knows, and how the live price feed is chosen."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.brokers.base import Source
from app.brokers.groww import GrowwSource
from app.brokers.upstox import UpstoxSource
from app.brokers.zerodha import ZerodhaSource
from app.secrets import GROWW, ZERODHA, StoreFactory, TokenStore, credential_set

PRICE_SOURCES = ("auto", "upstox", "zerodha", "groww", "bse", "yahoo", "off")
PRICE_SOURCE_KEY = "price_source"


class YahooSource(Source):
    id = "yahoo"
    label = "Yahoo Finance"
    kind = "data"
    capabilities = frozenset({"live", "history"})
    notes = "Daily price history for every risk metric, and stock search. Always on; no account needed."
    live_note = "Delayed quotes, polled every 15 seconds."

    def make_feed(self, cache_dir: Path):
        from app.market.feeds.yahoo_poll import YahooPollFeed

        return YahooPollFeed()


class BseSource(Source):
    id = "bse"
    label = "BSE India"
    kind = "data"
    capabilities = frozenset({"live"})
    experimental = True
    notes = ("BSE has no official public API. Prices and corporate actions come from the community "
             "bse package (BseIndiaApi), which can stop working when BSE changes its website. "
             "NSE holdings are priced from their BSE listing. Use SYNC FROM BSE in the Corp Actions "
             "pane to pull dividends, bonus issues and splits from the exchange.")
    live_note = "Polled every 20 seconds. Experimental."

    def __init__(self, stores=None, isin_of=None):
        super().__init__(stores)
        self._isin_of = isin_of

    def make_feed(self, cache_dir: Path):
        from app.market.feeds.bse_poll import BsePollFeed

        return BsePollFeed(cache_dir, isin_of=self._isin_of)


def build_sources(factory: StoreFactory, upstox_store: TokenStore, isin_of=None) -> dict[str, Source]:
    return {
        "upstox": UpstoxSource({"token": upstox_store}),
        "zerodha": ZerodhaSource(credential_set(ZERODHA, factory)),
        "groww": GrowwSource(credential_set(GROWW, factory)),
        "bse": BseSource(isin_of=isin_of),
        "yahoo": YahooSource(),
    }


@dataclass
class FeedContext:
    sources: dict[str, Source]
    preference: str          # one of PRICE_SOURCES
    cache_dir: Path


def choose_feed(ctx: FeedContext, env_choice: str = "auto"):
    """QT_FEED (env_choice) wins over the saved preference. `auto` keeps the
    original behaviour: Upstox when its token is saved, otherwise Yahoo."""
    choice = env_choice if env_choice not in ("", "auto") else ctx.preference
    if choice == "off":
        return None
    if choice == "auto" or choice not in ctx.sources:
        choice = "upstox" if ctx.sources["upstox"].configured() else "yahoo"
    return ctx.sources[choice].make_feed(ctx.cache_dir)
