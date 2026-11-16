"""Works out which broker a trade report came from and parses it."""
from __future__ import annotations

import csv
import io

from app.ledger import groww, table, upstox, zerodha
from app.ledger.upstox import ParseResult

PARSERS = {"upstox": upstox.parse, "zerodha": zerodha.parse, "groww": groww.parse}


def detect(content: bytes | str) -> str:
    try:
        rows = table.read_rows(content)
    except Exception:
        return "upstox"
    for row in rows[:40]:
        headers = {table.norm(c) for c in row}
        if zerodha.looks_like(headers):
            return "zerodha"
        if groww.looks_like(headers):
            return "groww"
    return "upstox"  # also reads this app's own export


BROKER_LABELS = {"zerodha": "Zerodha Console tradebook", "groww": "Groww order report",
                 "upstox": "Upstox trade book", "export": "This app's own trade export"}


def broker_of_rows(rows: list[list[str]]) -> str | None:
    """Which broker's report these rows are, judged strictly by its headings, or None
    for anything else (your own holdings file, a template...). Unlike `detect`, this
    never guesses Upstox just because nothing else matched."""
    for row in rows[:40]:
        headers = {table.norm(c) for c in row}
        if "ledger id" in headers and "scrip code" in headers:
            return "export"
        if zerodha.looks_like(headers):
            return "zerodha"
        if groww.looks_like(headers):
            return "groww"
        if "scrip code" in headers and ({"trade num", "segment", "company"} & headers):
            return "upstox"
    return None


def broker_of(content: bytes | str) -> str | None:
    try:
        return broker_of_rows(table.read_rows(content))
    except Exception:
        return None


def parse(content: bytes | str, broker: str = "auto") -> tuple[str, ParseResult]:
    name = detect(content) if broker in ("", "auto") else broker
    if name not in PARSERS:
        raise ValueError(f"Unknown broker '{broker}'. Use one of: auto, {', '.join(PARSERS)}")
    if name == "upstox" and isinstance(content, bytes) and content[:2] == b"PK":
        content = to_csv(content)   # the Upstox parser reads text; Excel is converted first
    return name, PARSERS[name](content)


def to_csv(content: bytes | str) -> str:
    """Any CSV or Excel report as CSV text."""
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(table.read_rows(content))
    return out.getvalue()
