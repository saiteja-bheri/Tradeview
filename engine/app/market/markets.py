"""Which market a listing trades on, from Yahoo's exchange code or symbol suffix.

Used so search results say where a stock trades (NSE, NASDAQ, London...) and
in what currency, and so the search can be narrowed to one market."""
from __future__ import annotations

# Yahoo exchange code -> (market group, exchange label, currency)
EXCHANGES: dict[str, tuple[str, str, str]] = {
    "NSI": ("INDIA", "NSE", "INR"), "BSE": ("INDIA", "BSE", "INR"), "BOM": ("INDIA", "BSE", "INR"),
    "NMS": ("US", "NASDAQ", "USD"), "NGM": ("US", "NASDAQ", "USD"), "NCM": ("US", "NASDAQ", "USD"),
    "NAS": ("US", "NASDAQ", "USD"), "NYQ": ("US", "NYSE", "USD"), "ASE": ("US", "NYSE AM", "USD"),
    "PCX": ("US", "NYSE ARCA", "USD"), "BTS": ("US", "CBOE", "USD"), "PNK": ("US", "OTC", "USD"),
    "LSE": ("UK", "LSE", "GBp"), "IOB": ("UK", "LSE IOB", "USD"),
    "GER": ("EUROPE", "XETRA", "EUR"), "FRA": ("EUROPE", "FRANKFURT", "EUR"), "PAR": ("EUROPE", "PARIS", "EUR"),
    "AMS": ("EUROPE", "AMSTERDAM", "EUR"), "MIL": ("EUROPE", "MILAN", "EUR"), "MCE": ("EUROPE", "MADRID", "EUR"),
    "BRU": ("EUROPE", "BRUSSELS", "EUR"), "EBS": ("EUROPE", "SIX", "CHF"), "STO": ("EUROPE", "STOCKHOLM", "SEK"),
    "OSL": ("EUROPE", "OSLO", "NOK"), "CPH": ("EUROPE", "COPENHAGEN", "DKK"),
    "HAM": ("EUROPE", "HAMBURG", "EUR"), "DUS": ("EUROPE", "DUSSELDORF", "EUR"), "STU": ("EUROPE", "STUTTGART", "EUR"),
    "MUN": ("EUROPE", "MUNICH", "EUR"), "BER": ("EUROPE", "BERLIN", "EUR"), "VIE": ("EUROPE", "VIENNA", "EUR"),
    "HEL": ("EUROPE", "HELSINKI", "EUR"), "LIS": ("EUROPE", "LISBON", "EUR"), "ISE": ("EUROPE", "DUBLIN", "EUR"),
    "JPX": ("ASIA", "TOKYO", "JPY"), "HKG": ("ASIA", "HONG KONG", "HKD"), "SES": ("ASIA", "SINGAPORE", "SGD"),
    "KSC": ("ASIA", "KOREA", "KRW"), "KOE": ("ASIA", "KOSDAQ", "KRW"), "SHH": ("ASIA", "SHANGHAI", "CNY"),
    "SHZ": ("ASIA", "SHENZHEN", "CNY"), "TAI": ("ASIA", "TAIWAN", "TWD"),
    "TOR": ("AMERICAS", "TORONTO", "CAD"), "VAN": ("AMERICAS", "TSX-V", "CAD"), "SAO": ("AMERICAS", "B3", "BRL"),
    "MEX": ("AMERICAS", "MEXICO", "MXN"), "ASX": ("PACIFIC", "ASX", "AUD"), "NZE": ("PACIFIC", "NZX", "NZD"),
}

# Yahoo symbol suffix -> exchange code, for rows without an exchange code (the ledger's own instruments).
SUFFIX_EXCHANGE = {
    "NS": "NSI", "BO": "BSE", "L": "LSE", "DE": "GER", "F": "FRA", "PA": "PAR", "AS": "AMS", "MI": "MIL",
    "MC": "MCE", "BR": "BRU", "SW": "EBS", "ST": "STO", "OL": "OSL", "CO": "CPH", "T": "JPX", "HK": "HKG",
    "SI": "SES", "KS": "KSC", "KQ": "KOE", "SS": "SHH", "SZ": "SHZ", "TW": "TAI", "TO": "TOR", "V": "VAN",
    "SA": "SAO", "MX": "MEX", "AX": "ASX", "NZ": "NZE",
    "HM": "HAM", "DU": "DUS", "SG": "STU", "MU": "MUN", "BE": "BER", "VI": "VIE", "HE": "HEL", "LS": "LIS",
    "IR": "ISE",
}

MARKETS = ("ALL", "INDIA", "US", "UK", "EUROPE", "ASIA", "AMERICAS", "PACIFIC", "FUNDS")


def describe(symbol: str, code: str = "", label: str = "") -> dict:
    """{market, exchange, currency} for a listing."""
    sym = symbol.upper()
    if sym.startswith("MF:"):
        return {"market": "FUNDS", "exchange": "AMFI", "currency": "INR"}
    if sym.startswith("CMDTY:"):
        return {"market": "FUNDS", "exchange": "CMDTY", "currency": "INR"}
    if not code:
        suffix = sym.rpartition(".")[2] if "." in sym else ""
        if not suffix and not sym.startswith("^"):
            return {"market": "US", "exchange": "US", "currency": "USD"}  # NYSE or NASDAQ: no way to tell
        code = SUFFIX_EXCHANGE.get(suffix, "")
    market, name, currency = EXCHANGES.get(code.upper(), ("OTHER", label.upper() or code.upper() or "INTL", ""))
    return {"market": market, "exchange": name, "currency": currency}
