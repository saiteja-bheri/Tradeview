"""Replays trades and corporate actions in date order to build positions.

Cost basis is FIFO. A split or bonus multiplies every open lot's quantity and
divides its cost, so total cost is unchanged. A dividend adds cash income for
the quantity held going into the ex-date. Actions on a date apply before that
day's trades. Long-only: a sell beyond the held quantity is flagged and the
excess ignored."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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


# Same-day order of actions: splits, bonuses and dividends first (as before),
# then a demerger, then the parent's rename, so the demerger works on the old symbol.
_ACTION_ORDER = {"demerger": 1, "rename": 2}


def _action_key(a: Any) -> datetime:
    return datetime.min + timedelta(microseconds=_ACTION_ORDER.get(a.kind, 0))


def _transfer(held: dict[str, float], ev: Any) -> None:
    """Applies a demerger or rename to a {symbol: quantity} map."""
    q = held.get(ev.symbol, 0.0)
    if ev.kind == "demerger" and ev.value > 0:
        held[ev.target] = held.get(ev.target, 0.0) + q * ev.value
    elif ev.kind == "rename":
        held[ev.target] = held.get(ev.target, 0.0) + held.pop(ev.symbol, 0.0)


def _events(trades: Iterable[Any], actions: Iterable[Any]) -> list[tuple]:
    events: list[tuple] = []
    for a in actions:
        if getattr(a, "review", "") == "skip":
            continue
        events.append((_day(a.ex_date), 0, _action_key(a), "action", a))
    for t in trades:
        events.append((_day(t.traded_at), 1, t.traded_at, "trade", t))
    events.sort(key=lambda e: e[:3])
    return events


def held_on(trades: Iterable[Any], actions: Iterable[Any], symbol: str, when: datetime) -> float:
    """Quantity of `symbol` held just before a trade at `when`, splits, bonuses,
    demergers and renames applied (same-day actions first, same-day earlier
    trades counted). Shares that arrived through a demerger or rename count too,
    so the whole ledger is replayed, not only this symbol's rows."""
    held: dict[str, float] = {}
    for day, _, at, kind, ev in _events(trades, actions):
        if kind == "trade" and (at >= when):
            break
        if kind == "action" and day > _day(when):
            break
        if kind == "action":
            if ev.kind in ("split", "bonus") and ev.value > 0 and ev.symbol in held:
                held[ev.symbol] *= ev.value
            else:
                _transfer(held, ev)
        else:
            q = held.get(ev.symbol, 0.0)
            held[ev.symbol] = q + ev.quantity if ev.side == "BUY" else max(q - ev.quantity, 0.0)
    return held.get(symbol, 0.0)


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
            else:
                _transfer(held, ev)
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


def _paid_per_share(dividend: Any, yahoo_splits: dict[str, list[tuple[date, float]]]) -> float:
    """Cash per share actually paid on the ex-date. Yahoo restates past dividends
    in today's shares, so a dividend paid before a later split is listed divided
    by that split; multiply it back. Manual and BSE dividends are entered as paid."""
    value = float(dividend.value)
    if getattr(dividend, "source", "manual") != "yfinance":
        return value
    ex = _day(dividend.ex_date)
    for when, factor in yahoo_splits.get(dividend.symbol, []):
        if when > ex:
            value *= factor
    return value


def build_positions(trades: Iterable[Any], actions: Iterable[Any]) -> dict[str, Position]:
    actions = list(actions)
    # Every split Yahoo knows about restates its dividends, including splits the
    # user marked as already in their file ("skip"): Yahoo still restated.
    yahoo_splits: dict[str, list[tuple[date, float]]] = {}
    for a in actions:
        if getattr(a, "source", "") == "yfinance" and a.kind in ("split", "bonus") and a.value > 0:
            yahoo_splits.setdefault(a.symbol, []).append((_day(a.ex_date), float(a.value)))
    events: list[tuple] = []
    for a in actions:
        if getattr(a, "review", "") == "skip":
            continue  # the uploaded quantities already include this split or bonus
        events.append((_day(a.ex_date), 0, _action_key(a), "action", a))
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
                cash = pos.quantity * _paid_per_share(ev, yahoo_splits)
                pos.dividends += cash
                if cash > EPS:
                    pos.income.append((_day(ev.ex_date), cash))
            elif ev.kind == "demerger" and ev.value > 0:
                # Each open lot gives `value` new shares per share held, carrying
                # `cost_share` of that lot's cost; the parent keeps the rest.
                share = float(getattr(ev, "cost_share", 0.0) or 0.0)
                child = book.setdefault(ev.target, Position(ev.target))
                for lot in pos.lots:
                    child.lots.append([lot[0] * ev.value, lot[1] * share / ev.value])
                    lot[1] *= 1.0 - share
            elif ev.kind == "rename":
                # The same holding under a new symbol: lots (in FIFO order), realised
                # P&L and income move over, ahead of anything already under the new symbol.
                new = book.setdefault(ev.target, Position(ev.target))
                new.lots = deque(list(pos.lots) + list(new.lots))
                new.realized_pnl += pos.realized_pnl
                new.dividends += pos.dividends
                new.income = pos.income + new.income
                new.warnings = pos.warnings + new.warnings
                del book[ev.symbol]
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
