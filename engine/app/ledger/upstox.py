"""Parser for Upstox trade-book CSV exports.

Columns are matched by name (case-insensitive, with aliases) rather than by
position, and any preamble lines above the header row are skipped, so small
variations between Upstox report versions still import."""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from app.market import symbols

BROKER = "upstox"

ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "trade date"),
    "company": ("company", "scrip name", "symbol name", "name"),
    "exchange": ("exchange",),
    "segment": ("segment",),
    "scrip": ("scrip code", "symbol", "scrip", "trading symbol"),
    "trade_num": ("trade num", "trade number", "trade no", "trade id"),
    "time": ("trade time", "time"),
    "side": ("side", "buy/sell", "trade type", "type"),
    "qty": ("quantity", "qty"),
    "price": ("price", "trade price", "rate"),
    # Written by this app's own export so an edited file updates rows instead of duplicating them.
    "ledger_id": ("ledger id",),
    "source": ("source",),
    "isin": ("isin",),
}
KNOWN_BROKERS = ("upstox", "zerodha", "groww", "manual")
REQUIRED = ("date", "scrip", "side", "qty", "price")
NON_EQUITY_MARKERS = ("FO", "FUT", "OPT", "CD", "COM", "CURR", "MCX")
SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


@dataclass
class ParsedTrade:
    trade_id: str
    symbol: str
    name: str
    exchange: str
    scrip_code: str
    side: str
    quantity: float
    price: float
    traded_at: datetime
    from_export: bool = False
    broker: str = BROKER
    isin: str = ""


@dataclass
class ParseResult:
    trades: list[ParsedTrade] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _norm(cell: str) -> str:
    return str(cell).strip().strip('"').lower()


def _find_header(lines: list[str]) -> int:
    qty, price = ALIASES["qty"], ALIASES["price"]
    for i, line in enumerate(lines):
        cells = [_norm(c) for c in line.split(",")]
        if any(c in qty for c in cells) and any(c in price for c in cells):
            return i
    raise ValueError("Could not find a header row with Quantity and Price columns")


def _num(value: object) -> float:
    return float(str(value).replace(",", "").replace("â‚¹", "").strip())


def to_yahoo_symbol(scrip: str, exchange: str) -> str:
    return symbols.to_yahoo(scrip, exchange)


def parse(content: bytes | str) -> ParseResult:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    lines = [ln for ln in text.splitlines() if ln.strip()]
    start = _find_header(lines)
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), dtype=str, keep_default_na=False)
    df.columns = [_norm(c) for c in df.columns]

    cols: dict[str, str] = {}
    for key, names in ALIASES.items():
        for name in names:
            if name in df.columns:
                cols[key] = name
                break
    missing = [k for k in REQUIRED if k not in cols]
    if missing:
        raise ValueError(f"Upstox CSV is missing required columns: {', '.join(missing)}")

    result = ParseResult()
    for n, row in enumerate(df.to_dict("records"), start=start + 2):
        get = lambda key: str(row.get(cols.get(key, ""), "")).strip()  # noqa: E731
        try:
            segment = get("segment").upper()
            if any(m in segment for m in NON_EQUITY_MARKERS):
                result.skipped.append(f"line {n}: non-equity segment '{segment}'")
                continue
            scrip = get("scrip")
            if not scrip:
                result.skipped.append(f"line {n}: no scrip code")
                continue
            side_raw = get("side").upper()
            if side_raw.startswith("B"):
                side = "BUY"
            elif side_raw.startswith("S"):
                side = "SELL"
            else:
                result.skipped.append(f"line {n}: unknown side '{side_raw}'")
                continue
            stamp = f"{get('date')} {get('time')}".strip()
            traded_at = pd.to_datetime(stamp, dayfirst=True).to_pydatetime()
            qty, price = abs(_num(get("qty"))), _num(get("price"))
            if qty <= 0 or price <= 0:
                result.skipped.append(f"line {n}: zero quantity or price")
                continue
            exchange = get("exchange").upper() or "NSE"
            num = get("trade_num")
            ledger_id = get("ledger_id")
            if ledger_id:
                trade_id = ledger_id
            elif num:
                trade_id = f"{traded_at.date().isoformat()}:{exchange}:{num}"
            else:
                raw = f"{stamp}|{exchange}|{scrip}|{side}|{qty}|{price}|{n}"
                trade_id = "h:" + hashlib.sha1(raw.encode()).hexdigest()[:20]
            source = get("source").lower()
            broker = source if ledger_id and source in KNOWN_BROKERS else BROKER
            result.trades.append(
                ParsedTrade(
                    trade_id=trade_id,
                    symbol=to_yahoo_symbol(scrip, exchange),
                    name=get("company"),
                    exchange=exchange,
                    scrip_code=scrip,
                    side=side,
                    quantity=qty,
                    price=price,
                    traded_at=traded_at,
                    from_export=bool(ledger_id),
                    broker=broker,
                    isin=get("isin").upper(),
                )
            )
        except Exception as exc:  # one bad row must not sink the whole import
            result.skipped.append(f"line {n}: {exc}")
    return result


EXPORT_COLUMNS = ("Date", "Company", "Amount", "Exchange", "Segment", "Scrip Code", "Trade Num",
                  "Trade Time", "Side", "Quantity", "Price", "Source", "Ledger Id")


def export_rows(trades, names: dict[str, str]) -> list[dict]:
    """Ledger trades as rows this parser reads back. `Ledger Id` ties a row to
    its ledger entry, so re-importing an edited export updates in place."""
    rows = []
    for t in trades:
        scrip, _, suffix = t.symbol.rpartition(".")
        exchange = {"NS": "NSE", "BO": "BSE"}.get(suffix, "NSE")
        if symbols.is_international(t.symbol) or symbols.namespace(t.symbol):
            scrip, exchange = t.symbol, "INTL"   # read back unchanged
        parts = t.trade_id.split(":")
        rows.append({
            "Date": t.traded_at.strftime("%d-%m-%Y"),
            "Company": names.get(t.symbol, ""),
            "Amount": f"{t.quantity * t.price:.2f}",
            "Exchange": exchange,
            "Segment": "EQ",
            "Scrip Code": scrip or t.symbol,
            "Trade Num": parts[2] if len(parts) == 3 and t.broker == BROKER else "",
            "Trade Time": t.traded_at.strftime("%H:%M:%S"),
            "Side": "Buy" if t.side == "BUY" else "Sell",
            "Quantity": f"{t.quantity:g}",
            "Price": f"{t.price:.4f}".rstrip("0").rstrip("."),
            "Source": t.broker,
            "Ledger Id": t.trade_id,
        })
    return rows
