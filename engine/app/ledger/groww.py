"""Parser for Groww stock trade reports (CSV or the Excel download).

Groww has changed its report layout over time, so columns are found by name
from a generous alias list. A typical file has: Stock name, Symbol, ISIN,
Type (BUY/SELL), Quantity, Value (or Price), Exchange, Exchange Order Id,
Execution date and time, Order status. Rows whose status is not executed are
skipped, and the price is worked out from Value / Quantity when no price column
exists."""
from __future__ import annotations

import pandas as pd

from app.ledger import table
from app.ledger.upstox import ParsedTrade, ParseResult
from app.market import symbols

BROKER = "groww"

ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("stock name", "company name", "company", "scrip name", "name"),
    "symbol": ("symbol", "trading symbol", "nse symbol", "bse symbol", "ticker"),
    "isin": ("isin",),
    "side": ("type", "buy/sell", "transaction type", "trade type", "side"),
    "qty": ("quantity", "qty", "executed quantity"),
    "price": ("price", "avg price", "average price", "trade price", "rate", "executed price"),
    "value": ("value", "amount", "total value", "trade value", "net amount"),
    "exchange": ("exchange",),
    "trade_id": ("exchange trade id", "trade id", "exchange order id"),
    "when": ("execution date and time", "trade date and time", "trade date", "date", "time"),
    "status": ("order status", "status"),
}
DONE = ("executed", "complete", "completed", "traded", "success", "successful", "filled")


def looks_like(headers: set[str]) -> bool:
    return "execution date and time" in headers or ("stock name" in headers and "type" in headers)


def parse(content: bytes | str) -> ParseResult:
    rows = table.read_rows(content)
    header = table.find_header(rows, [ALIASES["side"], ALIASES["qty"], ALIASES["when"]])
    result = ParseResult()
    for line, rec in table.records(rows, header):
        get = lambda key: table.pick(rec, ALIASES[key])  # noqa: E731
        try:
            status = get("status").lower()
            if status and not any(status.startswith(d) for d in DONE):
                result.skipped.append(f"line {line}: status '{status}'")
                continue
            raw_symbol = get("symbol")
            if not raw_symbol:
                result.skipped.append(f"line {line}: no symbol column value")
                continue
            side = table.side_of(get("side"))
            if side is None:
                result.skipped.append(f"line {line}: unknown buy/sell '{get('side')}'")
                continue
            qty = abs(table.number(get("qty")))
            price_raw, value_raw = get("price"), get("value")
            if price_raw:
                price = table.number(price_raw)
            elif value_raw and qty:
                price = abs(table.number(value_raw)) / qty
            else:
                price = 0.0
            if qty <= 0 or price <= 0:
                result.skipped.append(f"line {line}: zero quantity or price")
                continue
            exchange = get("exchange").upper() or "NSE"
            stamp = get("when")
            traded_at = pd.to_datetime(stamp, dayfirst=not stamp[:4].isdigit()).to_pydatetime()
            traded_at = traded_at.replace(tzinfo=None)
            tid = get("trade_id")
            trade_id = (f"g:{exchange}:{tid}" if tid else
                        table.fallback_id("g:", stamp, exchange, raw_symbol, side, qty, price, line))
            result.trades.append(ParsedTrade(
                trade_id=trade_id, symbol=symbols.to_yahoo(raw_symbol, exchange), name=get("name"),
                exchange=exchange, scrip_code=symbols.clean_trading_symbol(raw_symbol), side=side,
                quantity=qty, price=price, traded_at=traded_at, broker=BROKER,
                isin=get("isin").upper(),
            ))
        except Exception as exc:
            result.skipped.append(f"line {line}: {exc}")
    return result
