"""Portfolio cash: the money held inside the portfolio, like a broker's cash account.

Cash comes in from dividends and bond coupons (on their ex-dates, in rupees at
that day's exchange rate) and from sale proceeds. It stays there, counted in net
worth, until the user records a withdrawal. Nothing is assumed to have been
taken out.

Purchases are paid from this cash first; whatever the cash does not cover is
new money put in from outside. That keeps money from being counted twice: a
sale's proceeds that buy another stock become that stock, not extra cash.

So, at any date:
    cash        = dividends + sale proceeds - purchases paid from cash - withdrawals
    money in    = new money put in for purchases - withdrawals
    gain        = market value + cash - money in
Same-day order: dividends, then sales, then purchases (a same-day sale can fund
a same-day purchase), then withdrawals."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CashWithdrawal
from app.ledger.positions import build_positions
from app.quant import service

ORDER = {"dividend": 0, "sale": 1, "purchase": 2, "withdrawal": 3}


def payouts(session: Session) -> list[dict]:
    """[{date, symbol, amount}] for every dividend and coupon received, oldest first (INR)."""
    trades, actions, _, _ = service.inr_ledger(session)
    out = []
    for symbol, pos in build_positions(trades, actions).items():
        for d, cash in pos.income:
            out.append({"date": d, "symbol": symbol, "amount": float(cash)})
    return sorted(out, key=lambda p: (p["date"], p["symbol"]))


def withdrawals(session: Session) -> list[CashWithdrawal]:
    return session.scalars(select(CashWithdrawal).order_by(CashWithdrawal.date, CashWithdrawal.id)).all()


def events(session: Session, *, skip_withdrawal: int | None = None) -> list[dict]:
    """Every cash movement, in order, with the running cash balance and money put in."""
    trades, _, _, _ = service.inr_ledger(session)
    raw = [{"date": p["date"], "kind": "dividend", "symbol": p["symbol"], "amount": p["amount"]}
           for p in payouts(session) if p["date"] <= date.today()]
    for t in trades:
        raw.append({"date": t.traded_at.date(), "kind": "sale" if t.side == "SELL" else "purchase",
                    "symbol": t.symbol, "amount": t.quantity * t.price})
    for w in withdrawals(session):
        if w.id != skip_withdrawal:
            raw.append({"date": w.date, "kind": "withdrawal", "symbol": "", "amount": w.amount, "id": w.id,
                        "note": w.note})
    raw.sort(key=lambda e: (e["date"], ORDER[e["kind"]]))

    cash = money_in = 0.0
    out = []
    for e in raw:
        if e["kind"] in ("dividend", "sale"):
            cash += e["amount"]
            from_cash = new_money = 0.0
        elif e["kind"] == "purchase":
            from_cash = min(cash, e["amount"])
            new_money = e["amount"] - from_cash
            cash -= from_cash
            money_in += new_money
        else:  # withdrawal
            cash -= e["amount"]
            money_in -= e["amount"]
            from_cash, new_money = e["amount"], 0.0
        out.append({**e, "from_cash": from_cash, "new_money": new_money, "cash": cash, "money_in": money_in})
    return out


def state_on(evts: list[dict], on: date) -> tuple[float, float]:
    """(cash, money in) at the end of a day."""
    cash = money_in = 0.0
    for e in evts:
        if e["date"] > on:
            break
        cash, money_in = e["cash"], e["money_in"]
    return cash, money_in


def balance(session: Session, on: date | None = None) -> dict:
    """Portfolio cash on a day (today by default)."""
    evts = events(session)
    cash, money_in = state_on(evts, on or date.today())
    return {"balance": cash, "money_in": money_in}


def overdrawn(session: Session) -> dict | None:
    """The first movement that takes the cash below zero (only a withdrawal can), or None."""
    for e in events(session):
        if e["cash"] < -0.005:
            return e
    return None


def summary(session: Session) -> dict:
    evts = events(session)
    cash, money_in = state_on(evts, date.today())
    total = lambda kind, key="amount": sum(e[key] for e in evts if e["kind"] == kind)  # noqa: E731
    return {
        "balance": cash,
        "dividends": total("dividend"),
        "sale_proceeds": total("sale"),
        "spent_from_cash": total("purchase", "from_cash"),
        "new_money": total("purchase", "new_money"),
        "withdrawn": total("withdrawal"),
        "money_in": money_in,
        "movements": [{k: (v.isoformat() if isinstance(v, date) else v) for k, v in e.items()}
                      for e in reversed(evts)][:300],
        "withdrawals": [{"id": w.id, "date": w.date.isoformat(), "amount": w.amount, "note": w.note}
                        for w in reversed(withdrawals(session))],
    }
