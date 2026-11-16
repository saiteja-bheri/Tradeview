"""Importing any trade file by matching its columns to the ledger's fields.

Columns are found by their heading, not their position, so a file can have
its columns in any order. Headings are matched loosely (case, spaces and
punctuation ignored, common synonyms known, near-misses accepted), and when
something cannot be matched the user picks the column in the import dialog.
The preview tells the UI what was found; the import then uses the mapping."""
from __future__ import annotations

import difflib
import re

import pandas as pd

from app.ledger import table
from app.ledger.upstox import ParsedTrade, ParseResult
from app.market import markets, symbols

# field -> (label, required, accepted headings, format help)
FIELDS: dict[str, tuple[str, bool, tuple[str, ...], str]] = {
    "date": ("Date", True, ("date", "trade date", "trade_date", "transaction date", "execution date",
                            "execution date and time", "order date", "settlement date", "dt", "txn date",
                            "transaction dt", "trade dt", "value date"),
             "DD-MM-YYYY or YYYY-MM-DD (a time may follow)"),
    "time": ("Time", False, ("time", "trade time", "execution time", "order_execution_time", "timestamp"),
             "HH:MM or HH:MM:SS, 24-hour"),
    "symbol": ("Symbol", True, ("symbol", "ticker", "scrip", "scrip code", "trading symbol", "tradingsymbol",
                                "stock symbol", "security", "instrument", "code", "nse symbol", "stock"),
               "Exchange ticker: INFY, RELIANCE, AAPL, VOD.L"),
    "exchange": ("Exchange", False, ("exchange", "exch", "market", "listing", "venue"),
                 "NSE, BSE, NASDAQ, NYSE, LSE... Blank means NSE"),
    "side": ("Side", True, ("side", "buy/sell", "buy sell", "type", "trade type", "trade_type", "transaction type",
                            "action", "b/s", "direction"),
             "BUY or SELL (B / S also work)"),
    "quantity": ("Quantity", True, ("quantity", "qty", "shares", "units", "no of shares", "number of shares",
                                    "volume", "filled qty", "executed quantity"),
                 "Number of shares, e.g. 10"),
    "price": ("Price", True, ("price", "rate", "trade price", "avg price", "average price", "executed price",
                              "price per share", "unit price", "cost per share", "px", "trade px", "fill price",
                              "deal price", "net rate"),
              "Price per share in the listing's currency (or give Amount instead)"),
    "amount": ("Amount", False, ("amount", "value", "total", "trade value", "net amount", "consideration",
                                 "total value", "gross amount"),
               "Quantity x price; used when there is no price column"),
    "trade_id": ("Trade ID", False, ("trade id", "trade_id", "trade num", "trade no", "trade number",
                                     "exchange trade id", "order id", "reference", "ref no", "contract no"),
                 "Any unique id; stops the same trade being imported twice"),
    "isin": ("ISIN", False, ("isin", "isin code"), "INE009A01021"),
    "name": ("Name", False, ("name", "company", "company name", "stock name", "security name", "scrip name",
                             "description"), "Company name, for display"),
}
TEMPLATE_HEADINGS = ("Date", "Time", "Symbol", "Exchange", "Side", "Quantity", "Price", "Trade ID", "ISIN", "Name")


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


_ALIAS_KEYS = {f: {_key(a) for a in spec[2]} | {_key(spec[0])} for f, spec in FIELDS.items()}


def match_field(heading: str) -> str | None:
    """Which ledger field a heading most likely holds, or None."""
    k = _key(heading)
    if not k:
        return None
    for f, keys in _ALIAS_KEYS.items():
        if k in keys:
            return f
    best, score = None, 0.0
    for f, keys in _ALIAS_KEYS.items():
        for a in keys:
            r = difflib.SequenceMatcher(None, k, a).ratio()
            if r > score:
                best, score = f, r
    return best if score >= 0.84 else None


def find_header(rows: list[list[str]]) -> int:
    """The first row (of the first 40) where at least three headings match fields."""
    best, best_hits = 0, 0
    for i, row in enumerate(rows[:40]):
        hits = len({match_field(c) for c in row if c and match_field(c)})
        if hits >= 3 and hits > best_hits:
            best, best_hits = i, hits
            if hits >= 5:
                break
    return best


def guess(rows: list[list[str]], header: int | None = None) -> dict:
    header = find_header(rows) if header is None else header
    headings = [c.strip() for c in rows[header]] if rows else []
    mapping: dict[str, str | None] = {f: None for f in FIELDS}
    for h in headings:
        f = match_field(h)
        if f and mapping[f] is None:
            mapping[f] = h
    return {"header_row": header, "headings": headings, "mapping": mapping,
            "samples": [r[:len(headings)] for r in rows[header + 1: header + 6]]}


def missing(mapping: dict[str, str | None]) -> list[str]:
    need = [f for f, spec in FIELDS.items() if spec[1] and not mapping.get(f)]
    if "price" in need and mapping.get("amount"):
        need.remove("price")
    if "side" in need and mapping.get("quantity"):
        need.remove("side")  # signed quantities (negative = sell) are accepted
    return need


_EXCH_SUFFIX = {v: k for k, v in markets.SUFFIX_EXCHANGE.items()}
DERIVATIVE_SEGMENTS = {"NFO", "BFO", "FO", "F&O", "MCX", "CDS", "NCDEX", "COM", "CURRENCY"}
_LABELS = {spec[1]: code for code, spec in markets.EXCHANGES.items()}


def _symbol(raw: str, exchange: str) -> str:
    sym, ex = raw.strip().upper(), exchange.strip().upper()
    if symbols.is_namespaced(sym):
        return sym
    if ex in ("", "NSE", "NSI"):
        return sym if ("." in sym and not ex) else symbols.to_yahoo(sym, "NSE")
    if ex in ("BSE", "BOM"):
        return symbols.to_yahoo(sym, "BSE")
    if "." in sym:
        return sym                                  # already a Yahoo symbol (VOD.L)
    code = _LABELS.get(ex) or (ex if ex in markets.EXCHANGES else None)
    if code is None and ex in ("US", "USA", "INTL", "AMEX", "ARCA"):
        return sym
    if code and markets.EXCHANGES[code][0] == "US":
        return sym
    suffix = _EXCH_SUFFIX.get(code or "")
    return f"{sym}.{suffix}" if suffix else sym


def parse(rows: list[list[str]], mapping: dict[str, str | None], header: int) -> ParseResult:
    headings = [table.norm(h) for h in rows[header]]
    index = {f: headings.index(table.norm(col)) for f, col in mapping.items() if col and table.norm(col) in headings}
    need = missing({f: (mapping.get(f) if f in index else None) for f in FIELDS})
    if need:
        raise ValueError("Missing columns for: " + ", ".join(FIELDS[f][0] for f in need))
    result = ParseResult()
    for n, row in enumerate(rows[header + 1:], start=header + 2):
        get = lambda f: (row[index[f]].strip() if f in index and index[f] < len(row) else "")  # noqa: E731
        try:
            raw_symbol = get("symbol")
            if not raw_symbol:
                result.skipped.append(f"line {n}: no symbol")
                continue
            exch = get("exchange")
            if exch.upper() in DERIVATIVE_SEGMENTS:
                result.skipped.append(f"line {n}: derivatives segment '{exch}'")
                continue
            qty = table.number(get("quantity"))
            side = table.side_of(get("side")) if "side" in index else ("SELL" if qty < 0 else "BUY")
            if side is None:
                result.skipped.append(f"line {n}: unknown buy/sell '{get('side')}'")
                continue
            qty = abs(qty)
            price = table.number(get("price")) if get("price") else (
                abs(table.number(get("amount"))) / qty if get("amount") and qty else 0.0)
            if qty <= 0 or price <= 0:
                result.skipped.append(f"line {n}: zero quantity or price")
                continue
            stamp = f"{get('date')} {get('time')}".strip()
            traded_at = pd.to_datetime(stamp, dayfirst=not stamp[:4].isdigit()).to_pydatetime().replace(tzinfo=None)
            symbol = _symbol(raw_symbol, exch)
            tid = get("trade_id")
            trade_id = (f"x:{(exch or 'NSE').upper()}:{tid}" if tid
                        else table.fallback_id("x:", stamp, symbol, side, qty, price, n))
            result.trades.append(ParsedTrade(
                trade_id=trade_id, symbol=symbol, name=get("name"), exchange=(exch or "NSE").upper(),
                scrip_code=raw_symbol.upper(), side=side, quantity=qty, price=price, traded_at=traded_at,
                broker="manual", isin=get("isin").upper()))
        except Exception as exc:
            result.skipped.append(f"line {n}: {exc}")
    return result


def template_csv() -> str:
    return ("Date,Time,Symbol,Exchange,Side,Quantity,Price,Trade ID,ISIN,Name\n"
            "15-01-2025,10:15:00,INFY,NSE,BUY,10,1850.50,T1001,INE009A01021,Infosys\n"
            "03-02-2025,14:02:00,AAPL,NASDAQ,BUY,5,228.40,T1002,,Apple Inc.\n"
            "20-03-2025,11:30:00,INFY,NSE,SELL,4,1720.00,T1003,INE009A01021,Infosys\n")


BROKER_FORMATS = {
    "upstox": {"label": "Upstox trade book", "file": "CSV or Excel",
               "required": ["Date", "Scrip Code", "Side", "Quantity", "Price"],
               "optional": ["Company", "Exchange", "Segment", "Trade Num", "Trade Time"],
               "where": "Upstox > Reports > Trade book"},
    "zerodha": {"label": "Zerodha Console tradebook", "file": "CSV or Excel",
                "required": ["symbol", "trade_date", "trade_type", "quantity", "price"],
                "optional": ["isin", "exchange", "segment", "series", "trade_id", "order_execution_time"],
                "where": "Console > Reports > Tradebook (equity)"},
    "groww": {"label": "Groww stock order report", "file": "CSV or Excel",
              "required": ["Symbol", "Type", "Quantity", "Price or Value", "Execution date and time"],
              "optional": ["Stock name", "ISIN", "Exchange", "Exchange Order Id", "Order status"],
              "where": "Groww > Stocks > Reports > Order history"},
}


def formats() -> dict:
    return {
        "generic": {"headings": [{"heading": FIELDS[f][0], "required": FIELDS[f][1], "format": FIELDS[f][3]}
                                 for f in ("date", "time", "symbol", "exchange", "side", "quantity", "price",
                                           "amount", "trade_id", "isin", "name")],
                    "notes": ["Columns can be in any order; headings are matched by name.",
                              "Give either Price or Amount. Without a Side column, a negative Quantity means SELL.",
                              "Rows above the headings (report title, client code) are skipped."]},
        "brokers": BROKER_FORMATS,
    }
