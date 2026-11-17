"""Engine configuration. Everything is driven by environment variables so the
Electron shell can configure the engine the same way on macOS and Windows."""
from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "QuantTerminal"

DEFAULT_SETTINGS: dict[str, float | int | str] = {
    "benchmark": "^NSEI",
    "benchmark_name": "",
    "confidence": 0.95,
    "horizon_days": 1,
    "lookback_days": 252,
    "cov_horizon_days": 1,
    # Trading days of history behind the covariance matrix; 0 = same as lookback_days.
    "cov_lookback_days": 0,
    "risk_free_rate": 0.065,
    # How money is shown. The ledger and every calculation stay in INR; values are
    # converted at the latest rate for display. AUTO = the currency most of the
    # portfolio's value is in.
    "display_currency": "INR",
    # How often a new AI memo may be generated: "hourly" or "daily". Asking again
    # sooner returns the latest memo without calling Gemini (no tokens spent).
    "insight_frequency": "hourly",
}

INSIGHT_WINDOWS = {"hourly": 3600, "daily": 86400}

DISPLAY_CURRENCIES = ("AUTO", "INR", "USD", "EUR", "GBP", "JPY", "AED", "SGD", "AUD", "CAD", "CHF", "HKD")

# Ready-made choices for the benchmark picker. Any other Yahoo symbol (index,
# ETF, mutual fund or stock) can be used too; these are only shortcuts.
BENCHMARK_PRESETS: tuple[tuple[str, str, str], ...] = (
    ("^NSEI", "NIFTY 50", "INDEX"),
    ("^BSESN", "SENSEX", "INDEX"),
    ("^CRSLDX", "NIFTY 500", "INDEX"),
    ("^NSEBANK", "NIFTY BANK", "INDEX"),
    ("^CNX100", "NIFTY 100", "INDEX"),
    ("^CNX200", "NIFTY 200", "INDEX"),
    ("^NSMIDCP", "NIFTY NEXT 50", "INDEX"),
    ("^NSEMDCP50", "NIFTY MIDCAP 50", "INDEX"),
    ("NIFTYMIDCAP150.NS", "NIFTY MIDCAP 150", "INDEX"),
    ("NIFTYSMLCAP250.NS", "NIFTY SMALLCAP 250", "INDEX"),
    ("NIFTY_FIN_SERVICE.NS", "NIFTY FINANCIAL SERVICES", "INDEX"),
    ("^CNXIT", "NIFTY IT", "INDEX"),
    ("^CNXAUTO", "NIFTY AUTO", "INDEX"),
    ("^CNXPHARMA", "NIFTY PHARMA", "INDEX"),
    ("^CNXFMCG", "NIFTY FMCG", "INDEX"),
    ("^CNXMETAL", "NIFTY METAL", "INDEX"),
    ("^CNXENERGY", "NIFTY ENERGY", "INDEX"),
    ("^CNXREALTY", "NIFTY REALTY", "INDEX"),
    ("^CNXPSUBANK", "NIFTY PSU BANK", "INDEX"),
    ("^CNXINFRA", "NIFTY INFRASTRUCTURE", "INDEX"),
    ("BSE-100.BO", "BSE 100", "INDEX"),
    ("BSE-200.BO", "BSE 200", "INDEX"),
    ("BSE-500.BO", "BSE 500", "INDEX"),
    ("NIFTYBEES.NS", "Nippon India ETF Nifty 50 BeES", "ETF"),
    ("BANKBEES.NS", "Nippon India ETF Nifty Bank BeES", "ETF"),
    ("JUNIORBEES.NS", "Nippon India ETF Nifty Next 50 Junior BeES", "ETF"),
    ("GOLDBEES.NS", "Nippon India ETF Gold BeES", "ETF"),
)
BENCHMARK_NAMES = {symbol: name for symbol, name, _ in BENCHMARK_PRESETS}


def data_dir() -> Path:
    """Per-user data folder: ~/Library/Application Support on macOS,
    %LOCALAPPDATA% on Windows. Override with QT_DATA_DIR."""
    override = os.environ.get("QT_DATA_DIR")
    path = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_url() -> str:
    return f"sqlite:///{(data_dir() / 'ledger.sqlite3').as_posix()}"


def host() -> str:
    return "127.0.0.1"  # never exposed beyond the local machine


def port() -> int:
    return int(os.environ.get("QT_PORT", "8765"))


def token() -> str | None:
    """Optional per-session token set by the Electron shell."""
    return os.environ.get("QT_TOKEN") or None


def feed_choice() -> str:
    return os.environ.get("QT_FEED", "auto").strip().lower()



def gemini_model() -> str:
    return os.environ.get("QT_GEMINI_MODEL", "").strip() or "gemini-3.8-flash"
