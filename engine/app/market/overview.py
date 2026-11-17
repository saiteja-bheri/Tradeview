"""Markets page data: index levels and their recent path, world indices, and
the day's biggest movers. Read-only: quotes come from Yahoo daily bars.

Quotes are kept in memory for five minutes, so the page can refresh often
without hammering Yahoo. Index histories go through the normal price cache."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Callable

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import config
from app.db.models import Instrument, Watch
from app.ledger.positions import EPS
from app.market import history
from app.quant import service

QuoteFetcher = Callable[[list[str]], dict[str, tuple[float, float]]]
TTL_SECONDS = 300
MOVERS = 5

_CACHE: dict[tuple[str, ...], tuple[float, dict[str, tuple[float, float]]]] = {}


def yahoo_quotes(symbols: list[str]) -> dict[str, tuple[float, float]]:
    """(last, previous close) per symbol from one batched Yahoo request."""
    import yfinance as yf

    raw = yf.download(symbols, period="5d", interval="1d", group_by="ticker",
                      progress=False, threads=True, auto_adjust=False)
    out: dict[str, tuple[float, float]] = {}
    for s in symbols:
        try:
            closes = (raw[s]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]).dropna()
        except KeyError:
            continue
        if len(closes) >= 2:
            out[s] = (float(closes.iloc[-1]), float(closes.iloc[-2]))
    return out


def quotes(symbols: list[str], fetcher: QuoteFetcher | None = None) -> dict[str, tuple[float, float]]:
    """(last, previous close) per symbol, cached for TTL_SECONDS per symbol set.
    Raises whatever the fetcher raises when nothing is cached."""
    key = tuple(sorted(set(symbols)))
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < TTL_SECONDS:
        return hit[1]
    got = (fetcher or yahoo_quotes)(list(key))
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[key] = (now, got)
    return got


def _names(session: Session, syms: list[str]) -> dict[str, str]:
    return {i.symbol: i.name for i in session.scalars(select(Instrument).where(Instrument.symbol.in_(syms)))
            if i.name}


def _mine(session: Session) -> list[str]:
    held = {s for s, p in service.load_positions(session).items() if p.quantity > EPS}
    watched = set(session.scalars(select(Watch.symbol).where(or_(Watch.watched, Watch.starred))))
    return sorted(s for s in held | watched if not s.startswith(("^", "BOND:", "MF:", "CMDTY:")))


def _series(session: Session, symbol: str, window: int, fetcher) -> list[dict]:
    start = date.today() - timedelta(days=int(window * 365 / 252) + 15)
    try:
        history.refresh_symbol(session, symbol, start, fetcher=fetcher, with_actions=False)
    except Exception:
        session.rollback()
    close, _ = history.load_prices(session, [symbol])
    if symbol not in close.columns:
        return []
    closes = close[symbol].dropna().tail(window)
    if closes.empty:
        return []
    base = float(closes.iloc[0])
    return [{"date": d.isoformat(), "pct": float(v) / base - 1} for d, v in closes.items()]


def build(session: Session, universe: str, window: int, *,
          quote_fetcher: QuoteFetcher | None = None, price_fetcher=None) -> dict:
    benchmark = service.get_settings(session)["benchmark"]
    strip = config.INDEX_STRIP + ([benchmark] if benchmark not in config.INDEX_STRIP else [])
    global_syms = [s for s, _, _ in config.GLOBAL_INDICES]
    pool = config.NIFTY50 if universe == "nifty50" else _mine(session)
    names = {**config.BENCHMARK_NAMES, **{s: n for s, n, _ in config.GLOBAL_INDICES}}
    names.update(_names(session, pool + [benchmark]))
    if benchmark not in names:
        names[benchmark] = service.get_settings(session).get("benchmark_name") or benchmark

    empty = {"online": False, "as_of": None, "indexes": [], "global": [],
             "movers": {"universe": universe, "gainers": [], "losers": []}}
    try:
        q = quotes(sorted(set(strip + global_syms + pool)), quote_fetcher)
    except Exception:
        return empty

    def row(symbol: str) -> dict | None:
        if symbol not in q:
            return None
        last, prev = q[symbol]
        return {"symbol": symbol, "name": names.get(symbol, symbol.removesuffix(".NS")),
                "last": last, "change_pct": (last / prev - 1) if prev else None}

    indexes = []
    for s in strip:
        r = row(s)
        if r:
            r["series"] = _series(session, s, window, price_fetcher)
            indexes.append(r)
    regions = {s: region for s, _, region in config.GLOBAL_INDICES}
    global_rows = [dict(r, region=regions[s]) for s in global_syms if (r := row(s))]
    ranked = sorted((r for s in pool if (r := row(s)) and r["change_pct"] is not None),
                    key=lambda r: r["change_pct"], reverse=True)
    gainers = [r for r in ranked if r["change_pct"] >= 0][:MOVERS]
    losers = [r for r in reversed(ranked) if r["change_pct"] < 0][:MOVERS]
    return {"online": True, "as_of": date.today().isoformat(), "indexes": indexes, "global": global_rows,
            "movers": {"universe": universe, "gainers": gainers, "losers": losers}}
