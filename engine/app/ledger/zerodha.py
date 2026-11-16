"""Parser for the Zerodha Console tradebook (Console > Reports > Tradebook,
equity segment), as CSV or Excel. Its columns are snake_case:
symbol, isin, trade_date, exchange, segment, series, trade_type, auction,
quantity, price, trade_id, order_id, order_execution_time.

Trade ids are written as z:<exchange>:<trade_id>, the same form the Kite API
sync uses, so a trade imported from the file is not added again by a sync."""
from __future__ import annotations

import pandas as pd

from app.ledger import table
from app.ledger.upstox import NON_EQUITY_MARKERS, ParsedTrade, ParseResult
from app.market import symbols

BROKER = "zerodha"

ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "tradingsymbol", "trading symbol"),
    "isin": ("isin",),
    "date": ("trade_date", "trade date", "date"),
    "exchange": ("exchange",),
    "segment": ("segment",),
    "side": ("trade_type", "trade type", "type"),
    "qty": ("quantity", "qty"),
    "price": ("price", "trade price"),
    "trade_id": ("trade_id", "trade id"),
    "time": ("order_execution_time", "execution time", "trade time", "time"),
}
REQUIRED = ("symbol", "date", "side", "qty", "price")


def trade_key(exchange: str, trade_id: str) -> str:
    return f"z:{exchange.upper()}:{trade_id}"


def looks_like(headers: set[str]) -> bool:
    return "trade_type" in headers and ("trade_date" in headers or "order_execution_time" in headers)


def parse(content: bytes | str) -> ParseResult:
    rows = table.read_rows(content)
    header = table.find_header(rows, [ALIASES[k] for k in REQUIRED])
    result = ParseResult()
    for line, rec in table.records(rows, header):
        get = lambda key: table.pick(rec, ALIASES[key])  # noqa: E731
        try:
            segment = get("segment").upper()
            if segment and any(m in segment for m in NON_EQUITY_MARKERS):
                result.skipped.append(f"line {line}: non-equity segment '{segment}'")
                continue
            raw_symbol = get("symbol")
            side = table.side_of(get("side"))
            if not raw_symbol or side is None:
                result.skipped.append(f"line {line}: missing symbol or buy/sell")
                continue
            qty, price = abs(table.number(get("qty"))), table.number(get("price"))
            if qty <= 0 or price <= 0:
                result.skipped.append(f"line {line}: zero quantity or price")
                continue
            exchange = get("exchange").upper() or "NSE"
            stamp = get("time") or get("date")
            traded_at = pd.to_datetime(stamp, dayfirst=not stamp[:4].isdigit()).to_pydatetime()
            traded_at = traded_at.replace(tzinfo=None)
            tid = get("trade_id")
            trade_id = (trade_key(exchange, tid) if tid else
                        table.fallback_id("z:", stamp, exchange, raw_symbol, side, qty, price, line))
            result.trades.append(ParsedTrade(
                trade_id=trade_id, symbol=symbols.to_yahoo(raw_symbol, exchange), name="",
                exchange=exchange, scrip_code=symbols.clean_trading_symbol(raw_symbol), side=side,
                quantity=qty, price=price, traded_at=traded_at, broker=BROKER,
                isin=get("isin").upper(),
            ))
        except Exception as exc:  # one bad row must not sink the whole import
            result.skipped.append(f"line {line}: {exc}")
    return result
