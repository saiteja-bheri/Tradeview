"""Bonds tracked by hand (symbol BOND:<ID>): government securities, corporate
bonds, NCDs, tax-free bonds, and so on.

There is no free, reliable daily price source for most Indian bonds, so a bond
is valued at the price you set (face value by default) and its coupons are
generated from its terms and booked as income on each payment date, exactly
like dividends. Record a purchase as a BUY of N bonds at the price you paid
and the redemption at maturity as a SELL at face value.

Because the price only moves when you change it, a bond adds income and value
but almost no volatility to the risk metrics. That is a fair picture for a bond
held to maturity, and understates risk for one you might sell early."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from dateutil.relativedelta import relativedelta

from app.db.models import Bond


def coupon(bond: Bond) -> float:
    """Cash per bond per coupon."""
    if not bond.frequency:
        return 0.0
    return bond.face_value * bond.coupon_rate / 100 / bond.frequency


def coupon_dates(bond: Bond, start: date, end: date) -> list[date]:
    """Payment dates in [start, end], stepping back from maturity."""
    if not bond.frequency or bond.coupon_rate <= 0:
        return []
    step = relativedelta(months=12 // bond.frequency)
    out, d = [], bond.maturity
    while d >= start:
        if d <= end:
            out.append(d)
        d = d - step
    return sorted(out)


def price_frame(bond: Bond, start: date, today: date | None = None) -> pd.DataFrame:
    """A flat daily series at the valuation price, up to maturity, in the fetcher's shape."""
    today = today or date.today()
    end = min(today, bond.maturity)
    if end < start:
        start = end - timedelta(days=7)
    days = pd.bdate_range(start, end).date
    price = bond.price if bond.price > 0 else bond.face_value
    frame = pd.DataFrame({"close": price, "adj_close": price, "dividend": 0.0, "split": 0.0}, index=days)
    return frame
