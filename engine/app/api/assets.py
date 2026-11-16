"""Non-stock holdings and their data: bond terms, asset-class overrides, the
commodity list, and corporate actions pulled from BSE."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.api.routes import _poke, get_session, require_token
from app.db.models import Bond, CorporateAction, Instrument, Trade
from app.ledger import ingest, review
from app.market import bonds as bond_math
from app.market import commodities, symbols
from app.market.bse_india import BseClient
from app.quant import service

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


# ---------------------------------------------------------------- bonds

class BondIn(BaseModel):
    name: str = Field(default="", max_length=120)
    isin: str = Field(default="", max_length=12)
    face_value: float = Field(default=1000.0, gt=0)
    coupon_rate: float = Field(default=0.0, ge=0, lt=50, description="Annual coupon, percent of face value")
    frequency: Literal[0, 1, 2, 4, 12] = 2
    maturity: date
    price: float = Field(default=0.0, ge=0, description="Valuation price per bond; 0 means face value")


def _bond_json(b: Bond) -> dict:
    return {"symbol": b.symbol, "name": b.name, "isin": b.isin, "face_value": b.face_value,
            "coupon_rate": b.coupon_rate, "frequency": b.frequency, "maturity": b.maturity.isoformat(),
            "price": b.price, "coupon_per_bond": bond_math.coupon(b)}


@router.get("/bonds")
def list_bonds(session: Session = Depends(get_session)):
    return [_bond_json(b) for b in session.scalars(select(Bond).order_by(Bond.maturity))]


@router.put("/bonds/{symbol}")
def save_bond(symbol: str, body: BondIn, request: Request, session: Session = Depends(get_session)):
    symbol = symbol.strip().upper()
    if not symbol.startswith("BOND:"):
        symbol = f"BOND:{symbol}"
    if not symbols.is_namespaced(symbol):
        raise HTTPException(status_code=400, detail="Bond id: letters, digits and dashes, e.g. GOI2033")
    bond = session.get(Bond, symbol) or Bond(symbol=symbol)
    bond.name, bond.isin = body.name.strip(), body.isin.strip().upper()
    bond.face_value, bond.coupon_rate, bond.frequency = body.face_value, body.coupon_rate, body.frequency
    bond.maturity, bond.price = body.maturity, body.price
    session.merge(bond)
    ingest.remember_instrument(session, symbol, bond.name, bond.isin)
    inst = session.get(Instrument, symbol)
    if inst is not None:
        inst.name = bond.name or inst.name
    session.commit()
    _poke(request)
    return _bond_json(session.get(Bond, symbol))


@router.delete("/bonds/{symbol}")
def delete_bond(symbol: str, session: Session = Depends(get_session)):
    bond = session.get(Bond, symbol.strip().upper())
    if bond is None:
        raise HTTPException(status_code=404, detail="No such bond")
    if session.scalar(select(Trade.id).where(Trade.symbol == bond.symbol).limit(1)):
        raise HTTPException(status_code=409, detail="Trades in the ledger use this bond; remove them first")
    session.delete(bond)
    session.commit()
    return {"deleted": bond.symbol}


# ---------------------------------------------------------------- asset classes

class AssetClassIn(BaseModel):
    asset_class: Literal["", "equity", "etf", "mutual_fund", "gold", "commodity", "bond"]


@router.put("/instruments/{symbol}/asset-class")
def set_asset_class(symbol: str, body: AssetClassIn, session: Session = Depends(get_session)):
    """Overrides the automatic classification ('' goes back to automatic)."""
    inst = session.get(Instrument, symbol)
    if inst is None:
        raise HTTPException(status_code=404, detail="Unknown instrument")
    inst.asset_class = body.asset_class
    session.commit()
    return {"symbol": symbol, "asset_class": body.asset_class or symbols.asset_class(symbol, inst.name)}


@router.get("/commodities")
def list_commodities():
    return [{"symbol": f"CMDTY:{name}", "name": label, "unit": unit, "source": future}
            for name, (future, unit, _, label) in commodities.COMMODITIES.items()]


# ---------------------------------------------------------------- BSE corporate actions

def sync_bse_actions(session: Session, client: BseClient) -> dict:
    """Adds dividends, bonus issues and splits from BSE for every stock ever
    traded, over the price-history window. An action already recorded for the
    same date (from Yahoo or entered by hand) is left alone."""
    traded = sorted(s for s in session.scalars(select(Trade.symbol).distinct())
                    if not symbols.namespace(s) and symbols.split(s)[1])
    start, end = service.history_start(session), date.today() + timedelta(days=60)
    isins = {i.symbol: i.isin for i in session.scalars(select(Instrument)) if i.isin}
    added, skipped, failed = [], 0, []
    for symbol in traded:
        try:
            code = client.code_for(symbol, isins.get(symbol, ""))
            if not code:
                failed.append(f"{symbol}: not found on BSE")
                continue
            found = client.actions(code, start, end)
        except RuntimeError:
            raise
        except Exception as exc:
            failed.append(f"{symbol}: {exc}")
            continue
        existing = {(a.ex_date, "factor" if a.kind in ("split", "bonus") else a.kind)
                    for a in session.scalars(select(CorporateAction).where(CorporateAction.symbol == symbol))}
        for a in found:
            family = "factor" if a["kind"] in ("split", "bonus") else a["kind"]
            if (a["ex_date"], family) in existing:
                skipped += 1
                continue
            session.add(CorporateAction(symbol=symbol, ex_date=a["ex_date"], kind=a["kind"],
                                        value=a["value"], source="bse"))
            existing.add((a["ex_date"], family))
            added.append({"symbol": symbol, "ex_date": a["ex_date"].isoformat(), "kind": a["kind"],
                          "value": a["value"], "purpose": a["purpose"]})
    session.commit()
    return {"added": added, "already_recorded": skipped, "failed": failed, "checked": len(traded)}


@router.post("/corporate-actions/bse-sync")
async def bse_sync(request: Request):
    """Pulls corporate actions from BSE (needs the optional `bse` package)."""
    factory = getattr(request.app.state, "bse_factory", None)

    def run() -> dict:
        with BseClient(config.data_dir(), factory=factory) as client, request.app.state.sessionmaker() as s:
            return sync_bse_actions(s, client)

    try:
        out = await asyncio.to_thread(run)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    _poke(request)
    return out


# ---------------------------------------------------------------- split / bonus review

class ReviewIn(BaseModel):
    decision: Literal["apply", "skip"]


@router.get("/corporate-actions/review")
def actions_to_review(session: Session = Depends(get_session)):
    """Splits and bonuses that may already be reflected in an uploaded file."""
    review.refresh(session)
    session.commit()
    return review.pending(session)


@router.post("/corporate-actions/review/accept-suggestions")
def accept_suggestions(request: Request, session: Session = Depends(get_session)):
    review.refresh(session)
    decided = []
    for item in review.pending(session):
        answer = item["suggestion"]["answer"]
        if answer:
            review.decide(session, item["id"], answer)
            decided.append({"id": item["id"], "decision": answer})
    session.commit()
    _poke(request)
    return {"decided": decided, "remaining": len(review.pending(session))}


@router.post("/corporate-actions/{action_id}/review")
def decide_action(action_id: int, body: ReviewIn, request: Request, session: Session = Depends(get_session)):
    try:
        action = review.decide(session, action_id, body.decision)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _poke(request)
    return {"id": action.id, "review": action.review}
