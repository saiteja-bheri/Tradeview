"""Watchlist, starred stocks, search history, the local price cache and the
portfolio optimiser.

Three separate things:
  * Watchlist (eye icon): stocks you follow. Their daily prices are cached.
  * Starred (star icon): stocks picked for the optimiser. Prices are cached.
  * History: stocks you opened from the search. Only the visit is recorded;
    no prices are downloaded or stored for them.

Prices are downloaded and kept in the local database (ledger.sqlite3) only for
stocks you hold, watch or star. Anything else gets a chart only on request, and
that one-off download is not saved."""
from __future__ import annotations

import asyncio
import csv
import io
from datetime import date, datetime, timedelta
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import config
from app.api.routes import get_session, require_token
from app.db.models import Instrument, PriceBar, Setting, Trade, Watch
from app.ledger import ingest
from app.ledger.positions import EPS
from app.market import fx, history, symbols
from app.quant import optimizer, service

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
HISTORY_LIMIT = 200


def _symbol(raw: str) -> str:
    s = raw.strip().upper()
    if symbols.namespace(s) == "BOND":
        raise HTTPException(status_code=400, detail="Bonds have no market prices to track")
    if not (symbols.is_indian(s) or symbols.is_international(s) or symbols.is_namespaced(s)
            or s.startswith("^")):
        raise HTTPException(status_code=400, detail=f"'{raw}' is not a symbol the app can price")
    return s


def _cache(session: Session, symbol: str, days: int, fetcher=None) -> str | None:
    """Makes sure `days` of history are cached. Returns a warning, or None."""
    start = date.today() - timedelta(days=days)
    try:
        history.refresh_symbol(session, symbol, start, fetcher=fetcher,
                               with_actions=not symbol.startswith("^"))
        ccy = fx.currencies(session, [symbol])
        for pair in fx.fx_symbols(ccy):
            history.refresh_symbol(session, pair, start, fetcher=fetcher, with_actions=False)
        return None
    except Exception as exc:
        session.rollback()
        return f"Could not refresh {symbol}: {exc}"


def tracked(session: Session, symbol: str) -> bool:
    """Prices are kept for this symbol: it is held or traded, watched, starred, or the benchmark."""
    if session.scalar(select(Trade.id).where(Trade.symbol == symbol).limit(1)):
        return True
    w = session.get(Watch, symbol)
    if w is not None and (w.watched or w.starred):
        return True
    return symbol == service.get_settings(session)["benchmark"]


# ---------------------------------------------------------------- watchlist, stars, history

class MarkIn(BaseModel):
    starred: bool | None = None
    watched: bool | None = None
    name: str | None = Field(default=None, max_length=120)


class ViewIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    exchange: str | None = Field(default=None, max_length=20)


def _row(session: Session, w: Watch, held: set[str]) -> dict:
    inst = session.get(Instrument, w.symbol)
    bars = session.scalars(select(PriceBar).where(PriceBar.symbol == w.symbol)
                           .order_by(PriceBar.date.desc()).limit(2)).all()
    count = session.scalar(select(func.count()).where(PriceBar.symbol == w.symbol))
    last, prev = (bars[0].close if bars else None), (bars[1].close if len(bars) > 1 else None)
    return {
        "symbol": w.symbol, "starred": w.starred, "watched": w.watched, "name": inst.name if inst else "",
        "asset_class": (inst.asset_class if inst and inst.asset_class
                        else symbols.asset_class(w.symbol, inst.name if inst else "")),
        "currency": fx.currency_of(w.symbol, {w.symbol: inst} if inst else None),
        "exchange": inst.exchange if inst else "",
        "last": last, "as_of": bars[0].date.isoformat() if bars else None,
        "change_pct": (last / prev - 1) if last and prev else None,
        "cached_bars": count, "held": w.symbol in held,
        "viewed_at": w.viewed_at.isoformat() if w.viewed_at else None,
    }


def _held(session: Session) -> set[str]:
    return {s for s, p in service.load_positions(session).items() if p.quantity > EPS}


def _watch_rows(session: Session) -> list[dict]:
    """Watched and starred stocks (not the search history)."""
    rows = session.scalars(select(Watch).where(or_(Watch.watched, Watch.starred))
                           .order_by(Watch.watched.desc(), Watch.starred.desc(), Watch.added_at.desc())).all()
    held = _held(session)
    return [_row(session, w, held) for w in rows]


def _history_rows(session: Session) -> list[dict]:
    rows = session.scalars(select(Watch).where(Watch.viewed_at.is_not(None))
                           .order_by(Watch.viewed_at.desc()).limit(HISTORY_LIMIT)).all()
    held = _held(session)
    return [_row(session, w, held) for w in rows]


@router.get("/watchlist")
def watchlist(session: Session = Depends(get_session)):
    return _watch_rows(session)


@router.get("/history")
def search_history(session: Session = Depends(get_session)):
    """Stocks opened from the search, newest first. Nothing is downloaded for them."""
    return _history_rows(session)


@router.delete("/history")
def clear_history(session: Session = Depends(get_session)):
    """Forgets the visits. Watched and starred stocks stay on their lists."""
    for w in session.scalars(select(Watch).where(Watch.viewed_at.is_not(None))):
        if w.watched or w.starred:
            w.viewed_at = None
        else:
            session.delete(w)
    session.commit()
    return []


@router.delete("/history/{symbol}")
def forget_visit(symbol: str, session: Session = Depends(get_session)):
    w = session.get(Watch, symbol.strip().upper())
    if w is not None:
        if w.watched or w.starred:
            w.viewed_at = None
        else:
            session.delete(w)
        session.commit()
    return _history_rows(session)


def _upsert(session: Session, symbol: str, name: str | None, *, star: bool | None = None,
            watch: bool | None = None, viewed: bool = False, exchange: str | None = None) -> Watch:
    now = datetime.now().replace(microsecond=0)
    w = session.get(Watch, symbol) or Watch(symbol=symbol, starred=False, watched=False, added_at=now)
    if star is not None:
        w.starred = star
    if watch is not None:
        w.watched = watch
    if viewed:
        w.viewed_at = now
    session.merge(w)
    if not symbol.startswith("^"):
        ingest.remember_instrument(session, symbol, name)
        inst = session.get(Instrument, symbol)
        if inst is not None and exchange and symbols.is_international(symbol):
            inst.exchange = exchange.upper()[:20]   # NASDAQ / NYSE..., used for the chart
    session.commit()
    return w


@router.put("/watchlist/{symbol}")
async def mark(symbol: str, body: MarkIn, request: Request):
    """Watches or stars a stock (or undoes it). Watching or starring caches its
    price history; undoing both stops further downloads (cached bars are kept)."""
    symbol = _symbol(symbol)
    fetcher = getattr(request.app.state, "price_fetcher", None)
    if body.starred is None and body.watched is None:
        body.starred = True   # older clients sent {starred: true} only

    def run() -> dict:
        with request.app.state.sessionmaker() as s:
            w = _upsert(s, symbol, body.name, star=body.starred, watch=body.watched)
            warning = _cache(s, symbol, 3 * 365, fetcher) if (w.starred or w.watched) else None
            return {"watchlist": _watch_rows(s), "warning": warning}

    return await asyncio.to_thread(run)


@router.post("/watchlist/{symbol}/view")
def viewed(symbol: str, body: ViewIn, session: Session = Depends(get_session)):
    """Records that a stock was opened (the History tab). Downloads nothing."""
    symbol = _symbol(symbol)
    _upsert(session, symbol, body.name, viewed=True, exchange=body.exchange)
    return {"symbol": symbol, "tracked": tracked(session, symbol)}


@router.delete("/watchlist/{symbol}")
def forget(symbol: str, session: Session = Depends(get_session)):
    """Takes a stock off the watchlist and the starred list (keeps it in History)."""
    w = session.get(Watch, symbol.strip().upper())
    if w is None:
        raise HTTPException(status_code=404, detail="Not on the watchlist")
    if w.viewed_at:
        w.watched = w.starred = False
    else:
        session.delete(w)
    session.commit()
    return _watch_rows(session)


# ---------------------------------------------------------------- prices

def _bars_json(bars) -> list[dict]:
    return [{"date": b.date.isoformat(), "close": b.close, "adj_close": b.adj_close} for b in bars]


@router.get("/prices/{symbol}")
async def prices(symbol: str, request: Request, days: int = Query(365, ge=5, le=3660),
                 fetch: bool = Query(False, description="Untracked symbols: download once for this chart, without saving")):
    """Daily closes for a chart.

    Held, watched and starred stocks (and the benchmark) are served from the
    local cache, which downloads only the missing days. Any other stock is
    served from whatever happens to be cached; with `fetch=true` it is
    downloaded once for display and not stored, so no cache space is used."""
    symbol = _symbol(symbol)
    fetcher = getattr(request.app.state, "price_fetcher", None)

    def run() -> dict:
        with request.app.state.sessionmaker() as s:
            ccy = fx.currencies(s, [symbol])[symbol]
            since = date.today() - timedelta(days=days)
            keep = tracked(s, symbol)
            warning = _cache(s, symbol, days, fetcher) if keep else None
            bars = s.scalars(select(PriceBar).where(PriceBar.symbol == symbol, PriceBar.date >= since)
                             .order_by(PriceBar.date)).all()
            out = {"symbol": symbol, "currency": ccy, "warning": warning, "tracked": keep, "saved": keep,
                   "bars": _bars_json(bars)}
            if not keep and not bars and fetch:
                try:
                    frame = (fetcher or history.fetch_any)(symbol, since)
                except Exception as exc:
                    out["warning"] = f"Could not load {symbol}: {exc}"
                    return out
                out["currency"] = frame.attrs.get("currency") or ccy
                out["bars"] = [{"date": d.isoformat(), "close": float(r.close), "adj_close": float(r.adj_close)}
                               for d, r in frame.iterrows()]
                out["saved"] = False
            return out

    return await asyncio.to_thread(run)


@router.get("/prices/{symbol}/csv")
def prices_csv(symbol: str, session: Session = Depends(get_session)):
    """The cached history of one symbol as a CSV file (no download from Yahoo)."""
    symbol = symbol.strip().upper()
    bars = session.scalars(select(PriceBar).where(PriceBar.symbol == symbol).order_by(PriceBar.date)).all()
    if not bars:
        raise HTTPException(status_code=404, detail="Nothing cached for this symbol yet")
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["date", "close", "adj_close"])
    w.writerows([b.date.isoformat(), b.close, b.adj_close] for b in bars)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in symbol)
    return Response(content=out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{safe}-prices.csv"'})


@router.get("/cache")
def cache_status(session: Session = Depends(get_session)):
    """What is stored locally, and how many downloads the cache has saved."""
    rows = session.execute(select(PriceBar.symbol, func.count(), func.min(PriceBar.date), func.max(PriceBar.date))
                           .group_by(PriceBar.symbol)).all()
    marks = {s.key.split(":", 1)[1]: s.value.partition("|")[0]
             for s in session.scalars(select(Setting).where(Setting.key.like("refreshed:%")))}
    counters = {s.key.split(":", 1)[1]: int(s.value or 0)
                for s in session.scalars(select(Setting).where(Setting.key.like("cache:%")))}
    starred = {w.symbol for w in session.scalars(select(Watch).where(Watch.starred))}
    watched = {w.symbol for w in session.scalars(select(Watch).where(Watch.watched))}
    traded = set(session.scalars(select(Trade.symbol).distinct()))
    return {
        "database": config.database_url().removeprefix("sqlite:///"),
        "symbols": [{"symbol": s, "bars": n, "first": lo.isoformat(), "last": hi.isoformat(),
                     "refreshed": marks.get(s), "starred": s in starred, "watched": s in watched,
                     "traded": s in traded}
                    for s, n, lo, hi in sorted(rows)],
        "bars": sum(n for _, n, _, _ in rows),
        "served_from_cache": counters.get("hits", 0),
        "incremental_updates": counters.get("incremental", 0),
        "full_downloads": counters.get("downloads", 0),
    }


# ---------------------------------------------------------------- optimiser

class OptimiseIn(BaseModel):
    scope: Literal["portfolio", "starred", "both"] = Field(
        default="portfolio", description="portfolio = current holdings (default); starred = starred stocks; both")
    symbols: list[str] | None = Field(default=None, description="An explicit list; overrides scope")
    include_holdings: bool = Field(default=False, description="Deprecated: same as scope=both")
    lookback_days: int = Field(default=504, ge=60, le=1260)
    max_weight: float = Field(default=0.35, gt=0, le=1)


@router.post("/optimizer")
async def optimise(body: OptimiseIn, request: Request):
    fetcher = getattr(request.app.state, "price_fetcher", None)

    def run() -> dict:
        with request.app.state.sessionmaker() as s:
            return run_optimiser(s, body, fetcher)

    return await asyncio.to_thread(run)


def run_optimiser(session: Session, body: OptimiseIn, fetcher=None) -> dict:
    """Optimises the whole portfolio unless told otherwise: the holdings by
    default, the starred stocks, both, or an explicit list of symbols."""
    warnings: list[str] = []
    positions = service.load_positions(session)
    held = {sym: p for sym, p in positions.items() if p.quantity > EPS}
    scope = "both" if body.include_holdings and body.scope == "starred" else body.scope
    holdings = [h for h in held if symbols.namespace(h) != "BOND"]
    starred = list(session.scalars(select(Watch.symbol).where(Watch.starred)))
    if body.symbols:
        wanted, scope = [x.strip().upper() for x in body.symbols], "custom"
    elif scope == "starred":
        wanted = starred
    elif scope == "both":
        wanted = holdings + starred
    else:
        wanted = holdings
    wanted = list(dict.fromkeys(w for w in wanted if not w.startswith("BOND:")))
    if len(wanted) < 2:
        need = {"portfolio": "Hold at least two stocks (or optimise the starred list)",
                "starred": "Star at least two stocks", "both": "Hold or star at least two stocks",
                "custom": "Give at least two symbols"}[scope]
        raise HTTPException(status_code=400, detail=need)
    if any(h.startswith("BOND:") for h in held) and scope in ("portfolio", "both"):
        warnings.append("Bonds are left out: their price is set by hand, so they have no market risk to optimise")

    calendar_days = int(body.lookback_days * 1.5) + 14
    for sym in wanted:
        w = _cache(session, sym, calendar_days, fetcher)
        if w:
            warnings.append(w)
    _, adj = history.load_prices(session, wanted)
    ccys = fx.currencies(session, wanted)
    rates = fx.Rates(session, ccys)
    usable = []
    for sym in wanted:
        if sym not in adj.columns or adj[sym].notna().sum() < 60:
            warnings.append(f"Not enough price history for {sym}; left out")
            continue
        r = rates.frame(sym, adj.index)
        if symbols.fx_pair(ccys.get(sym, "INR")) and r is None:
            warnings.append(f"No {ccys[sym]}/INR rate for {sym}; left out")
            continue
        if r is not None:
            adj[sym] = adj[sym] * r
        usable.append(sym)
    if len(usable) < 2:
        raise HTTPException(status_code=409, detail="Need price history for at least two of the stocks")
    rets = adj[usable].ffill(limit=5).pct_change(fill_method=None).dropna(how="any").tail(body.lookback_days)
    if len(rets) < 60:
        raise HTTPException(status_code=409, detail=f"Only {len(rets)} overlapping days of returns; need 60")

    rf = float(service.get_settings(session)["risk_free_rate"])
    current = None
    in_both = [sym for sym in usable if sym in held]
    if in_both:
        last = {sym: float(adj[sym].dropna().iloc[-1]) for sym in in_both}
        current = {sym: held[sym].quantity * last[sym] for sym in in_both}
        if len(in_both) < len(usable):
            warnings.append("CURRENT compares only the stocks you hold among these")
    result = optimizer.optimise(rets.to_numpy(), usable, rf, body.max_weight, current)
    names = {i.symbol: i.name for i in session.scalars(select(Instrument).where(Instrument.symbol.in_(usable)))}
    for a in result["assets"]:
        a["name"] = names.get(a["symbol"], "")
        a["held"] = a["symbol"] in held
    if result["max_weight"] > body.max_weight:
        warnings.append(f"Cap raised to {result['max_weight']:.0%}: {len(usable)} stocks cannot be fully "
                        f"invested at {body.max_weight:.0%} each")
    result.update({"scope": scope, "symbols": usable, "observations": len(rets),
                   "from": rets.index.min().isoformat(), "to": rets.index.max().isoformat(),
                   "risk_free_rate": rf, "warnings": warnings})
    return _clean(result)


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, float | np.floating):
        v = float(obj)
        return v if np.isfinite(v) else None
    return obj
