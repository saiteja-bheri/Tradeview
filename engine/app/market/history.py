"""Daily price history and corporate actions from Yahoo Finance, cached in SQLite.

Adjusted closes change retroactively whenever a new dividend or split lands,
so a refresh replaces the whole window for a symbol instead of appending."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Bond, CorporateAction, Instrument, PriceBar, Setting
from app.market import symbols

Fetcher = Callable[[str, date], pd.DataFrame]


def fetch(symbol: str, start: date) -> pd.DataFrame:
    """Returns a frame indexed by date with columns close, adj_close, dividend, split."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    raw = ticker.history(start=start.isoformat(), auto_adjust=False, actions=True)
    if raw.empty:
        return pd.DataFrame(columns=["close", "adj_close", "dividend", "split"])
    try:
        currency = (ticker.history_metadata or {}).get("currency") or ""
    except Exception:
        currency = ""
    idx = pd.to_datetime(raw.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = pd.DataFrame(index=idx.date)
    out["close"] = raw["Close"].to_numpy()
    out["adj_close"] = raw["Adj Close"].to_numpy() if "Adj Close" in raw else raw["Close"].to_numpy()
    out["dividend"] = raw["Dividends"].to_numpy() if "Dividends" in raw else 0.0
    out["split"] = raw["Stock Splits"].to_numpy() if "Stock Splits" in raw else 0.0
    out = out.dropna(subset=["close"])
    out.attrs["currency"] = currency  # INR, USD, GBp (London pence), JPY...
    return out


def fetch_any(symbol: str, start: date) -> pd.DataFrame:
    """Routes a symbol to its source: AMFI NAVs for MF:, INR-converted futures
    for CMDTY:, Yahoo for everything else (stocks, ETFs, indices, SGBs)."""
    ns = symbols.namespace(symbol)
    if ns == "MF":
        from app.market import mutual_funds

        return mutual_funds.fetch(symbol, start)
    if ns == "CMDTY":
        from app.market import commodities

        return commodities.fetch(symbol, start)
    return fetch(symbol, start)


def _refresh_bond(session: Session, symbol: str, start: date) -> int:
    """Bonds have no market feed: a flat series at the valuation price, and
    coupons regenerated from the bond's terms as dividend income."""
    from app.market import bonds

    bond = session.get(Bond, symbol)
    if bond is None:
        raise ValueError(f"No terms saved for {symbol}; add them under BONDS")
    frame = bonds.price_frame(bond, start)
    session.execute(delete(PriceBar).where(PriceBar.symbol == symbol))
    session.add_all(PriceBar(symbol=symbol, date=d, close=float(r.close), adj_close=float(r.adj_close))
                    for d, r in frame.iterrows())
    session.execute(delete(CorporateAction).where(CorporateAction.symbol == symbol,
                                                  CorporateAction.source == "coupon"))
    per_bond = bonds.coupon(bond)
    if per_bond > 0:
        for d in bonds.coupon_dates(bond, start, min(date.today(), bond.maturity)):
            session.add(CorporateAction(symbol=symbol, ex_date=d, kind="dividend",
                                        value=per_bond, source="coupon"))
    session.commit()
    return len(frame)


def _bump(session: Session, counter: str) -> None:
    """Counts cache hits and downloads (shown under CACHE) so the saving is visible."""
    key = f"cache:{counter}"
    row = session.get(Setting, key)
    if row:
        row.value = str(int(row.value or 0) + 1)
    else:
        session.add(Setting(key=key, value="1"))


def cached_range(session: Session, symbol: str) -> tuple[date, date] | None:
    lo, hi = session.execute(select(func.min(PriceBar.date), func.max(PriceBar.date))
                             .where(PriceBar.symbol == symbol)).one()
    return (lo, hi) if lo else None


def _store_actions(session: Session, symbol: str, frame: pd.DataFrame, replace: bool) -> None:
    """Yahoo's splits and dividends. A full download rewrites Yahoo's rows (keeping
    the user's split/bonus answers); an incremental one only adds new dates. An
    action from another source (manual, BSE) on the same date always wins."""
    answers = {(a.ex_date, a.kind): a.review for a in session.scalars(
        select(CorporateAction).where(CorporateAction.symbol == symbol, CorporateAction.source == "yfinance"))}
    if replace:
        session.execute(delete(CorporateAction).where(CorporateAction.symbol == symbol,
                                                      CorporateAction.source == "yfinance"))
    known = {(a.ex_date, "factor" if a.kind in ("split", "bonus") else a.kind)
             for a in session.scalars(select(CorporateAction).where(CorporateAction.symbol == symbol))}
    for d, r in frame.iterrows():
        if r.split and r.split > 0 and (d, "factor") not in known:
            session.add(CorporateAction(symbol=symbol, ex_date=d, kind="split", value=float(r.split),
                                        source="yfinance", review=answers.get((d, "split"), "")))
        if r.dividend and r.dividend > 0 and (d, "dividend") not in known:
            session.add(CorporateAction(symbol=symbol, ex_date=d, kind="dividend", value=float(r.dividend),
                                        source="yfinance"))


def _has_new_actions(session: Session, symbol: str, frame: pd.DataFrame) -> bool:
    known = {(a.ex_date, "factor" if a.kind in ("split", "bonus") else a.kind)
             for a in session.scalars(select(CorporateAction).where(CorporateAction.symbol == symbol))}
    for d, r in frame.iterrows():
        if (r.split and r.split > 0 and (d, "factor") not in known) or            (r.dividend and r.dividend > 0 and (d, "dividend") not in known):
            return True
    return False


def refresh_symbol(
    session: Session,
    symbol: str,
    start: date,
    *,
    fetcher: Fetcher | None = None,
    with_actions: bool = True,
    force: bool = False,
) -> int:
    """Brings one symbol's cached daily prices up to date, downloading as little
    as possible:
      * already refreshed today and covering `start`: no download at all;
      * cache covers `start`: download only the last week onward and append;
      * a new split or dividend shows up, the cache is short, or `force`: one full
        download, because Yahoo then restates every adjusted close.
    Returns the number of bars written (0 when served from the cache)."""
    if symbols.namespace(symbol) == "BOND":
        return _refresh_bond(session, symbol, start)  # local and cheap: always current
    key = f"refreshed:{symbol}"
    today = date.today()
    marker = session.get(Setting, key)
    covered = cached_range(session, symbol)
    if marker and covered and not force:
        day, _, marked_start = marker.value.partition("|")
        if day == today.isoformat() and marked_start <= start.isoformat():
            _bump(session, "hits")
            session.commit()
            return 0

    fetch = fetcher or fetch_any
    with_actions = with_actions and symbols.namespace(symbol) is None
    incremental = bool(covered) and not force and covered[0] <= start + timedelta(days=7)
    frame = None
    if incremental:
        frame = fetch(symbol, covered[1] - timedelta(days=7))
        if with_actions and _has_new_actions(session, symbol, frame):
            frame, incremental = None, False      # adjusted closes restated: take it all again
    if frame is None:
        frame = fetch(symbol, start)
        if frame.empty:
            raise ValueError(f"No price data returned for {symbol}")

    currency = frame.attrs.get("currency") if hasattr(frame, "attrs") else None
    if currency:
        inst = session.get(Instrument, symbol)
        if inst is not None and inst.currency != currency:
            inst.currency = currency
        elif inst is None:
            # Benchmarks and other unheld symbols have no instrument row; keep the
            # currency Yahoo reported so a foreign index is converted to rupees.
            # (Own variable name: `key` is the refreshed-stamp key used further down.)
            ccy_key = f"currency:{symbol}"
            ccy_row = session.get(Setting, ccy_key)
            if ccy_row is None:
                session.add(Setting(key=ccy_key, value=currency))
            elif ccy_row.value != currency:
                ccy_row.value = currency

    if incremental:
        if not frame.empty:
            session.execute(delete(PriceBar).where(PriceBar.symbol == symbol,
                                                   PriceBar.date >= min(frame.index)))
        _bump(session, "incremental")
    else:
        session.execute(delete(PriceBar).where(PriceBar.symbol == symbol))
        _bump(session, "downloads")
    session.add_all(
        PriceBar(symbol=symbol, date=d, close=float(r.close), adj_close=float(r.adj_close))
        for d, r in frame.iterrows()
    )
    if with_actions:
        _store_actions(session, symbol, frame, replace=not incremental)
    covered_from = min(start, covered[0]) if incremental else start
    stamp = f"{today.isoformat()}|{covered_from.isoformat()}"
    if marker:
        marker.value = stamp
    else:
        session.add(Setting(key=key, value=stamp))
    session.commit()
    return len(frame)


def load_prices(session: Session, symbols: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (close, adj_close) frames: one column per symbol, indexed by date."""
    rows = session.execute(
        select(PriceBar.symbol, PriceBar.date, PriceBar.close, PriceBar.adj_close).where(
            PriceBar.symbol.in_(symbols)
        )
    ).all()
    if not rows:
        empty = pd.DataFrame()
        return empty, empty
    df = pd.DataFrame(rows, columns=["symbol", "date", "close", "adj_close"])
    close = df.pivot(index="date", columns="symbol", values="close").sort_index()
    adj = df.pivot(index="date", columns="symbol", values="adj_close").sort_index()
    return close, adj
