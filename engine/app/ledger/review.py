"""Checking splits and bonus issues against uploaded trade files.

A split or bonus multiplies every share held before its ex-date. The ledger
applies it to trades dated before the ex-date. That is right when the file
lists trades as they were originally executed, and wrong when the broker has
since restated old trades in post-split terms (some exports do): the split
would then be counted twice.

The ledger cannot know which from the file alone, so it asks once for every
split or bonus that falls between a trade's date and the day that trade
entered the ledger (upload, sync or manual entry). An action after the upload
cannot be in the file, so it is applied without asking.

Until answered, a pending action is applied (the common case) and flagged.
Each question carries a suggested answer from the prices: Yahoo's historical
closes are split-adjusted, so the ratio of the file's trade price to the close
on the same day shows whether the file is in pre- or post-split terms."""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import BrokerHolding, CorporateAction, PriceBar, Trade
from app.ledger.positions import build_positions

FACTOR_KINDS = ("split", "bonus")
TOLERANCE = math.log(1.2)   # a price within 20% of a hypothesis counts as a match


def _day(v) -> date:
    return v.date() if isinstance(v, datetime) else v


def _needs_question(action: CorporateAction, trades: list[Trade]) -> bool:
    for t in trades:
        if _day(t.traded_at) >= action.ex_date:
            continue
        entered = _day(t.imported_at) if t.imported_at else None
        if entered is None or entered >= action.ex_date:
            return True
    return False


def refresh(session: Session) -> int:
    """Marks the splits and bonuses that need a decision as pending (and clears
    stale pending marks). Answers already given are never changed. Returns the
    number pending."""
    actions = session.scalars(select(CorporateAction).where(CorporateAction.kind.in_(FACTOR_KINDS))).all()
    if not actions:
        return 0
    by_symbol: dict[str, list[Trade]] = {}
    for t in session.scalars(select(Trade).where(Trade.symbol.in_({a.symbol for a in actions}))):
        by_symbol.setdefault(t.symbol, []).append(t)
    pending = 0
    for a in actions:
        if a.review in ("apply", "skip"):
            continue
        needed = _needs_question(a, by_symbol.get(a.symbol, []))
        a.review = "pending" if needed else ""
        pending += needed
    session.flush()
    return pending


def _suggest(action: CorporateAction, trades: list[Trade], later_factor: float,
             closes: dict[date, float]) -> dict:
    """Compares the file's prices with Yahoo's split-adjusted closes.
    later_factor: product of this and every later split/bonus for the symbol,
    which is how far Yahoo has scaled closes before this ex-date."""
    ratios = []
    for t in trades:
        d = _day(t.traded_at)
        if d >= action.ex_date:
            continue
        close = closes.get(d)
        if close and close > 0 and t.price > 0:
            ratios.append(math.log(t.price / close))
    if not ratios:
        return {"answer": None, "reason": "No price history for the trade dates yet; refresh prices and look again."}
    observed = statistics.median(ratios)
    original = math.log(later_factor)                        # file in pre-split terms
    adjusted = math.log(later_factor / action.value)          # file already restated
    d_orig, d_adj = abs(observed - original), abs(observed - adjusted)
    if min(d_orig, d_adj) > TOLERANCE or abs(d_orig - d_adj) < TOLERANCE / 2:
        return {"answer": None, "reason": "The prices in the file don't clearly match either case."}
    if d_orig < d_adj:
        return {"answer": "apply",
                "reason": f"Prices in the file are about {math.exp(observed):.2f}× Yahoo's adjusted close, "
                          f"as expected for trades listed before the {action.kind}."}
    return {"answer": "skip",
            "reason": "Prices in the file already match Yahoo's adjusted close, so the file seems "
                      f"to be restated after the {action.kind}."}


def pending(session: Session) -> list[dict]:
    rows = session.scalars(select(CorporateAction).where(CorporateAction.review == "pending")
                           .order_by(CorporateAction.ex_date.desc())).all()
    if not rows:
        return []
    symbols = {a.symbol for a in rows}
    trades = session.scalars(select(Trade).where(Trade.symbol.in_(symbols))).all()
    actions = session.scalars(select(CorporateAction).where(CorporateAction.symbol.in_(symbols))).all()
    holdings = {(h.symbol, h.broker): h.quantity for h in
                session.scalars(select(BrokerHolding).where(BrokerHolding.symbol.in_(symbols)))}
    out = []
    for a in rows:
        mine = [t for t in trades if t.symbol == a.symbol]
        before = [t for t in mine if _day(t.traded_at) < a.ex_date]
        closes = {b.date: b.close for b in session.scalars(
            select(PriceBar).where(PriceBar.symbol == a.symbol, PriceBar.date < a.ex_date))}
        later = [x for x in actions if x.symbol == a.symbol and x.kind in FACTOR_KINDS
                 and x.ex_date >= a.ex_date and x.review != "skip" and x.value > 0]
        later_factor = math.prod(x.value for x in later) if later else a.value
        others = [x for x in actions if x.symbol == a.symbol and x.id != a.id and x.review != "skip"]
        with_it = build_positions(mine, others + [a]).get(a.symbol)
        without = build_positions(mine, others).get(a.symbol)
        uploaded = [t.imported_at for t in before if t.imported_at]
        out.append({
            "id": a.id, "symbol": a.symbol, "kind": a.kind, "value": a.value,
            "ex_date": a.ex_date.isoformat(), "source": a.source,
            "trades_before": len(before),
            "uploaded_on": max(uploaded).date().isoformat() if uploaded else None,
            "quantity_if_applied": with_it.quantity if with_it else 0.0,
            "quantity_if_skipped": without.quantity if without else 0.0,
            "broker_quantity": next((q for (s, _), q in holdings.items() if s == a.symbol), None),
            "suggestion": _suggest(a, before, later_factor, closes),
        })
    return out


def decide(session: Session, action_id: int, decision: str) -> CorporateAction:
    if decision not in ("apply", "skip"):
        raise ValueError("decision must be apply or skip")
    action = session.get(CorporateAction, action_id)
    if action is None or action.kind not in FACTOR_KINDS:
        raise LookupError("No such split or bonus")
    action.review = decision
    session.commit()
    return action
