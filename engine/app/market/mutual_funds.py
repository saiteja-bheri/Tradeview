"""Indian mutual funds by AMFI scheme code (symbol MF:<code>).

NAVs are AMFI's official daily NAVs, served with full history by the free
mfapi.in service (https://api.mfapi.in/mf/<code>). NAV is the price: a fund
unit has no separate adjusted close, and growth plans pay no dividends, so
returns come straight from the NAV series. IDCW (dividend) plans should have
their payouts entered as corporate actions."""
from __future__ import annotations

import json
import urllib.parse
from datetime import date, datetime

import pandas as pd

from app.brokers import http

API = "https://api.mfapi.in/mf"


def code_of(symbol: str) -> str:
    return symbol.partition(":")[2]


def _get(url: str) -> object:
    return json.loads(http.get_bytes(url, {"Accept": "application/json"}, timeout=30))


def scheme(code: str) -> dict:
    """{meta, data:[{date: 'dd-mm-yyyy', nav: '12.3400'}, ...]} newest first."""
    body = _get(f"{API}/{code}")
    if not isinstance(body, dict) or not body.get("data"):
        raise ValueError(f"No NAV history for scheme {code}")
    return body


def fetch(symbol: str, start: date) -> pd.DataFrame:
    """Same shape as the Yahoo fetcher: close, adj_close, dividend, split."""
    body = scheme(code_of(symbol))
    rows = []
    for point in body["data"]:
        try:
            d = datetime.strptime(point["date"], "%d-%m-%Y").date()
            nav = float(point["nav"])
        except (KeyError, ValueError, TypeError):
            continue
        if d >= start and nav > 0:
            rows.append((d, nav))
    frame = pd.DataFrame(rows, columns=["date", "close"]).drop_duplicates("date").set_index("date").sort_index()
    frame["adj_close"] = frame["close"]
    frame["dividend"] = 0.0
    frame["split"] = 0.0
    return frame


def info(symbol: str) -> dict:
    meta = scheme(code_of(symbol)).get("meta") or {}
    return {"name": meta.get("scheme_name") or "", "isin": meta.get("isin_growth") or "",
            "category": meta.get("scheme_category") or "", "house": meta.get("fund_house") or ""}


def search(query: str, limit: int = 8) -> list[dict]:
    rows = _get(f"{API}/search?{urllib.parse.urlencode({'q': query})}")
    out = []
    for row in rows if isinstance(rows, list) else []:
        code = str(row.get("schemeCode") or "")
        if code.isdigit():
            out.append({"symbol": f"MF:{code}", "name": str(row.get("schemeName") or ""),
                        "exchange": "MF", "held": False, "asset_class": "mutual_fund"})
        if len(out) >= limit:
            break
    return out
