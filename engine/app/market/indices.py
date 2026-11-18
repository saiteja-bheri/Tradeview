"""Index constituents from NSE's own published lists (read-only downloads).

NSE rebalances its indices twice a year, so the lists are fetched rather than
typed in. Each is kept in the data folder for a week; when NSE can't be
reached, the last saved copy is used, however old."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

from app.brokers import http

URLS = {"nifty500": "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"}
MAX_AGE = timedelta(days=7)
MIN_ROWS = 100            # a shorter file is an error page, not the list


def _parse(raw: bytes) -> list[tuple[str, str]]:
    rows = []
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace"))):
        sym = (r.get("Symbol") or "").strip().upper()
        if sym:
            rows.append((f"{sym}.NS", (r.get("Company Name") or "").strip()))
    if len(rows) < MIN_ROWS:
        raise ValueError(f"NSE list has only {len(rows)} rows")
    return rows


def constituents(index: str, cache_dir: Path) -> list[tuple[str, str]]:
    """[(Yahoo symbol, company name)] for an NSE index."""
    cache = Path(cache_dir) / f"{index}_constituents.json"
    saved = None
    try:
        saved = json.loads(cache.read_text())
        if datetime.now() - datetime.fromisoformat(saved["fetched"]) < MAX_AGE:
            return [tuple(r) for r in saved["rows"]]
    except (OSError, ValueError, KeyError):
        saved = None
    try:
        rows = _parse(http.get_bytes(URLS[index], {"Accept": "text/csv"}, timeout=20))
    except Exception:
        if saved:
            return [tuple(r) for r in saved["rows"]]
        raise
    try:
        cache.write_text(json.dumps({"fetched": datetime.now().isoformat(), "rows": rows}))
    except OSError:
        pass
    return rows
