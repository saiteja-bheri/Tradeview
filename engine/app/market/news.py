"""News and upcoming events for the stocks you hold, watch or star.

Sources (each can be switched off in the NEWS tab, see news_sources.SOURCES):
  * Yahoo Finance headlines per symbol (and for the benchmark, as market news).
  * Google News search per stock, and market wires (Economic Times, Livemint,
    Moneycontrol, Business Standard, MarketWatch, CNBC) whose stories are
    matched to your stocks by name and ticker.
  * Yahoo Finance calendar: next earnings date with the analyst estimate,
    ex-dividend and dividend payment dates.
  * The app's own records: upcoming corporate actions, bond coupons and
    maturities, and splits or bonuses waiting for your confirmation.

Downloads are kept to a minimum: only held, watched and starred stocks (never
ones that are only in History), headlines refreshed at most every 30 minutes
and calendars every 12 hours, everything else served from the local database."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Bond, CorporateAction, Instrument, NewsItem, Setting, Trade, Watch
from app.ledger.positions import EPS
from app.market import news_sources, symbols
from app.market.news_sources import SOURCES, Getter

NEWS_TTL = timedelta(minutes=30)
EVENTS_TTL = timedelta(hours=12)
KEEP_DAYS = 30            # headlines older than this are dropped
MAX_PER_SYMBOL = 20

NewsFetcher = Callable[[str], list[dict]]
EventFetcher = Callable[[str], dict]


def _parse_time(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc).replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def yahoo_news(symbol: str) -> list[dict]:
    """[{id, title, summary, publisher, url, published_at}] from Yahoo, newest first.
    Handles both the current ('content' wrapper) and the older flat format."""
    import yfinance as yf

    out = []
    for raw in yf.Ticker(symbol).news or []:
        c = raw.get("content") or raw
        title = (c.get("title") or "").strip()
        if not title:
            continue
        url = ((c.get("clickThroughUrl") or {}).get("url") or (c.get("canonicalUrl") or {}).get("url")
               or c.get("link") or "")
        published = _parse_time(c.get("pubDate") or c.get("displayTime") or c.get("providerPublishTime"))
        out.append({
            "source": "yahoo",
            "id": str(raw.get("id") or c.get("id") or c.get("uuid") or url or title)[:120],
            "title": title[:300],
            "summary": (c.get("summary") or c.get("description") or "").strip()[:600],
            "publisher": ((c.get("provider") or {}).get("displayName") or c.get("publisher") or "").strip(),
            "url": url if url.startswith("https://") else "",
            "published_at": published or datetime.now(timezone.utc).replace(tzinfo=None),
        })
    return out


def yahoo_events(symbol: str) -> dict:
    """Yahoo's calendar for one symbol as plain JSON-able values."""
    import yfinance as yf

    cal = yf.Ticker(symbol).calendar or {}
    if not isinstance(cal, dict):
        return {}

    def iso(v):
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v else None)

    return {"earnings": iso(cal.get("Earnings Date")), "earnings_eps_estimate": cal.get("Earnings Average"),
            "ex_dividend": iso(cal.get("Ex-Dividend Date")), "dividend_paid": iso(cal.get("Dividend Date"))}


def covered(session: Session, benchmark: str) -> dict[str, str]:
    """symbol -> why it is covered (held / watched / starred / market)."""
    trades = session.scalars(select(Trade)).all()
    qty: dict[str, float] = {}
    for t in trades:
        qty[t.symbol] = qty.get(t.symbol, 0.0) + (t.quantity if t.side == "BUY" else -t.quantity)
    out = {s: "held" for s, q in qty.items() if q > EPS}
    for w in session.scalars(select(Watch).where(Watch.watched | Watch.starred)):
        out.setdefault(w.symbol, "watched" if w.watched else "starred")
    out.setdefault(benchmark, "market")
    # Yahoo has no headlines for funds, commodities priced here, or hand-entered bonds.
    return {s: why for s, why in out.items() if not symbols.namespace(s)}


def _stale(session: Session, key: str, ttl: timedelta, now: datetime) -> bool:
    row = session.get(Setting, key)
    try:
        return row is None or now - datetime.fromisoformat(row.value.partition("|")[0]) > ttl
    except ValueError:
        return True


def _stamp(session: Session, key: str, now: datetime, payload: str = "") -> None:
    value = now.isoformat(timespec="seconds") + (f"|{payload}" if payload else "")
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


def enabled_sources(session: Session) -> list[str]:
    row = session.get(Setting, "news_sources")
    if row is None:
        return list(news_sources.DEFAULT_ENABLED)
    try:
        return [x for x in json.loads(row.value) if x in SOURCES]
    except ValueError:
        return list(news_sources.DEFAULT_ENABLED)


def set_sources(session: Session, enabled: list[str]) -> list[str]:
    clean = [x for x in SOURCES if x in set(enabled)]
    row = session.get(Setting, "news_sources")
    if row:
        row.value = json.dumps(clean)
    else:
        session.add(Setting(key="news_sources", value=json.dumps(clean)))
    session.commit()
    return clean


def _names(session: Session, syms) -> dict[str, str]:
    syms = list(syms)
    found = {i.symbol: i.name or "" for i in session.scalars(select(Instrument).where(Instrument.symbol.in_(syms)))}
    return {s: found.get(s, "") for s in syms}


def _key(source: str, sym: str) -> str:
    return f"news:{sym}" if source == "yahoo" else f"news:{source}:{sym}"


def refresh(session: Session, wanted: list[str], *, force: bool = False,
            news_fetcher: NewsFetcher | None = None, event_fetcher: EventFetcher | None = None,
            rss_get: Getter | None = None, match_names: dict[str, str] | None = None,
            market_symbol: str | None = None) -> dict:
    """Downloads what is stale only: per-stock sources for `wanted`, each enabled
    market wire once (its stories matched to `match_names`, unmatched ones filed
    under `market_symbol`), and calendars. Returns counts and errors."""
    now = datetime.now()
    enabled = enabled_sources(session)
    names = _names(session, wanted)
    get_events = event_fetcher or yahoo_events
    jobs: list[tuple[str, str, Callable[[], list[dict]]]] = []        # (source, symbol or "", fetch)
    for src in enabled:
        meta = SOURCES[src]
        if meta["kind"] == "symbol":
            for sym in wanted:
                if not (force or _stale(session, _key(src, sym), NEWS_TTL, now)):
                    continue
                if src == "yahoo":
                    fn = (lambda sym=sym: (news_fetcher or yahoo_news)(sym))
                else:
                    fn = (lambda sym=sym: news_sources.google_news(sym, names.get(sym, ""), rss_get))
                jobs.append((src, sym, fn))
        elif force or _stale(session, f"news:feed:{src}", NEWS_TTL, now):
            jobs.append((src, "", lambda src=src: news_sources.wire(src, rss_get)))
    events_due = [s for s in wanted if force or _stale(session, f"events:{s}", EVENTS_TTL, now)]
    errors: list[str] = []

    def safe(fn, label):
        try:
            return fn(), None
        except Exception as exc:  # one source or symbol failing must not stop the rest
            return None, f"{label}: {exc}"

    with ThreadPoolExecutor(max_workers=6) as pool:
        news_results = list(pool.map(
            lambda j: (j, *safe(j[2], f"{SOURCES[j[0]]['label']} {j[1]}".strip())), jobs))
        event_results = list(pool.map(lambda sym: (sym, *safe(lambda: get_events(sym), sym)), events_due))

    match = news_sources.matcher(match_names if match_names is not None else names)
    added = 0

    def store(item: dict, sym: str):
        nonlocal added
        if session.get(NewsItem, (item["id"], sym)) is None:
            session.add(NewsItem(symbol=sym, **{"source": "yahoo", **item}))
            added += 1

    for (src, sym, _), items, err in news_results:
        if err:
            # Tried: wait the usual 30 minutes (or REFRESH) before asking that source again.
            errors.append(err)
            _stamp(session, _key(src, sym) if sym else f"news:feed:{src}", now)
            continue
        if sym:
            for it in (items or [])[:MAX_PER_SYMBOL]:
                store(it, sym)
            _stamp(session, _key(src, sym), now)
        else:
            bench_region = news_sources.region_of(market_symbol) if market_symbol else None
            as_market = bool(market_symbol) and bench_region in (None, SOURCES[src]["region"])
            kept = 0
            for it in sorted(items or [], key=lambda i: i["published_at"], reverse=True):
                hits = match(f"{it['title']} {it['summary']}")
                if not hits and as_market and kept < news_sources.MARKET_PER_FEED:
                    hits, kept = [market_symbol], kept + 1
                for target in hits:
                    store(it, target)
            _stamp(session, f"news:feed:{src}", now)
        session.flush()
    for sym, ev, err in event_results:
        if err:
            errors.append(err)
            continue
        _stamp(session, f"events:{sym}", now, json.dumps(ev or {}, default=str))
    session.execute(delete(NewsItem).where(NewsItem.published_at < now - timedelta(days=KEEP_DAYS)))
    session.commit()
    return {"downloaded_news": len(jobs), "downloaded_events": len(events_due), "new_headlines": added,
            "errors": errors}


def _events(session: Session, wanted: dict[str, str], horizon_days: int) -> list[dict]:
    today = date.today()
    until = today + timedelta(days=horizon_days)
    out: list[dict] = []

    def add(d: str | date | None, sym: str, kind: str, text: str, source: str):
        if not d:
            return
        day = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
        if today - timedelta(days=3) <= day <= until:
            out.append({"date": day.isoformat(), "symbol": sym, "kind": kind, "text": text, "source": source})

    for sym in wanted:
        row = session.get(Setting, f"events:{sym}")
        if not row or "|" not in row.value:
            continue
        ev = json.loads(row.value.partition("|")[2] or "{}")
        est = ev.get("earnings_eps_estimate")
        add(ev.get("earnings"), sym, "earnings",
            "Results due" + (f" · EPS estimate {est:.2f}" if isinstance(est, (int, float)) else ""), "Yahoo")
        add(ev.get("ex_dividend"), sym, "ex_dividend", "Ex-dividend date", "Yahoo")
        add(ev.get("dividend_paid"), sym, "dividend", "Dividend paid", "Yahoo")
    for a in session.scalars(select(CorporateAction).where(CorporateAction.ex_date >= today - timedelta(days=3),
                                                           CorporateAction.ex_date <= until)):
        if a.symbol in wanted or a.source == "coupon":
            label = {"split": f"Split ×{a.value:g}", "bonus": f"Bonus ×{a.value:g}",
                     "dividend": f"Coupon {a.value:g} per bond" if a.source == "coupon" else f"Dividend {a.value:g} per share"}
            add(a.ex_date, a.symbol, "coupon" if a.source == "coupon" else a.kind, label[a.kind], a.source)
    for b in session.scalars(select(Bond).where(Bond.maturity <= until)):
        add(b.maturity, b.symbol, "maturity", f"Bond matures ({b.name or b.symbol})", "bond terms")
    # Open questions are things to do now, so they are dated today and listed first.
    for a in session.scalars(select(CorporateAction).where(CorporateAction.review == "pending")):
        out.append({"date": today.isoformat(), "symbol": a.symbol, "kind": "check",
                    "text": f"Confirm the {a.kind} ×{a.value:g} of {a.ex_date:%d %b %Y} against your uploaded "
                            "trades (CHECK SPLITS)", "source": "ledger"})
    return sorted(out, key=lambda e: (e["date"], e["kind"] != "check", e["symbol"]))


def feed(session: Session, benchmark: str, *, scope: str = "all", symbol: str | None = None,
         refresh_now: bool = True, force: bool = False, limit: int = 120, horizon_days: int = 60,
         news_fetcher: NewsFetcher | None = None, event_fetcher: EventFetcher | None = None,
         rss_get: Getter | None = None, sources: list[str] | None = None) -> dict:
    """Headlines (newest first) and upcoming events for the chosen stocks.
    `sources` narrows what is shown (not what is downloaded)."""
    everything = covered(session, benchmark)
    cover = dict(everything)
    if scope == "portfolio":
        cover = {s: w for s, w in cover.items() if w in ("held", "market")}
    elif scope == "watchlist":
        cover = {s: w for s, w in cover.items() if w in ("watched", "starred")}
    if symbol:
        cover = {symbol: cover.get(symbol, "selected")}
    stats = refresh(session, list(cover), force=force, news_fetcher=news_fetcher, event_fetcher=event_fetcher,
                    rss_get=rss_get, match_names=_names(session, everything),
                    market_symbol=benchmark) if refresh_now else {"errors": []}
    enabled = enabled_sources(session)
    shown = [x for x in (sources or enabled) if x in enabled]
    names = {i.symbol: i.name for i in session.scalars(select(Instrument).where(Instrument.symbol.in_(list(cover))))}
    rows = session.scalars(select(NewsItem).where(NewsItem.symbol.in_(list(cover)))
                           .order_by(NewsItem.published_at.desc())).all()
    counts = {x: 0 for x in SOURCES}
    items, seen = [], {}
    for n in rows:
        # One story about several of your stocks, or carried by several sources, is shown once.
        if n.source not in shown:
            continue
        key = re.sub(r"[^a-z0-9]+", " ", n.title.lower()).strip()
        if key in seen:
            item = seen[key]
            if n.symbol not in item["symbols"]:
                item["symbols"].append(n.symbol)
            if n.source not in item["sources"]:
                item["sources"].append(n.source)
            continue
        if len(items) >= limit:
            continue
        item = {"id": n.id, "symbols": [n.symbol], "title": n.title, "summary": n.summary,
                "publisher": n.publisher or SOURCES.get(n.source, {}).get("label", ""), "url": n.url,
                "published_at": n.published_at.isoformat() + "Z", "source": n.source, "sources": [n.source]}
        seen[key] = item
        items.append(item)
    for it in items:
        for src in it["sources"]:
            counts[src] = counts.get(src, 0) + 1
    last = [session.get(Setting, f"news:{s}") for s in cover] + \
        [session.get(Setting, f"news:feed:{x}") for x in enabled]
    stamps = [r.value.partition("|")[0] for r in last if r]
    return {"items": items, "events": _events(session, cover, horizon_days),
            "covered": [{"symbol": s, "why": w, "name": names.get(s, "")} for s, w in sorted(cover.items())],
            "sources": [{"id": x, "label": m["label"], "region": m["region"], "kind": m["kind"],
                         "enabled": x in enabled, "shown": x in shown, "count": counts.get(x, 0)}
                        for x, m in SOURCES.items()],
            "updated_at": max(stamps) if stamps else None, **stats}
