"""Carhart four-factor analysis for Indian portfolios.

Factor data: the IIM Ahmedabad "Fama French and Momentum Factors Data Library
for Indian Market" (Agarwalla, Jacob and Varma), survivorship-bias adjusted,
daily. Columns: MF (market return above the risk-free rate), SMB (small minus
big), HML (high minus low book-to-market, i.e. value), WML (winners minus
losers, i.e. momentum) and RF (91-day T-bill), all in percent per day. The
library publishes a few releases a year, so its data ends some months back;
the newest release is picked up automatically.

Model, by ordinary least squares on daily returns over the chosen window:
    r - RF = alpha + b_mkt * MF + b_smb * SMB + b_hml * HML + b_wml * WML + e
Portfolio returns use today's weights (as the Risk tab does), so the loadings
describe the portfolio held now."""
from __future__ import annotations

import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.brokers import http

BASE = "https://faculty.iima.ac.in/iffm/Indian-Fama-French-Momentum/"
FILE_RE = re.compile(r"DATA/(\d{4}-\d{2})_FourFactors_and_Market_Returns_Daily_SurvivorshipBiasAdjusted\.csv")
RECHECK = timedelta(days=7)
COLUMNS = ["MF", "SMB", "HML", "WML", "RF"]
NAMES = {"MF": "market", "SMB": "size", "HML": "value", "WML": "momentum"}
CITATION = ("Agarwalla, S. K., Jacob, J. and Varma, J. R. (2013), Four factor model in Indian equities market, "
            "Working Paper W.P. No. 2013-09-05, Indian Institute of Management, Ahmedabad.")


def latest_file(page_html: str) -> tuple[str, str]:
    """(release, relative path) of the newest daily, survivorship-adjusted file on the library page."""
    found = sorted({(m.group(1), m.group(0)) for m in FILE_RE.finditer(page_html)})
    if not found:
        raise ValueError("No daily four-factor file listed on the IIM Ahmedabad page")
    return found[-1]


def parse(raw: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(raw), na_values=["NA", ""])
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    return df.set_index("Date")[COLUMNS].dropna() / 100.0


def load(cache_dir: Path) -> tuple[str, pd.DataFrame]:
    """(release, daily factors as decimals). Downloads a new release at most once a
    week; when IIM Ahmedabad cannot be reached, the saved copy is used."""
    folder = Path(cache_dir)
    meta_path, data_path = folder / "iima_factors.json", folder / "iima_factors.csv"
    meta = {}
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        pass
    cached = data_path.exists() and meta.get("release")
    fresh = cached and datetime.now() - datetime.fromisoformat(meta.get("checked", "2000-01-01")) < RECHECK
    if not fresh:
        try:
            release, path = latest_file(http.get_bytes(BASE, timeout=20).decode("utf-8", "replace"))
            if release != meta.get("release") or not data_path.exists():
                raw = http.get_bytes(BASE + path, timeout=60)
                if len(parse(raw)) < 250:              # never replace a good copy with a broken one
                    raise ValueError("The downloaded four-factor file is too short to be the real data")
                data_path.write_bytes(raw)
            meta = {"release": release, "checked": datetime.now().isoformat()}
            meta_path.write_text(json.dumps(meta))
        except Exception:
            if not cached:
                raise
    return meta["release"], parse(data_path.read_bytes())


def regress(y: np.ndarray, x: np.ndarray) -> dict:
    """OLS of y on [1, x] with classical standard errors."""
    X = np.column_stack([np.ones(len(y)), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    n, k = X.shape
    dof = max(n - k, 1)
    sigma2 = float(resid @ resid) / dof
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(resid @ resid) / tss if tss > 0 else float("nan")
    return {"coef": coef, "se": se, "t": coef / se, "r2": r2, "adj_r2": 1 - (1 - r2) * (n - 1) / dof, "n": n}


def summarise(fit: dict) -> dict:
    """JSON shape: annualised alpha and each factor's loading, with t-statistics."""
    def item(i):
        return {"coef": float(fit["coef"][i]), "se": float(fit["se"][i]), "t": float(fit["t"][i])}

    alpha = item(0)
    return {
        "alpha": {"annual": alpha["coef"] * 252, "daily": alpha["coef"], "t": alpha["t"]},
        "loadings": {NAMES[c]: item(i + 1) for i, c in enumerate(["MF", "SMB", "HML", "WML"])},
        "r2": float(fit["r2"]), "adj_r2": float(fit["adj_r2"]),
    }


# ---------------------------------------------------------------- your own factor file
#
# For a period IIM Ahmedabad's release does not cover yet, or for factors built
# another way, a daily file can be uploaded: a date column plus market (excess),
# size, value, momentum and, ideally, the risk-free rate. Percent or decimal
# returns are both accepted; the units are worked out from the numbers.

UPLOAD_DATA, UPLOAD_META = "user_factors.csv", "user_factors.json"
MIN_ROWS = 60
ALIASES = {
    "MF": {"mf", "mkt", "mktrf", "market", "rmrf", "marketexcess", "excessmarket", "mkt-rf", "erm"},
    "SMB": {"smb", "size"},
    "HML": {"hml", "value"},
    "WML": {"wml", "mom", "umd", "momentum", "pr1yr", "wml(momentum)"},
    "RF": {"rf", "riskfree", "rfr", "tbill", "riskfreerate"},
}


def _key(name: str) -> str:
    return re.sub(r"[\s_\-.%()]", "", str(name).strip().lower())


def _dates(col: pd.Series) -> pd.Series:
    text = col.astype(str).str.strip()
    if text.str.fullmatch(r"\d{8}").all():                         # 20260105, as in Ken French's files
        return pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    if text.str.match(r"\d{4}-").all():
        return pd.to_datetime(text, errors="coerce", format="mixed")
    return pd.to_datetime(text, errors="coerce", dayfirst=True, format="mixed")   # Indian style: 05-01-2026


def parse_upload(raw: bytes, filename: str = "") -> tuple[pd.DataFrame, dict]:
    """(daily factors as decimals, info) from an uploaded CSV or Excel file.
    Raises ValueError with a reason the user can act on."""
    try:
        if filename.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw))
        else:
            df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", na_values=["NA", "", "-"])
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not read the file as a table ({str(exc)[:60]})") from exc
    if df.shape[1] < 2:
        raise ValueError("Could not read the file as a table: expected a Date column and the factor columns")
    keys = {_key(c): c for c in df.columns}
    found = {}
    for col, names in ALIASES.items():
        hit = next((keys[_key(n)] for n in names if _key(n) in keys), None)
        if hit is not None:
            found[col] = hit
    missing = [c for c in ("MF", "SMB", "HML", "WML") if c not in found]
    if not found:
        raise ValueError("Could not read any factor columns. Expected Date, MF (or Mkt-RF), SMB, HML, "
                         "WML (or MOM/UMD) and RF")
    if missing:
        raise ValueError(f"Missing column(s) {', '.join(missing)}. Expected Date, MF (or Mkt-RF), SMB, HML, "
                         "WML (or MOM/UMD) and RF")
    date_col = keys.get("date", df.columns[0])
    out = pd.DataFrame({c: pd.to_numeric(df[found[c]], errors="coerce") for c in found})
    out.index = _dates(df[date_col])
    out = out[out.index.notna()].dropna(subset=["MF", "SMB", "HML", "WML"])
    warnings = []
    if "RF" not in out:
        out["RF"] = 0.0
        warnings.append("No RF (risk-free) column: assumed zero, so alpha includes the T-bill rate")
    out["RF"] = out["RF"].fillna(0.0)
    out = out[~out.index.duplicated(keep="last")].sort_index()[COLUMNS]
    if len(out) < MIN_ROWS:
        raise ValueError(f"Only {len(out)} usable rows; need at least {MIN_ROWS} trading days")
    gap = pd.Series(out.index).diff().dt.days.median()
    if gap > 5:
        raise ValueError(f"The rows are about {gap:.0f} days apart; the analysis needs daily factor returns")
    units = "percent" if out[["MF", "SMB", "HML", "WML"]].abs().median().median() > 0.05 else "decimal"
    if units == "percent":
        out = out / 100.0
    if (out[["MF", "SMB", "HML", "WML"]].abs() > 0.5).any().any():
        raise ValueError("Some daily factor returns are above 50%; check the units and the columns")
    out.index = out.index.date
    out.index.name = "Date"
    info = {"name": Path(filename).name or "factors.csv", "rows": len(out), "from": str(out.index[0]),
            "to": str(out.index[-1]), "units": units, "warnings": warnings,
            "uploaded": datetime.now().isoformat(timespec="seconds")}
    return out, info


def save_upload(cache_dir: Path, raw: bytes, filename: str) -> dict:
    """Check and keep the user's factor file (as decimals) in the data folder."""
    out, info = parse_upload(raw, filename)
    folder = Path(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    out.to_csv(folder / UPLOAD_DATA)
    (folder / UPLOAD_META).write_text(json.dumps(info))
    return info


def load_upload(cache_dir: Path) -> tuple[dict, pd.DataFrame] | None:
    folder = Path(cache_dir)
    try:
        meta = json.loads((folder / UPLOAD_META).read_text())
        df = pd.read_csv(folder / UPLOAD_DATA, parse_dates=["Date"])
    except (OSError, ValueError):
        return None
    df["Date"] = df["Date"].dt.date
    return meta, df.set_index("Date")[COLUMNS]


def delete_upload(cache_dir: Path) -> None:
    for name in (UPLOAD_DATA, UPLOAD_META):
        (Path(cache_dir) / name).unlink(missing_ok=True)
