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
