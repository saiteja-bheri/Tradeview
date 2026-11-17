"""Money-weighted returns.

Total return = realized P&L + unrealized P&L + dividends/coupons, as a share of
the money put in (sum of all purchases).

XIRR is the annual rate r that makes the dated cash flows sum to zero:
  sum(cf_i / (1 + r) ** (days_i / 365)) = 0
with purchases negative, sales and income positive, and today's market value
as a final positive flow. It is the figure Indian fund statements show, and
unlike a simple return it accounts for when money went in. Brokerage, taxes
and charges are not in the ledger, so returns here are before costs."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from scipy.optimize import brentq

Flow = tuple[date, float]


def _day(value) -> date:
    return value.date() if isinstance(value, datetime) else value


def xirr(flows: Iterable[Flow]) -> float | None:
    flows = sorted((_day(d), float(cf)) for d, cf in flows if abs(cf) > 1e-9)
    if len(flows) < 2 or not any(cf < 0 for _, cf in flows) or not any(cf > 0 for _, cf in flows):
        return None
    t0 = flows[0][0]
    span = (flows[-1][0] - t0).days
    if span < 1:
        return None
    years = [((d - t0).days) / 365.0 for d, _ in flows]
    cfs = [cf for _, cf in flows]

    def npv(rate: float) -> float:
        return sum(cf / (1.0 + rate) ** y for cf, y in zip(cfs, years))

    lo, hi = -0.9999, 10.0
    try:
        f_lo, f_hi = npv(lo), npv(hi)
        while f_lo * f_hi > 0 and hi < 1e6:
            hi *= 10
            f_hi = npv(hi)
        if f_lo * f_hi > 0:
            return None
        rate = brentq(npv, lo, hi, maxiter=200)
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    return rate if math.isfinite(rate) else None


def compute_returns(trades, positions: dict, value_now: dict[str, float],
                    today: date | None = None) -> tuple[dict[str, dict], dict]:
    """Per-symbol and whole-portfolio returns.

    trades: ledger rows (symbol, side, quantity, price, traded_at)
    positions: symbol -> Position (realized_pnl, dividends, income, cost_value)
    value_now: symbol -> current market value of the open position
    """
    today = today or date.today()
    flows: dict[str, list[Flow]] = defaultdict(list)
    invested: dict[str, float] = defaultdict(float)
    for t in trades:
        amount = t.quantity * t.price
        if t.side == "BUY":
            flows[t.symbol].append((_day(t.traded_at), -amount))
            invested[t.symbol] += amount
        else:
            flows[t.symbol].append((_day(t.traded_at), amount))
    for symbol, pos in positions.items():
        flows[symbol].extend(pos.income)

    per: dict[str, dict] = {}
    all_flows: list[Flow] = []
    total_gain = total_in = 0.0
    for symbol, pos in positions.items():
        held_value = value_now.get(symbol)
        open_cost = pos.cost_value
        priced = held_value is not None or pos.quantity <= 1e-9
        unrealized = (held_value - open_cost) if held_value is not None else 0.0
        gain = pos.realized_pnl + unrealized + pos.dividends
        sym_flows = list(flows[symbol]) + ([(today, held_value)] if held_value else [])
        if priced:
            # A holding with no price has no closing value to set against its
            # purchases; counting it would read as money lost. Same rule as the
            # total return above, so XIRR and total return describe the same holdings.
            all_flows.extend(sym_flows)
            total_gain += gain
            total_in += invested[symbol]
        per[symbol] = {
            "invested": invested[symbol],
            "total_return": gain if priced else None,
            "total_return_pct": (gain / invested[symbol]) if priced and invested[symbol] > 0 else None,
            "xirr": xirr(sym_flows) if priced else None,
        }
    portfolio = {
        "invested": total_in,
        "total_return": total_gain,
        "total_return_pct": total_gain / total_in if total_in > 0 else None,
        "xirr": xirr(all_flows),
    }
    return per, portfolio
