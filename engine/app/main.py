from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.ai import gemini
from app.api.assets import router as assets_router
from app.api.connections import router as connections_router
from app.api.news import router as news_router
from app.api.stress import router as stress_router
from app.api.watch import router as watch_router
from app.api.wealth import router as wealth_router
from app.api.routes import router
from app.brokers.registry import PRICE_SOURCE_KEY, FeedContext, build_sources
from sqlalchemy import select

from app.db.models import Instrument, Setting, make_sessionmaker
from app.market.live import Feed, LiveHub
from app.secrets import MemoryStore, StoreFactory, TokenStore, memory_stores
from app.ws.routes import router as ws_router


def read_preference(sessionmaker) -> str:
    with sessionmaker() as session:
        row = session.get(Setting, PRICE_SOURCE_KEY)
        return row.value if row else "auto"


def create_app(
    db_url: str | None = None,
    token: str | None = None,
    feed: Feed | None = None,
    token_store: TokenStore | None = None,
    feed_factory: Callable[[FeedContext], Feed | None] | None = None,
    gemini_store: TokenStore | None = None,
    memo_generator: Callable[..., str] | None = None,
    store_factory: StoreFactory | None = None,
) -> FastAPI:
    """`feed_factory` builds the price feed from the configured sources and the
    saved price-source preference; it runs again whenever either changes.
    `feed` is a fixed feed for tests. `store_factory` makes the credential
    stores for broker fields (the OS keychain in production, memory in tests)."""
    store = token_store or MemoryStore()
    factory = feed_factory or (lambda _ctx: feed)
    sessionmaker = make_sessionmaker(db_url or config.database_url())
    def isin_of() -> dict[str, str]:
        with sessionmaker() as session:
            return {i.symbol: i.isin for i in session.scalars(select(Instrument)) if i.isin}

    sources = build_sources(store_factory or memory_stores, store, isin_of=isin_of)

    def feed_context() -> FeedContext:
        return FeedContext(sources=sources, preference=read_preference(sessionmaker),
                           cache_dir=config.data_dir())

    first_feed = factory(feed_context())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.hub:
            await app.state.hub.start()
        yield
        if app.state.hub:
            await app.state.hub.stop()

    app = FastAPI(title="Quant Terminal Engine", version="0.5.0", lifespan=lifespan)
    app.state.sessionmaker = sessionmaker
    app.state.token = token if token is not None else config.token()
    app.state.token_store = store
    app.state.sources = sources
    app.state.feed_context = feed_context
    app.state.gemini_store = gemini_store or MemoryStore()
    app.state.memo_generator = memo_generator or gemini.generate
    app.state.feed_factory = factory
    app.state.hub = LiveHub(sessionmaker, first_feed) if first_feed else None
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(http://(localhost|127\.0\.0\.1)(:\d+)?|file://|null)$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "version": app.version}

    app.include_router(router)
    app.include_router(connections_router)
    app.include_router(assets_router)
    app.include_router(watch_router)
    app.include_router(stress_router)
    app.include_router(news_router)
    app.include_router(wealth_router)
    app.include_router(ws_router)
    return app
