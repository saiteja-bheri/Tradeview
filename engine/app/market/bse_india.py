"""BSE India data through the community `bse` package (BseIndiaApi).

BSE publishes no official public API; `bse` reads the JSON that bseindia.com
itself uses, and can break when BSE changes its site. It is optional
(pip install bse) and every caller treats a failure as a warning.

What it adds over Yahoo:
  * scrip-code lookup by ISIN or ticker (lookup / getScripCode)
  * quotes with BSE's own previous close (quote)
  * BSE's corporate-action list (actions): dividends, bonus issues and splits
    straight from the exchange. Yahoo often misses Indian bonus issues, which
    otherwise have to be entered by hand.
The package throttles its own requests and keeps its cookies in the folder
it is given, here the app's data folder (never its install folder)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

INSTALL = "BSE data needs the bse package: run  engine\\.venv\\Scripts\\pip install bse"

_DIVIDEND = re.compile(r"dividend\s*-?\s*rs\.?\s*-?\s*([\d.]+)", re.I)
_BONUS = re.compile(r"bonus\s+issue\s+(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", re.I)
_SPLIT = re.compile(r"split\s+from\s+rs\.?\s*([\d.]+)\s*/?-?\s*to\s+rs\.?\s*([\d.]+)", re.I)


def parse_purpose(purpose: str) -> list[tuple[str, float]]:
    """BSE 'Purpose' text -> [(kind, value)] in this app's terms.
    'Interim Dividend - Rs. - 18.0000'        -> [('dividend', 18.0)]
    'Bonus issue 1:1'                          -> [('bonus', 2.0)]   (1 new per 1 held)
    'Stock  Split From Rs.10/- to Rs.2/-'      -> [('split', 5.0)]
    Several dividends in one line are added up. Anything else (rights, buyback,
    AGM) is not a price-affecting action this ledger models, so it is ignored."""
    out: list[tuple[str, float]] = []
    dividends = [float(x) for x in _DIVIDEND.findall(purpose) if float(x) > 0]
    if dividends:
        out.append(("dividend", round(sum(dividends), 6)))
    bonus = _BONUS.search(purpose)
    if bonus:
        new, held = float(bonus.group(1)), float(bonus.group(2))
        if new > 0 and held > 0:
            out.append(("bonus", (new + held) / held))
    split = _SPLIT.search(purpose)
    if split:
        old, new = float(split.group(1)), float(split.group(2))
        if old > 0 and new > 0 and old != new:
            out.append(("split", old / new))
    return out


def _ex_date(row: dict) -> date | None:
    raw = str(row.get("exdate") or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
    text = str(row.get("Ex_date") or "").strip()
    try:
        return datetime.strptime(text, "%d %b %Y").date()
    except ValueError:
        return None


class BseClient:
    """Thin, cached wrapper. `factory` builds the bse.BSE object (tests pass a fake)."""

    def __init__(self, cache_dir: Path, factory=None):
        self._dir = Path(cache_dir) / "bse"
        self._codes_file = Path(cache_dir) / "bse_codes.json"
        self._factory = factory
        self._api = None
        try:
            self._codes: dict[str, str] = json.loads(self._codes_file.read_text())
        except (OSError, ValueError):
            self._codes = {}

    def api(self):
        if self._api is None:
            if self._factory is None:
                try:
                    from bse import BSE
                except ImportError as exc:
                    raise RuntimeError(INSTALL) from exc
                self._dir.mkdir(parents=True, exist_ok=True)
                self._factory = lambda: BSE(download_folder=self._dir)
            self._api = self._factory()
        return self._api

    def close(self) -> None:
        if self._api is not None and hasattr(self._api, "exit"):
            try:
                self._api.exit()
            except Exception:
                pass
        self._api = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def code_for(self, symbol: str, isin: str = "") -> str | None:
        """BSE scrip code for a Yahoo symbol: 500325.BO is one already; otherwise
        look up by ISIN (exact) or ticker. Answers are cached on disk."""
        base = symbol.rpartition(".")[0].upper() or symbol.upper()
        if base.isdigit():
            return base
        key = isin or base
        if key in self._codes:
            return self._codes[key] or None
        code = None
        try:
            if isin:
                found = self.api().lookup(isin)
                code = str(found["bse_code"]) if found and found.get("bse_code") else None
            if code is None:
                code = str(self.api().getScripCode(base))
        except (ValueError, KeyError):
            code = None  # not listed on BSE
        self._codes[key] = code or ""
        try:
            self._codes_file.write_text(json.dumps(self._codes))
        except OSError:
            pass
        return code

    def quote(self, code: str) -> dict[str, float | None]:
        q = self.api().quote(code)
        ltp, prev = q.get("LTP"), q.get("PrevClose")
        return {"ltp": float(ltp) if ltp else None, "prev_close": float(prev) if prev else None}

    def actions(self, code: str, start: date, end: date) -> list[dict[str, Any]]:
        """[{ex_date, kind, value, purpose}] for one scrip between two dates."""
        rows = self.api().actions(segment="equity", scripcode=code,
                                  from_date=datetime.combine(start, datetime.min.time()),
                                  to_date=datetime.combine(end, datetime.min.time()))
        out = []
        for row in rows or []:
            ex = _ex_date(row)
            if ex is None:
                continue
            for kind, value in parse_purpose(str(row.get("Purpose") or "")):
                out.append({"ex_date": ex, "kind": kind, "value": value, "purpose": row.get("Purpose", "")})
        return out
