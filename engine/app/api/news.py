"""News and upcoming events (the NEWS tab)."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.routes import require_token
from app.market import news
from app.market.news_sources import SOURCES
from app.quant import service

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@router.get("/news")
async def news_feed(request: Request,
                    scope: Literal["all", "portfolio", "watchlist"] = "all",
                    symbol: str | None = Query(None, max_length=40),
                    sources: str | None = Query(None, max_length=200,
                                                description="Comma-separated source ids to show (default: all enabled)"),
                    refresh: bool = Query(True, description="Download what is stale (headlines every 30 min, calendars every 12 h)"),
                    force: bool = Query(False, description="Download now even if fresh"),
                    days: int = Query(60, ge=7, le=365, description="How far ahead to list events")):
    """Headlines for held, watched and starred stocks plus the benchmark (market
    news) from Yahoo, Google News and market wires, and their upcoming results,
    dividends, corporate actions and bond dates."""
    state = request.app.state
    news_fetcher = getattr(state, "news_fetcher", None)
    event_fetcher = getattr(state, "event_fetcher", None)
    rss_get = getattr(state, "rss_get", None)
    shown = [x.strip() for x in sources.split(",") if x.strip()] if sources else None

    def run() -> dict:
        with state.sessionmaker() as s:
            bench = service.get_settings(s)["benchmark"]
            return news.feed(s, bench, scope=scope, symbol=symbol.strip().upper() if symbol else None,
                             refresh_now=refresh, force=force, horizon_days=days, sources=shown,
                             news_fetcher=news_fetcher, event_fetcher=event_fetcher, rss_get=rss_get)

    return await asyncio.to_thread(run)


class SourcesIn(BaseModel):
    enabled: list[str]


@router.get("/news/sources")
def news_sources(request: Request):
    """Every news source and whether it is downloaded."""
    with request.app.state.sessionmaker() as s:
        on = news.enabled_sources(s)
    return [{"id": x, "label": m["label"], "region": m["region"], "kind": m["kind"], "enabled": x in on}
            for x, m in SOURCES.items()]


@router.put("/news/sources")
def set_news_sources(body: SourcesIn, request: Request):
    """Choose which sources are downloaded. Switched-off sources cost no downloads."""
    unknown = [x for x in body.enabled if x not in SOURCES]
    if unknown:
        raise HTTPException(400, f"Unknown news source: {', '.join(unknown)}")
    with request.app.state.sessionmaker() as s:
        news.set_sources(s, body.enabled)
    return news_sources(request)
