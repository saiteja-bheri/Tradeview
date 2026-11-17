"""One naming scheme for every source.

The ledger, price cache and risk maths all key instruments by their Yahoo
symbol (RELIANCE.NS, 500325.BO). Brokers and exchanges each use their own
names, so every adapter converts at the edge with the helpers here. ISIN is
the tie-breaker: the same company can be bought on NSE at one broker and on
BSE at another, and only the ISIN says it is one holding."""
from __future__ import annotations

import re

SUFFIX = {"NSE": ".NS", "BSE": ".BO"}
EXCHANGE = {"NS": "NSE", "BO": "BSE"}

# NSE series suffixes some brokers append to the trading symbol (IDEA-BE, TATAMOTORS-EQ).
_SERIES = re.compile(r"-(EQ|BE|BZ|BL|SM|ST|IL|E1|X1)$")


def clean_trading_symbol(raw: str) -> str:
    return _SERIES.sub("", raw.strip().upper())


def to_yahoo(trading_symbol: str, exchange: str) -> str:
    """('RELIANCE', 'NSE') -> 'RELIANCE.NS'. Unknown exchanges default to NSE.
    Namespaced symbols (MF:, CMDTY:, BOND:) pass through unchanged."""
    if is_namespaced(trading_symbol) or exchange.strip().upper() == "INTL":
        return trading_symbol.strip().upper()
    return f"{clean_trading_symbol(trading_symbol)}{SUFFIX.get(exchange.strip().upper(), '.NS')}"


def split(symbol: str) -> tuple[str, str]:
    """'RELIANCE.NS' -> ('RELIANCE', 'NSE'). Symbols without a known suffix come back as-is with ''."""
    base, dot, suffix = symbol.rpartition(".")
    if not dot or suffix.upper() not in EXCHANGE:
        return symbol, ""
    return base.upper(), EXCHANGE[suffix.upper()]


def is_isin(value: str) -> bool:
    return bool(re.fullmatch(r"IN[A-Z0-9]{9}\d", (value or "").strip().upper()))


# ---------------------------------------------------------------- non-exchange instruments
#
# Instruments that have no Yahoo stock ticker get a namespaced symbol:
#   MF:122639        mutual fund, by AMFI scheme code (NAVs from AMFI via mfapi.in)
#   CMDTY:GOLD       commodity, priced in INR per Indian trading unit (see market/commodities.py)
#   BOND:GOI2033     a bond whose terms are entered by hand (see the bonds table)

NAMESPACES = ("MF", "CMDTY", "BOND")
ASSET_CLASSES = ("equity", "etf", "mutual_fund", "gold", "commodity", "bond")
_NAMESPACED = re.compile(r"^(MF:\d{3,8}|CMDTY:[A-Z]{2,12}|BOND:[A-Z0-9-]{1,30})$")


def namespace(symbol: str) -> str | None:
    head, sep, _ = symbol.partition(":")
    return head.upper() if sep and head.upper() in NAMESPACES else None


def is_namespaced(symbol: str) -> bool:
    return bool(_NAMESPACED.match(symbol.strip().upper()))


def asset_class(symbol: str, name: str = "", quote_type: str = "") -> str:
    """Best guess from the symbol, the instrument name and Yahoo's quote type."""
    ns, upper = namespace(symbol), f"{symbol} {name}".upper()
    if ns == "MF":
        return "mutual_fund"
    if ns == "BOND":
        return "bond"
    if ns == "CMDTY":
        return "gold" if symbol.upper() == "CMDTY:GOLD" else "commodity"
    base = symbol.rpartition(".")[0].upper() or symbol.upper()
    if base.startswith("SGB"):
        return "gold"                       # Sovereign Gold Bonds trade on NSE as SGB...
    is_etf = quote_type.upper() == "ETF" or "ETF" in upper or base.endswith("BEES") or "BEES" in base
    if is_etf:
        if "GOLD" in upper:
            return "gold"
        if "SILVER" in upper:
            return "commodity"
        return "etf"
    if quote_type.upper() == "MUTUALFUND":
        return "mutual_fund"
    return "equity"


# ---------------------------------------------------------------- international listings
#
# Anything that is not an NSE/BSE symbol, an index (^...), an FX pair (...=X) or
# a namespaced instrument is an international Yahoo listing: AAPL, MSFT (US),
# VOD.L (London), 7203.T (Tokyo), SAP.DE (Xetra) and so on.

_INTL = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,19}(\.[A-Z]{1,3})?$")
# Yahoo suffix -> trading currency, used until Yahoo reports the real one.
_SUFFIX_CCY = {
    "L": "GBp", "IL": "GBp", "T": "JPY", "HK": "HKD", "DE": "EUR", "F": "EUR", "PA": "EUR", "AS": "EUR",
    "MI": "EUR", "MC": "EUR", "BR": "EUR", "LS": "EUR", "HE": "EUR", "VI": "EUR", "IR": "EUR",
    "TO": "CAD", "V": "CAD", "AX": "AUD", "NZ": "NZD", "SI": "SGD", "SW": "CHF", "KS": "KRW", "KQ": "KRW",
    "SS": "CNY", "SZ": "CNY", "TW": "TWD", "ST": "SEK", "OL": "NOK", "CO": "DKK", "SA": "BRL", "MX": "MXN",
    "JO": "ZAc", "TA": "ILA", "KL": "MYR", "BK": "THB", "JK": "IDR",
}
# Currencies Yahoo quotes in minor units (pence, cents, agorot).
MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def is_indian(symbol: str) -> bool:
    return split(symbol)[1] != ""


def is_international(symbol: str) -> bool:
    s = symbol.strip().upper()
    if is_indian(s) or namespace(s) or s.startswith("^") or s.endswith("=X") or "=" in s:
        return False
    return bool(_INTL.match(s))


# Foreign market indices, quoted in their home currency. Indian indices
# (^NSEI, ^BSESN, ^CRSLDX, ^NSEBANK...) are INR and need no entry. Yahoo's own
# reported currency, once a symbol has been downloaded, takes precedence.
_INDEX_CCY = {
    "^GSPC": "USD", "^DJI": "USD", "^IXIC": "USD", "^NDX": "USD", "^RUT": "USD", "^VIX": "USD", "^NYA": "USD",
    "^FTSE": "GBP", "^FTMC": "GBP", "^N225": "JPY", "^HSI": "HKD", "^GDAXI": "EUR", "^FCHI": "EUR",
    "^STOXX50E": "EUR", "^AEX": "EUR", "^IBEX": "EUR", "^SSMI": "CHF", "^AXJO": "AUD", "^GSPTSE": "CAD",
    "^KS11": "KRW", "^TWII": "TWD", "^STI": "SGD", "^BVSP": "BRL", "^MXX": "MXN", "000001.SS": "CNY",
}


def guess_currency(symbol: str) -> str:
    s = symbol.strip().upper()
    if s in _INDEX_CCY:
        return _INDEX_CCY[s]
    if not is_international(symbol):
        return "INR"
    suffix = symbol.rpartition(".")[2].upper() if "." in symbol else ""
    return _SUFFIX_CCY.get(suffix, "USD")


def fx_pair(currency: str) -> tuple[str, float] | None:
    """Yahoo FX symbol giving INR per unit of the major currency, and the divisor
    for minor-unit quotes. None for INR."""
    if not currency or currency.upper() == "INR":
        return None
    major, divisor = MINOR_UNITS.get(currency, (currency.upper(), 1.0))
    return f"{major}INR=X", divisor
