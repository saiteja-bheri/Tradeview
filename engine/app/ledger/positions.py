"""Replays trades and corporate actions in date order to build positions.

Cost basis is FIFO. A split or bonus multiplies every open lot's quantity and
divides its cost, so total cost is unchanged. A dividend adds cash income for
the quantity held going into the ex-date. Actions on a date apply before that
day's trades. Long-only: a sell beyond the held quantity is flagged and the
excess ignored."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

EPS = 1e-9


@dataclass
class Position:
    symbol: str
    lots: deque = field(default_factory=deque)  # [quantity, cost per share]
    realized_pnl: float = 0.0
    dividends: float = 0.0
    warnings: list[str] = field(default_factory=list)
    income: list = field(default_factory=list)  # [(date, cash)] dividends and coupons, for XIRR

    @property
    def quantity(self) -> float:
        return sum(q for q, _ in self.lots)

    @property
    def cost_value(self) -> float:
        return sum(q * c for q, c in self.lots)

    @property
    def avg_cost(self) -> float:
        qty = self.quantity
        return self.cost_value / qty if qty > EPS else 0.0


def _day(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def _events(trades: Iterable[Any], actions: Iterable[Any]) -> list[tuple]:
    events: list[tuple] = []
    for a in actions:
        if getattr(a, "review", "") == "skip":
            continue
        events.append((_day(a.ex_date), 0, datetime.min, "action", a))
    for t in trades:
        events.append((_day(t.traded_at), 1, t.traded_at, "trade", t))
    events.sort(key=lambda e: e[:3])
    return events


def held_on(trades: Iterable[Any], actions: Iterable[Any], symbol: str, when: datetime) -> float:
    """Quantity of `symbol` held just before a trade at `when`, splits and
    bonuses applied (same-day actions first, same-day earlier trades counted)."""
    qty = 0.0
    for day, _, at, kind, ev in _events([t for t in trades if t.symbol == symbol],
                                        [a for a in actions if a.symbol == symbol]):
        if kind == "trade" and (at >= when):
            break
        if kind == "action" and day > _day(when):
            break
        if kind == "action":
            if ev.kind in ("split", "bonus") and ev.value > 0:
                qty *= ev.value
        else:
            qty = qty + ev.quantity if ev.side == "BUY" else max(qty - ev.quantity, 0.0)
    return qty


def clip_oversells(trades: Iterable[Any], actions: Iterable[Any]) -> tuple[list[Any], list[str]]:
    """Caps every sale at the quantity held at that moment (long-only), so a
    sale the ledger cannot back (a typo, or a report that starts after the
    purchase) never creates cash, realised P&L or XIRR flows out of nothing.
    Returns (trades with capped sells; fully unbacked sells dropped, warnings)."""
    held: dict[str, float] = {}
    out: list[Any] = []
    warnings: list[str] = []
    for _, _, _, kind, ev in _events(trades, actions):
        if kind == "action":
            if ev.kind in ("split", "bonus") and ev.value > 0 and ev.symbol in held:
                held[ev.symbol] *= ev.value
            continue
        q = held.get(ev.symbol, 0.0)
        if ev.side == "BUY":
            held[ev.symbol] = q + float(ev.quantity)
            out.append(ev)
            continue
        sold = min(float(ev.quantity), q)
        excess = float(ev.quantity) - sold
        held[ev.symbol] = q - sold
        if excess > EPS:
            warnings.append(f"{ev.symbol}: sold {excess:g} more than held on {_day(ev.traded_at)}; the excess is "
                            "left out of holdings, cash and returns (missing earlier buys or a corporate action?)")
            if sold <= EPS:
                continue
            ev = _with_quantity(ev, sold)
        out.append(ev)
    return out, warnings


def _with_quantity(t: Any, quantity: float) -> Any:
    from types import SimpleNamespace
    fields = {k: getattr(t, k) for k in ("id", "symbol", "side", "price", "traded_at", "broker", "imported_at",
                                          "trade_id") if hasattr(t, k)}
    return SimpleNamespace(**fields, quantity=quantity)


def build_positions(trades: Iterable[Any], actions: Iterable[Any]) -> dict[str, Position]:
    events: list[tuple] = []
    for a in actions:
        if getattr(a, "review", "") == "skip":
            continue  # the uploaded quantities already include this split or bonus
        events.append((_day(a.ex_date), 0, datetime.min, "action", a))
    for t in trades:
        events.append((_day(t.traded_at), 1, t.traded_at, "trade", t))
    events.sort(key=lambda e: e[:3])

    book: dict[str, Position] = {}
    for _, _, _, kind, ev in events:
        pos = book.setdefault(ev.symbol, Position(ev.symbol))
        if kind == "action":
            if ev.kind in ("split", "bonus"):
                if ev.value > 0:
                    for lot in pos.lots:
                        lot[0] *= ev.value
                        lot[1] /= ev.value
            elif ev.kind == "dividend":
                cash = pos.quantity * ev.value
                pos.dividends += cash
                if cash > EPS:
                    pos.income.append((_day(ev.ex_date), cash))
            continue
        if ev.side == "BUY":
            pos.lots.append([float(ev.quantity), float(ev.price)])
            continue
        remaining = float(ev.quantity)
        while remaining > EPS and pos.lots:
            lot = pos.lots[0]
            used = min(lot[0], remaining)
            pos.realized_pnl += used * (ev.price - lot[1])
            lot[0] -= used
            remaining -= used
            if lot[0] <= EPS:
                pos.lots.popleft()
        if remaining > EPS:
            pos.warnings.append(
                f"{ev.symbol}: sold {remaining:g} more than held on {_day(ev.traded_at)}; "
                "excess ignored (missing earlier buys or a corporate action?)"
            )
    return book
