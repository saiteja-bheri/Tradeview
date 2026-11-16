"""News sources beyond Yahoo Finance.

The idea comes from newsfilter.io's realtime-newsapi: pull stories from many
outlets into one feed and map each story to the tickers it mentions. Its free
query endpoint now refuses requests, so this uses free, public RSS feeds that
need no key:

  * Google News search, one query per stock (by company name). Google News
    itself aggregates thousands of outlets (Reuters, Bloomberg, Mint, ...).
  * Market wires, one download per feed, every story matched against the names
    and tickers of the stocks you hold, watch or star: Economic Times Markets,
    Livemint Markets, Business Standard Markets, BusinessLine Markets, CNBC-TV18
    Markets, MarketWatch, CNBC. Stories that mention none of your stocks are kept
    as market news (filed under the benchmark), but only from wires in the
    benchmark's region and only the newest few, so they don't crowd out your stocks.
    (Moneycontrol's public RSS stopped updating, so it is not used.)

Every source returns the same item dicts as `news.yahoo_news`:
    {id, title, summary, publisher, url, published_at, source}
All downloads go through `app.brokers.http.get_bytes` (blocked in tests) and
identify the app honestly in the User-Agent."""
from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from app.brokers import http

Getter = Callable[[str], bytes]
HEADERS = {"User-Agent": "QuantTerminal/1.0 (personal portfolio news reader)"}

# id -> (label, region, kind, url). kind "symbol" = one query per stock, "feed" = one download.
SOURCES: dict[str, dict] = {
    "yahoo": {"label": "Yahoo Finance", "region": "Global", "kind": "symbol"},
    "google": {"label": "Google News", "region": "Global", "kind": "symbol"},
    "et": {"label": "Economic Times", "region": "India", "kind": "feed",
           "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    "mint": {"label": "Livemint", "region": "India", "kind": "feed",
             "url": "https://www.livemint.com/rss/markets"},
    "businessline": {"label": "BusinessLine", "region": "India", "kind": "feed",
                     "url": "https://www.thehindubusinessline.com/markets/feeder/default.rss"},
    "cnbctv18": {"label": "CNBC-TV18", "region": "India", "kind": "feed",
                 "url": "https://www.cnbctv18.com/commonfeeds/v1/cne/rss/market.xml"},
    "bs": {"label": "Business Standard", "region": "India", "kind": "feed",
           "url": "https://www.business-standard.com/rss/markets-106.rss"},
    "marketwatch": {"label": "MarketWatch", "region": "US", "kind": "feed",
                    "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    "cnbc": {"label": "CNBC", "region": "US", "kind": "feed",
             "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
}
DEFAULT_ENABLED = list(SOURCES)
MARKET_PER_FEED = 10      # unmatched stories kept as market news, per wire

_INDIA_INDICES = {"^NSEI", "^BSESN", "^NSEBANK", "^CNXIT", "^NSMIDCP", "^CRSLDX", "^CNX100"}
_US_INDICES = {"^GSPC", "^IXIC", "^DJI", "^RUT", "^NDX"}


def region_of(symbol: str) -> str | None:
    """'India', 'US' or None (unknown) for a benchmark symbol."""
    if symbol in _INDIA_INDICES or symbol.endswith((".NS", ".BO")):
        return "India"
    if symbol in _US_INDICES or (not symbol.startswith("^") and "." not in symbol and "=" not in symbol):
        return "US"
    return None

# Google News queries for common benchmarks (other indices get no Google query).
INDEX_QUERIES = {"^NSEI": "Nifty 50", "^BSESN": "Sensex", "^NSEBANK": "Bank Nifty", "^GSPC": "S&P 500",
                 "^IXIC": "Nasdaq Composite", "^DJI": "Dow Jones", "^FTSE": "FTSE 100", "^N225": "Nikkei 225"}

_SUFFIXES = re.compile(r"\b(limited|ltd|inc|incorporated|corp|corporation|plc|co|company|holdings?|group|"
                       r"ag|sa|nv|se|the|and|&)\b\.?", re.I)
_TAGS = re.compile(r"<[^>]+>")


def clean_name(name: str) -> str:
    """'Infosys Limited' -> 'Infosys'; 'Tata Consultancy Services Ltd.' -> 'Tata Consultancy Services'."""
    out = _SUFFIXES.sub(" ", name or "")
    return re.sub(r"[\s.,]+", " ", out).strip()


def base_ticker(symbol: str) -> str:
    return symbol.split(".")[0].lstrip("^").upper()


def _text(el, tag: str) -> str:
    found = el.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _plain(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", html.unescape(raw or "")))).strip()


def _when(raw: str) -> datetime:
    try:
        d = parsedate_to_datetime(raw)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_rss(raw: bytes, source: str, publisher: str = "") -> list[dict]:
    """RSS 2.0 items (and Atom entries) as news item dicts."""
    root = ET.fromstring(raw)
    out = []
    items = root.iter("item")
    for it in items:
        title = _plain(_text(it, "title"))
        if not title:
            continue
        url = _text(it, "link")
        pub = publisher
        src = it.find("source")
        if src is not None and src.text:          # Google News: the outlet that ran it
            pub = src.text.strip()
            suffix = f" - {pub}"
            if title.endswith(suffix):
                title = title[: -len(suffix)]
        summary = _plain(_text(it, "description"))
        if source == "google":
            summary = ""                           # Google's description is just the title again as a link
        guid = _text(it, "guid") or url or title
        out.append({
            "id": f"{source}:{hashlib.sha1(guid.encode()).hexdigest()[:20]}",
            "title": title[:300],
            "summary": summary[:600],
            "publisher": pub,
            "url": url if url.startswith("https://") else "",
            "published_at": _when(_text(it, "pubDate")),
            "source": source,
        })
    return out


def _get(getter: Getter | None, url: str) -> bytes:
    return (getter or (lambda u: http.get_bytes(u, headers=HEADERS, timeout=15)))(url)


def google_query(symbol: str, name: str) -> str | None:
    if symbol in INDEX_QUERIES:
        return f'"{INDEX_QUERIES[symbol]}"'
    if symbol.startswith("^"):
        return None
    cleaned = clean_name(name)
    if cleaned:
        return f'"{cleaned}" (shares OR stock OR results)'
    return f'"{base_ticker(symbol)}" stock'


def google_news(symbol: str, name: str, getter: Getter | None = None) -> list[dict]:
    """Google News search for one stock over the last week, in the stock's own market's edition."""
    q = google_query(symbol, name)
    if not q:
        return []
    india = symbol.endswith((".NS", ".BO")) or symbol in ("^NSEI", "^BSESN", "^NSEBANK")
    hl, gl, ceid = ("en-IN", "IN", "IN:en") if india else ("en-US", "US", "US:en")
    url = (f"https://news.google.com/rss/search?q={urllib.parse.quote(q + ' when:7d')}"
           f"&hl={hl}&gl={gl}&ceid={ceid}")
    return parse_rss(_get(getter, url), "google")


def wire(source: str, getter: Getter | None = None) -> list[dict]:
    """One market wire's latest stories."""
    s = SOURCES[source]
    return parse_rss(_get(getter, s["url"]), source, s["label"])


def matcher(names: dict[str, str]) -> Callable[[str], list[str]]:
    """Returns text -> the symbols it mentions, by company name (case-insensitive,
    whole words) or by bare ticker written in capitals (3+ letters)."""
    rules: list[tuple[str, re.Pattern]] = []
    for sym, name in names.items():
        if sym.startswith("^"):
            continue
        cleaned = clean_name(name)
        pats = []
        if len(cleaned) >= 4:
            pats.append(re.escape(cleaned).replace(r"\ ", r"\s+"))
        tick = base_ticker(sym)
        if len(tick) >= 3 and tick.isalpha():
            rules.append((sym, re.compile(rf"(?<![A-Za-z]){re.escape(tick)}(?![A-Za-z])")))
        if pats:
            rules.append((sym, re.compile(rf"\b(?:{'|'.join(pats)})\b", re.I)))

    def match(text: str) -> list[str]:
        return sorted({sym for sym, rx in rules if rx.search(text)})

    return match
