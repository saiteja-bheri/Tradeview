"""Stock search by company name or ticker.

Sources merged: instruments already in the local ledger (instant, works
offline), Yahoo's symbol search (stocks and ETFs on any exchange, each tagged
with its market and currency), AMFI mutual funds and commodities. Secondary
cross-listings of a foreign company (the same name on several exchanges) are
folded into the first, which Yahoo ranks as the primary listing. A Yahoo
failure is not an error: the caller still gets the local matches.
"""
from __future__ import annotations

import time
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BENCHMARK_PRESETS
from app.db.models import Instrument
from app.market import commodities, markets, mutual_funds, symbols

Lookup = Callable[[str, int], list[dict]]

_SUFFIX = {".NS": "NSE", ".BO": "BSE"}
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_SECONDS = 600
_CACHE_SIZE = 256


def yahoo_lookup(query: str, limit: int) -> list[dict]:
    """Raw quote rows from Yahoo's search. Imported lazily; needs the network."""
    import yfinance as yf

    found = yf.Search(query, max_results=limit, news_count=0, enable_fuzzy_query=True, timeout=5)
    return list(found.quotes or [])


def _exchange(symbol: str) -> str | None:
    return _SUFFIX.get(symbol[-3:].upper()) if len(symbol) > 3 else None


def _normalise(rows: list[dict]) -> list[dict]:
    out, seen_foreign = [], set()
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        exchange = _exchange(symbol)
        kind = str(row.get("quoteType") or "EQUITY").upper()
        if kind not in ("EQUITY", "ETF"):
            continue
        if exchange is None and not symbols.is_international(symbol):
            continue
        name = str(row.get("longname") or row.get("shortname") or "").strip()
        info = markets.describe(symbol, str(row.get("exchange") or ""), str(row.get("exchDisp") or ""))
        if info["exchange"] == "OTC":
            continue  # US over-the-counter copies of foreign shares: not the real listing
        if exchange is None:
            key = (name.lower(), info["market"])
            if name and key in seen_foreign:
                continue  # same company again on another exchange in that market
            seen_foreign.add(key)
        out.append({"symbol": symbol, "name": name, "held": False,
                    "asset_class": symbols.asset_class(symbol, name, kind), **info})
    return out


def _raw(query: str, limit: int, lookup: Lookup) -> list[dict]:
    """Yahoo's rows for a query, cached for a few minutes."""
    key = query.lower()
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    # Yahoo ranks global listings first, so ask for more than we show and filter.
    rows = lookup(query, max(limit * 3, 25))
    if len(_CACHE) >= _CACHE_SIZE:
        _CACHE.clear()
    _CACHE[key] = (time.monotonic(), rows)
    return rows


def _remote(query: str, limit: int, lookup: Lookup) -> list[dict]:
    return _normalise(_raw(query, limit, lookup))


def _rank(query: str, item: dict) -> tuple:
    q = query.lower()
    sym = item["symbol"]
    ticker = (sym.partition(":")[2] if ":" in sym else sym.rpartition(".")[0] or sym).lower()
    name = item["name"].lower()
    if ticker == q:
        tier = 0
    elif ticker.startswith(q):
        tier = 1
    elif name.startswith(q) or any(word.startswith(q) for word in name.split()):
        tier = 2
    else:
        tier = 3
    # held first within a tier, then Indian listings (NSE before BSE), then international
    indian = symbols.is_indian(sym) or ":" in sym
    return (tier, not item["held"], not indian, item["exchange"] != "NSE")


def search(session: Session, query: str, limit: int = 10, lookup: Lookup | None = None,
           fund_lookup: Callable[[str, int], list[dict]] | None = None, market: str = "ALL") -> dict:
    """Stocks and ETFs (ledger + Yahoo), mutual funds (AMFI via mfapi.in) and commodities."""
    query = " ".join(query.split())
    if not query:
        return {"query": query, "results": [], "online": True}

    like = f"%{query.replace('%', '').replace('_', '')}%"
    local = session.scalars(
        select(Instrument).where(Instrument.symbol.ilike(like) | Instrument.name.ilike(like))
    ).all()
    merged: dict[str, dict] = {
        i.symbol: {"symbol": i.symbol, "name": i.name or "", "held": True,
                   "asset_class": i.asset_class or symbols.asset_class(i.symbol, i.name or ""),
                   **markets.describe(i.symbol)}
        for i in local
    }
    for i in local:
        if i.currency:  # what Yahoo reported beats the guess from the suffix
            merged[i.symbol]["currency"] = i.currency
    for item in commodities.search(query):
        merged.setdefault(item["symbol"], {**item, **markets.describe(item["symbol"])})

    online = True
    try:
        remote = _remote(query, limit, lookup or yahoo_lookup)
    except Exception:  # offline, rate-limited or a changed response: local results still stand
        remote, online = [], False
    for item in remote:
        known = merged.get(item["symbol"])
        if known is None:
            merged[item["symbol"]] = dict(item)
        elif not known["name"]:
            known["name"] = item["name"]

    # stable sort keeps Yahoo's own relevance order inside each tier
    stocks = sorted(merged.values(), key=lambda item: _rank(query, item))
    if market not in ("", "ALL"):
        stocks = [x for x in stocks if x.get("market") == market]
    # Funds go after listed instruments, a few at most, so a stock search stays a stock search.
    funds: list[dict] = []
    if len(query) >= 3 and market in ("", "ALL", "FUNDS", "INDIA"):
        try:
            funds = [{**f, **markets.describe(f["symbol"])}
                     for f in (fund_lookup or mutual_funds.search)(query, 5) if f["symbol"] not in merged]
        except Exception:
            online = online and bool(stocks)
    room = max(limit - len(funds), limit // 2)
    results = stocks[:room] + funds[:limit - min(room, len(stocks))]
    return {"query": query, "results": results[:limit], "online": online}


_KINDS = {"INDEX": "INDEX", "ETF": "ETF", "MUTUALFUND": "FUND", "EQUITY": "STOCK"}
_INDIAN = ("NSI", "BSE", "NSE", "BOM")


def search_benchmarks(query: str, limit: int = 12, lookup: Lookup | None = None) -> dict:
    """Benchmark candidates: the built-in list filtered by the query, then
    anything Yahoo finds (indices, ETFs, mutual funds, stocks), Indian listings first."""
    query = " ".join(query.split())
    words = query.lower().split()
    presets = [
        {"symbol": symbol, "name": name, "kind": kind, "exchange": "", "preset": True}
        for symbol, name, kind in BENCHMARK_PRESETS
        if all(w in f"{name} {symbol}".lower() for w in words)
    ]
    if not query:
        return {"query": query, "results": presets, "online": True}

    online, found = True, []
    try:
        rows = _raw(query, limit, lookup or yahoo_lookup)
    except Exception:
        rows, online = [], False
    seen = {p["symbol"] for p in presets}
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        kind = _KINDS.get(str(row.get("quoteType") or "").upper())
        if not symbol or kind is None or symbol in seen:
            continue
        seen.add(symbol)
        exchange = str(row.get("exchange") or "").upper()
        indian = exchange in _INDIAN or symbol.endswith((".NS", ".BO"))
        found.append({
            "symbol": symbol,
            "name": str(row.get("longname") or row.get("shortname") or symbol).strip(),
            "kind": kind,
            "exchange": _exchange(symbol) or str(row.get("exchDisp") or exchange),
            "preset": False,
            "_rank": (not indian, kind == "STOCK"),
        })
    found.sort(key=lambda item: item.pop("_rank"))
    return {"query": query, "results": (presets + found)[:limit], "online": online}
