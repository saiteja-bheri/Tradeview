"""Reads a broker report (CSV or Excel) into plain rows of text, and finds the
real header row below any preamble (client name, report period, and so on).
Broker parsers then match columns by name, never by position."""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from typing import Iterable


def norm(cell: object) -> str:
    return " ".join(str(cell).replace("﻿", "").strip().strip('"').lower().split())


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


UNREADABLE = "This file could not be read as a CSV or Excel (.xlsx) report"


def open_workbook(content: bytes):
    """openpyxl workbook from bytes; a damaged or non-Excel file is a ValueError
    (shown to the user as a 400), never a server error."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ValueError("Reading Excel reports needs the openpyxl package") from exc
    try:
        return load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # BadZipFile, KeyError, InvalidFileException, XML errors...
        raise ValueError(f"{UNREADABLE}: the Excel file is damaged or not really .xlsx") from exc


def looks_binary(text: str) -> bool:
    """Undecodable bytes or control characters in a sizeable share of the text."""
    sample = text[:4096]
    if not sample:
        return False
    bad = sum(1 for ch in sample if ch == "�" or (ord(ch) < 32 and ch not in "\r\n\t"))
    return bad / len(sample) > 0.05


def read_rows(content: bytes | str) -> list[list[str]]:
    """CSV text or an .xlsx workbook (first sheet) as rows of strings."""
    if isinstance(content, bytes) and content[:2] == b"PK":
        book = open_workbook(content)
        try:
            sheet = book.worksheets[0]
            rows = [[_cell(v) for v in row] for row in sheet.iter_rows(values_only=True)]
        except Exception as exc:
            raise ValueError(f"{UNREADABLE}: {exc.__class__.__name__}") from exc
        finally:
            book.close()
    else:
        text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
        if looks_binary(text):
            raise ValueError(f"{UNREADABLE}: it looks like a binary file")
        try:
            # newline="" lets the csv module handle \r, \n and \r\n line ends itself.
            rows = [[_cell(v) for v in row] for row in csv.reader(io.StringIO(text, newline=""))]
        except csv.Error as exc:
            raise ValueError(f"{UNREADABLE}: {exc}") from exc
    return [r for r in rows if any(c for c in r)]


def find_header(rows: list[list[str]], groups: Iterable[tuple[str, ...]], scan: int = 40) -> int:
    """Index of the first row that has a column from every alias group."""
    groups = list(groups)
    for i, row in enumerate(rows[:scan]):
        cells = {norm(c) for c in row}
        if all(cells & set(g) for g in groups):
            return i
    raise ValueError("Could not find the column headings in this file")


def records(rows: list[list[str]], header: int) -> list[tuple[int, dict[str, str]]]:
    """(1-based line number, {normalised heading: value}) for each data row."""
    names = [norm(c) for c in rows[header]]
    out = []
    for offset, row in enumerate(rows[header + 1:], start=header + 2):
        out.append((offset, {n: (row[i] if i < len(row) else "") for i, n in enumerate(names) if n}))
    return out


def pick(record: dict[str, str], aliases: tuple[str, ...]) -> str:
    for name in aliases:
        value = record.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def number(value: str) -> float:
    return float(str(value).replace(",", "").replace("₹", "").replace("Rs.", "").strip())


def side_of(raw: str) -> str | None:
    s = raw.strip().upper()
    if s.startswith("B"):
        return "BUY"
    if s.startswith("S"):
        return "SELL"
    return None


def fallback_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return f"{prefix}h:" + hashlib.sha1(raw.encode()).hexdigest()[:20]
