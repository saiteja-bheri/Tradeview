from __future__ import annotations

import json
import math
import re
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


LOCAL_ORIGIN = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
# "testserver" is the Host header of FastAPI's test client.
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "testserver"})


class LocalOnly:
    """Refuses requests a web page could forge (HTTP and WebSocket alike):

    - a Host other than this machine, which stops DNS rebinding, where a site's
      own domain is pointed at 127.0.0.1 so its pages count as same-origin;
    - when the engine runs without a session token, a request whose Origin is
      not a page on this machine. Browsers attach Origin to every cross-site
      request, including form posts and WebSockets that CORS never checks."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "").rsplit(":", 1)[0].strip("[]").lower()
        origin = headers.get("origin")
        locked = not scope["app"].state.token if "app" in scope else True
        bad_host = host not in LOCAL_HOSTS
        bad_origin = locked and origin is not None and not re.match(LOCAL_ORIGIN, origin)
        if not (bad_host or bad_origin):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await receive()  # the connect event
            return await send({"type": "websocket.close", "code": 4403})
        body = b'{"detail":"Request refused: the engine only answers this computer\'s own pages"}'
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _NotFinite(ValueError):
    pass


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):             # 1e309 and beyond overflow to infinity
        raise _NotFinite(text)
    return value


def _reject_constant(name: str):
    raise _NotFinite(name)                   # NaN, Infinity, -Infinity


class FiniteJson:
    """Refuses JSON bodies holding NaN or infinite numbers. Python's parser accepts
    them, validation lets infinity through "greater than 0" checks, and echoing a
    NaN back in an error crashed the response: a 500 instead of a clear refusal."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if "json" not in headers.get("content-type", ""):
            return await self.app(scope, receive, send)
        chunks, more = [], True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return await self.app(scope, receive, send)
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        try:
            json.loads(body or b"null", parse_constant=_reject_constant, parse_float=_finite_float)
        except _NotFinite as exc:
            payload = json.dumps({"detail": f"Numbers must be finite; got {str(exc)[:20]}"}).encode()
            await send({"type": "http.response.start", "status": 422,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(payload)).encode())]})
            return await send({"type": "http.response.body", "body": payload})
        except (ValueError, RecursionError):
            pass                                  # malformed JSON: FastAPI reports it as usual

        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


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
    # With a session token (the desktop app) the token is the lock, and the
    # packaged UI, loaded from disk, sends Origin "file://" or "null". Without
    # one (`npm run engine:dev`) only pages served from this machine may call in.
    origins = LOCAL_ORIGIN if not app.state.token else r"^(http://(localhost|127\.0\.0\.1)(:\d+)?|file://|null)$"
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(FiniteJson)
    app.add_middleware(LocalOnly)

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
