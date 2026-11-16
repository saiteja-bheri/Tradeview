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
