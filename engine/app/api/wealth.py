"""Wealth outside the market portfolio (cash, deposits, pension, insurance) and
the projection of portfolio value with a SIP."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes import _poke, get_session, require_token
from app.db.models import WealthItem
from types import SimpleNamespace

from app.db.models import CashWithdrawal
from app.quant import cashflow, projection, service, wealth

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

Kind = Literal["cash", "fixed_deposit", "recurring_deposit", "ppf", "epf", "nps", "pension",
               "life_insurance", "term_insurance"]


class WealthIn(BaseModel):
    kind: Kind
    name: str = Field(default="", max_length=120)
    institution: str = Field(default="", max_length=120)
    amount: float = Field(default=0.0, ge=0, description="Balance, fund value, or FD principal (INR)")
    rate: float = Field(default=0.0, ge=0, lt=50, description="Annual %; 0 uses the default for the kind")
    start_date: date | None = None
    maturity_date: date | None = None
    monthly_contribution: float = Field(default=0.0, ge=0)
    cover: float = Field(default=0.0, ge=0, description="Insurance sum assured")
    premium: float = Field(default=0.0, ge=0, description="Insurance premium per year")
    notes: str = Field(default="", max_length=400)


def market_side(session: Session) -> tuple[float, dict[str, float], dict]:
    """Market portfolio value, its value by asset class, and the computed metrics (cached prices only)."""
    data = service.compute(session, refresh=False)
    by_class: dict[str, float] = {}
    for h in data["holdings"]:
        if h.get("value"):
            by_class[h.get("asset_class") or "equity"] = by_class.get(h.get("asset_class") or "equity", 0.0) + h["value"]
    return data["portfolio_value"] or 0.0, by_class, data


def overview(session: Session) -> dict:
    value, by_class, _ = market_side(session)
    items = session.scalars(select(WealthItem).order_by(WealthItem.kind, WealthItem.name)).all()
    out = wealth.summary(items, value, by_class, cashflow.balance(session)["balance"])
    out["kinds"] = [{"kind": k, **v} for k, v in wealth.KINDS.items()]
    return out


@router.get("/wealth")
def wealth_overview(session: Session = Depends(get_session)):
    """Net worth: the market portfolio plus cash, deposits, pension and insurance."""
    return overview(session)


def _apply(item: WealthItem, body: WealthIn) -> None:
    if body.maturity_date and body.start_date and body.maturity_date < body.start_date:
        raise HTTPException(status_code=400, detail="Maturity is before the start date")
    if body.kind == "fixed_deposit" and not body.start_date:
        raise HTTPException(status_code=400, detail="A fixed deposit needs its start date to work out interest")
    for k, v in body.model_dump().items():
        setattr(item, k, v.strip() if isinstance(v, str) else v)
    item.updated_at = datetime.now().replace(microsecond=0)


@router.post("/wealth", status_code=201)
def add_item(body: WealthIn, request: Request, session: Session = Depends(get_session)):
    item = WealthItem()
    _apply(item, body)
    session.add(item)
    session.commit()
    _poke(request)
    return wealth.item_json(item)


@router.put("/wealth/{item_id}")
def edit_item(item_id: int, body: WealthIn, request: Request, session: Session = Depends(get_session)):
    item = session.get(WealthItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item")
    _apply(item, body)
    session.commit()
    _poke(request)
    return wealth.item_json(item)


@router.delete("/wealth/{item_id}")
def delete_item(item_id: int, request: Request, session: Session = Depends(get_session)):
    item = session.get(WealthItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such item")
    session.delete(item)
    session.commit()
    _poke(request)
    return {"deleted": item_id}


# ---------------------------------------------------------------- projection

class ProjectionIn(BaseModel):
    mode: Literal["continue", "fresh"] = Field(
        default="continue", description="continue = current portfolio plus a SIP; fresh = a new SIP from zero")
    monthly_sip: float = Field(default=10_000, ge=0, le=1e9)
    step_up_pct: float = Field(default=0.0, ge=0, le=50, description="Yearly increase in the SIP, percent")
    years: int = Field(default=10, ge=1, le=40)
    interval: Literal["monthly", "quarterly", "yearly"] = "yearly"
    outlook: Literal["past", "cautious", "neutral", "optimistic"] = "neutral"
    include_wealth: bool = Field(default=True, description="Grow deposits, pension and insurance alongside")
    simulations: int = Field(default=5_000, ge=500, le=20_000)
    tax_gains_pct: float = Field(default=12.5, ge=0, le=50,
                                 description="Tax on market gains if sold, percent (equity LTCG is 12.5% in India)")
    gains_exemption: float = Field(default=125_000, ge=0, le=1e9,
                                   description="Gain that is tax-free (ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¹1.25 lakh a year for equity LTCG in India)")
    tax_interest_pct: float = Field(default=0.0, ge=0, le=50,
                                    description="Your income-tax slab, taken out of deposit and savings interest")
    renew_deposits: bool = Field(default=True, description="Renew FDs/RDs at the same rate when they mature")


@router.post("/projection")
async def project(body: ProjectionIn, request: Request):
    """Portfolio value at equal intervals if you keep investing (or start) a SIP,
    from the market outlook you pick or the portfolio's own past performance."""

    def run() -> dict:
        with request.app.state.sessionmaker() as s:
            value, by_class, data = market_side(s)
            cost = value - (data.get("unrealized_pnl") or 0.0)   # what today's holdings cost
            items = list(s.scalars(select(WealthItem)).all()) if body.include_wealth else []
            held_cash = cashflow.balance(s)["balance"]
            if body.include_wealth and held_cash > 0:   # dividend cash grows at the savings rate
                items.append(SimpleNamespace(kind="cash", amount=held_cash, rate=0.0, start_date=None,
                                             maturity_date=None, monthly_contribution=0.0))
            return projection.project(
                start_value=value if body.mode == "continue" else 0.0,
                by_class=by_class,   # a fresh SIP is assumed to follow today's mix (or equity if none)
                metrics=data.get("metrics") or {}, observations=data.get("observations", 0),
                monthly_sip=body.monthly_sip, step_up_pct=body.step_up_pct, years=body.years,
                interval=body.interval, outlook=body.outlook, wealth_items=items, simulations=body.simulations,
                risk_free=float(data["params"]["risk_free_rate"]),
                start_cost=cost if body.mode == "continue" else 0.0,
                tax_gains_pct=body.tax_gains_pct, gains_exemption=body.gains_exemption,
                tax_interest_pct=body.tax_interest_pct, renew_deposits=body.renew_deposits)

    return await asyncio.to_thread(run)


# ---------------------------------------------------------------- portfolio cash

class WithdrawalIn(BaseModel):
    date: date
    amount: float = Field(gt=0, le=1e12)
    note: str = Field(default="", max_length=200)


@router.get("/portfolio-cash")
@router.get("/dividend-cash")          # older name, kept for compatibility
def portfolio_cash(session: Session = Depends(get_session)):
    """Cash in the portfolio: dividends, coupons and sale proceeds, less purchases
    paid from it and recorded withdrawals, with every movement."""
    return cashflow.summary(session)


@router.post("/portfolio-cash/withdrawals", status_code=201)
@router.post("/dividend-cash/withdrawals", status_code=201)
def record_withdrawal(body: WithdrawalIn, request: Request, session: Session = Depends(get_session)):
    """Records money taken out of the portfolio. Until then it stays as cash."""
    row = CashWithdrawal(date=body.date, amount=body.amount, note=body.note.strip())
    session.add(row)
    session.flush()
    problem = cashflow.overdrawn(session)
    if problem is not None:
        session.rollback()
        cash_then = cashflow.state_on(cashflow.events(session), body.date)[0]
        detail = (f"Only {cash_then:,.2f} of portfolio cash was available on {body.date}"
                  if problem.get("id") == row.id else
                  f"That would leave too little cash for the withdrawal of {problem['amount']:,.2f} on {problem['date']}")
        raise HTTPException(status_code=400, detail=detail)
    session.commit()
    _poke(request)
    return cashflow.summary(session)


@router.delete("/portfolio-cash/withdrawals/{withdrawal_id}")
@router.delete("/dividend-cash/withdrawals/{withdrawal_id}")
def delete_withdrawal(withdrawal_id: int, request: Request, session: Session = Depends(get_session)):
    w = session.get(CashWithdrawal, withdrawal_id)
    if w is None:
        raise HTTPException(status_code=404, detail="No such withdrawal")
    session.delete(w)
    session.commit()
    _poke(request)
    return cashflow.summary(session)


# ---------------------------------------------------------------- performance over time

@router.get("/timeline")
async def timeline_data(request: Request, start: date | None = None, end: date | None = None):
    """Portfolio value, money invested, dividend cash, gain, other wealth and net
    worth for every day in the period (all of it by default)."""
    from app.quant import timeline

    def run() -> dict:
        with request.app.state.sessionmaker() as s:
            return timeline.build(s, start, end)

    return await asyncio.to_thread(run)
