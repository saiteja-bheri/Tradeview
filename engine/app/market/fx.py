"""Currency conversion into rupees for international holdings.

Everything the risk maths and returns see is in INR:
  * a trade is costed at the exchange rate on its trade date,
  * a dividend at the rate on its ex-date,
  * a price on each day at that day's rate,
so a US stock's INR return includes the dollar's move against the rupee, as it
does for an Indian investor. Rates are Yahoo's daily FX closes (USDINR=X,
GBPINR=X...), cached like any other price series. Quotes in minor units
(London pence, GBp) are divided down first."""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Instrument, PriceBar
from app.market import symbols


def currency_of(symbol: str, instruments: dict[str, Instrument] | None = None) -> str:
    inst = (instruments or {}).get(symbol)
    if inst is not None and inst.currency:
        return inst.currency
    return symbols.guess_currency(symbol)


def currencies(session: Session, held: list[str]) -> dict[str, str]:
    instruments = {i.symbol: i for i in session.scalars(select(Instrument).where(Instrument.symbol.in_(held)))}
    return {s: currency_of(s, instruments) for s in held}


def fx_symbols(ccys: dict[str, str]) -> list[str]:
    return sorted({pair[0] for c in ccys.values() if (pair := symbols.fx_pair(c))})


class Rates:
    """INR per one unit of each quote currency, by date."""

    def __init__(self, session: Session, ccys: dict[str, str]):
        self.ccys = ccys
        self.series: dict[str, pd.Series] = {}
        self.missing: set[str] = set()
        for ccy in set(ccys.values()):
            pair = symbols.fx_pair(ccy)
            if pair is None:
                continue
            fx_symbol, divisor = pair
            rows = session.execute(select(PriceBar.date, PriceBar.close)
                                   .where(PriceBar.symbol == fx_symbol).order_by(PriceBar.date)).all()
            if rows:
                s = pd.Series([r.close / divisor for r in rows], index=pd.Index([r.date for r in rows]))
                self.series[ccy] = s[~s.index.duplicated(keep="last")]
            else:
                self.missing.add(ccy)

    def rate(self, symbol: str, on: date | datetime | None = None) -> float | None:
        """Rate for the symbol's currency on a day (the last close on or before it;
        the first known rate for days before the series starts). 1.0 for INR."""
        ccy = self.ccys.get(symbol, "INR")
        if symbols.fx_pair(ccy) is None:
            return 1.0
        s = self.series.get(ccy)
        if s is None or s.empty:
            return None
        if on is None:
            return float(s.iloc[-1])
        d = on.date() if isinstance(on, datetime) else on
        pos = s.index.searchsorted(d, side="right") - 1
        return float(s.iloc[max(pos, 0)])

    def frame(self, symbol: str, index) -> pd.Series | None:
        """Daily rates aligned to a price index (carried forward over FX holidays)."""
        ccy = self.ccys.get(symbol, "INR")
        if symbols.fx_pair(ccy) is None:
            return None
        s = self.series.get(ccy)
        if s is None:
            return None
        full = s.reindex(sorted(set(s.index) | set(index))).ffill().bfill()
        return full.reindex(index)
