"""Broker and data-source connections: credentials, daily login sessions,
holdings sync, and which source streams live prices.

Read-only towards every broker. A sync reads holdings and the day's trades
and writes them only to the local ledger; credentials go to the OS keychain
and are never sent back to the UI."""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app import config
from app.api.routes import _poke, require_token, restart_feed
from app.brokers.base import BrokerError, Source
from app.brokers.registry import PRICE_SOURCE_KEY, PRICE_SOURCES
from app.db.models import BrokerHolding, Setting
from app.ledger import ingest
from app.quant import service

router = APIRouter(prefix="/api/connections", dependencies=[Depends(require_token)])


class CredentialsIn(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class SessionIn(BaseModel):
    value: str | None = Field(default=None, max_length=4096)


class PriceSourceIn(BaseModel):
    source: str


def _source(request: Request, source_id: str) -> Source:
    source = request.app.state.sources.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"No source called '{source_id}'")
    return source


def _http(exc: BrokerError) -> HTTPException:
    return HTTPException(status_code=exc.status if 400 <= exc.status < 600 else 502, detail=str(exc))


def _overview(request: Request) -> dict:
    app = request.app
    with app.state.sessionmaker() as session:
        pref = session.get(Setting, PRICE_SOURCE_KEY)
        synced = {s.key.split(":", 1)[1]: s.value
                  for s in session.scalars(select(Setting).where(Setting.key.like("synced:%")))}
        counts = dict(session.execute(
            select(BrokerHolding.broker, func.count()).group_by(BrokerHolding.broker)).all())
        mismatches = service.reconcile(session)
    rows = []
    for source in app.state.sources.values():
        row = source.status()
        row["last_sync"] = synced.get(source.id)
        row["holdings_synced"] = counts.get(source.id, 0)
        row["mismatches"] = [m for m in mismatches if m["broker"] == source.id]
        rows.append(row)
    env = config.feed_choice()
    hub = app.state.hub
    return {
        "price_source": pref.value if pref else "auto",
        "price_sources": list(PRICE_SOURCES),
        "env_override": env if env not in ("", "auto") else None,
        "feed": hub.status if hub else {"source": "none", "state": "off", "detail": "Live feed is off"},
        "sources": rows,
    }


@router.get("")
async def overview(request: Request):
    return await asyncio.to_thread(_overview, request)


@router.put("/price-source")
async def set_price_source(body: PriceSourceIn, request: Request):
    if body.source not in PRICE_SOURCES:
        raise HTTPException(status_code=400, detail=f"Price source must be one of {', '.join(PRICE_SOURCES)}")

    def save() -> None:
        with request.app.state.sessionmaker() as session:
            row = session.get(Setting, PRICE_SOURCE_KEY)
            if row:
                row.value = body.source
            else:
                session.add(Setting(key=PRICE_SOURCE_KEY, value=body.source))
            session.commit()

    await asyncio.to_thread(save)
    await restart_feed(request.app)
    return await asyncio.to_thread(_overview, request)


@router.put("/{source_id}/credentials")
async def save_credentials(source_id: str, body: CredentialsIn, request: Request):
    source = _source(request, source_id)
    try:
        await asyncio.to_thread(source.save, body.values)
    except BrokerError as exc:
        raise _http(exc) from exc
    await restart_feed(request.app)
    return await asyncio.to_thread(_overview, request)


@router.delete("/{source_id}/credentials")
async def remove_credentials(source_id: str, request: Request):
    source = _source(request, source_id)
    await asyncio.to_thread(source.clear)
    await restart_feed(request.app)
    return await asyncio.to_thread(_overview, request)


@router.get("/{source_id}/login-url")
async def login_url(source_id: str, request: Request):
    source = _source(request, source_id)
    try:
        url = await asyncio.to_thread(source.login_url)
    except BrokerError as exc:
        raise _http(exc) from exc
    if not url:
        raise HTTPException(status_code=400, detail=f"{source.label} has no browser login")
    return {"url": url}


@router.post("/{source_id}/session")
async def open_session(source_id: str, body: SessionIn, request: Request):
    """Zerodha: paste the address Kite redirected to. Groww: empty body to log
    in with the saved TOTP or API secret, or paste an access token."""
    source = _source(request, source_id)
    try:
        await asyncio.to_thread(source.start_session, body.value)
    except BrokerError as exc:
        raise _http(exc) from exc
    await restart_feed(request.app)
    return await asyncio.to_thread(_overview, request)


@router.delete("/{source_id}/session")
async def close_session(source_id: str, request: Request):
    source = _source(request, source_id)
    await asyncio.to_thread(source.end_session)
    await restart_feed(request.app)
    return await asyncio.to_thread(_overview, request)


@router.post("/{source_id}/sync")
async def sync(source_id: str, request: Request):
    """Adds the broker's trades for today to the ledger and saves its holdings
    so the ledger can be checked against them."""
    source = _source(request, source_id)
    if not ({"holdings", "trades"} & source.capabilities):
        raise HTTPException(status_code=400, detail=f"{source.label} has nothing to sync; use IMPORT CSV")
    try:
        trades = await asyncio.to_thread(source.fetch_trades) if "trades" in source.capabilities else []
        holdings = await asyncio.to_thread(source.fetch_holdings) if "holdings" in source.capabilities else []
    except BrokerError as exc:
        raise _http(exc) from exc

    def save() -> dict:
        now = datetime.now().replace(microsecond=0)
        with request.app.state.sessionmaker() as session:
            result = ingest.store_trades(session, trades)
            if "holdings" in source.capabilities:
                session.execute(delete(BrokerHolding).where(BrokerHolding.broker == source.id))
                for h in holdings:
                    ingest.remember_instrument(session, h.symbol, h.name, h.isin)
                    session.merge(BrokerHolding(broker=source.id, symbol=h.symbol, isin=h.isin, name=h.name,
                                                quantity=h.quantity, avg_price=h.avg_price, synced_at=now))
            key = f"synced:{source.id}"
            marker = session.get(Setting, key)
            if marker:
                marker.value = now.isoformat()
            else:
                session.add(Setting(key=key, value=now.isoformat()))
            session.commit()
            mismatches = [m for m in service.reconcile(session) if m["broker"] == source.id]
        return {"imported": result.imported, "duplicates": result.duplicates,
                "holdings": len(holdings), "mismatches": mismatches, "synced_at": now.isoformat()}

    out = await asyncio.to_thread(save)
    _poke(request)
    return out


@router.get("/reconciliation")
def reconciliation(request: Request):
    with request.app.state.sessionmaker() as session:
        return service.reconcile(session)
