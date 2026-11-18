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
