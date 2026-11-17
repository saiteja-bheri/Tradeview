"""Writes parsed trades into the ledger. CSV imports and broker syncs both
come through here, so they share one rule for duplicates: a trade id already
in the ledger is never added twice."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Instrument, Trade
from app.ledger.upstox import ParsedTrade
from app.market import symbols


@dataclass
class IngestResult:
    imported: int = 0
    duplicates: int = 0
    updated: int = 0
    skipped: list[str] = field(default_factory=list)   # rows not stored, with the reason


def remember_instrument(session: Session, symbol: str, name: str | None, isin: str = "") -> None:
    known = session.get(Instrument, symbol)
    if known is None:
        scrip, _, suffix = symbol.rpartition(".")
        ns = symbols.namespace(symbol)
        session.add(Instrument(symbol=symbol, name=(name or "").strip(),
                               exchange=ns or ("BSE" if suffix == "BO" else "NSE"),
                               scrip_code=symbol.partition(":")[2] if ns else scrip,
                               isin=(isin or "").upper()))
        session.flush()
        return
    if name and not known.name:
        known.name = name.strip()
    if isin and not known.isin:
        known.isin = isin.upper()


def store_trades(session: Session, trades: list[ParsedTrade]) -> IngestResult:
    existing = {t.trade_id: t for t in session.scalars(select(Trade))}
    result = IngestResult()
    now = datetime.now().replace(microsecond=0)
    today = now.date()
    for t in trades:
        if t.traded_at.date() > today:
            # A date in the future is a typo or a mis-read column (e.g. a settlement or expiry date).
            result.skipped.append(f"{t.symbol} {t.side} {t.quantity:g} on {t.traded_at:%Y-%m-%d}: "
                                  "dated in the future; not imported")
            continue
        known = existing.get(t.trade_id)
        if known is not None:
            # Rows from this app's own export carry their ledger id: apply edits made in the file.
            new = (t.symbol, t.side, t.quantity, t.price, t.traded_at)
            old = (known.symbol, known.side, known.quantity, known.price, known.traded_at)
            if t.from_export and new != old:
                known.symbol, known.side, known.quantity, known.price, known.traded_at = new
                remember_instrument(session, t.symbol, t.name, t.isin)
                result.updated += 1
            else:
                if t.isin:
                    remember_instrument(session, known.symbol, None, t.isin)
                result.duplicates += 1
            continue
        broker = "manual" if t.trade_id.startswith("m:") else t.broker
        row = Trade(broker=broker, trade_id=t.trade_id, symbol=t.symbol, side=t.side,
                    quantity=t.quantity, price=t.price, traded_at=t.traded_at, imported_at=now)
        session.add(row)
        existing[t.trade_id] = row
        remember_instrument(session, t.symbol, t.name, t.isin)
        result.imported += 1
    return result
