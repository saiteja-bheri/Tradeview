"""Gold, silver and other commodities, priced in rupees (symbol CMDTY:<NAME>).

The price is the international benchmark converted to INR per Indian trading
unit: the front-month COMEX/NYMEX future from Yahoo Finance (USD) times the
USD/INR rate, scaled to the unit Indians quote (gold per gram, silver per kg).

It is an international spot equivalent. Physical gold in India usually costs
several percent more (import duty and GST), and MCX futures differ slightly,
so use it to track value and risk, not as a buy or sell price. For gold you
hold through the market, Gold ETFs (GOLDBEES) and Sovereign Gold Bonds (SGB...)
are listed on NSE and are tracked like any stock, with exact prices."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pandas as pd

TROY_OUNCE_G = 31.1034768
POUND_KG = 0.45359237

# name: (Yahoo future in USD, quote unit, multiply USD price by this for one unit, label)
COMMODITIES: dict[str, tuple[str, str, float, str]] = {
    "GOLD": ("GC=F", "g", 1 / TROY_OUNCE_G, "Gold, 24K equivalent (per gram)"),
    "SILVER": ("SI=F", "kg", 1000 / TROY_OUNCE_G, "Silver (per kg)"),
    "PLATINUM": ("PL=F", "g", 1 / TROY_OUNCE_G, "Platinum (per gram)"),
    "CRUDE": ("CL=F", "bbl", 1.0, "Crude oil, WTI (per barrel)"),
    "BRENT": ("BZ=F", "bbl", 1.0, "Crude oil, Brent (per barrel)"),
    "NATGAS": ("NG=F", "MMBtu", 1.0, "Natural gas (per MMBtu)"),
    "COPPER": ("HG=F", "kg", 1 / POUND_KG, "Copper (per kg)"),
}
FX = "USDINR=X"

YahooFetch = Callable[[str, date], pd.DataFrame]


def name_of(symbol: str) -> str:
    return symbol.partition(":")[2].upper()


def fetch(symbol: str, start: date, yahoo: YahooFetch | None = None) -> pd.DataFrame:
    name = name_of(symbol)
    if name not in COMMODITIES:
        raise ValueError(f"Unknown commodity {name}. Choose from {', '.join(COMMODITIES)}")
    if yahoo is None:
        from app.market.history import fetch as yahoo
    future, _, factor, _ = COMMODITIES[name]
    usd = yahoo(future, start - timedelta(days=7))["close"]
    fx = yahoo(FX, start - timedelta(days=7))["close"]
    if usd.empty or fx.empty:
        raise ValueError(f"No price data for {name} or the USD/INR rate")
    # Futures and FX trade on different calendars: carry the last FX rate forward.
    fx = fx.reindex(sorted(set(fx.index) | set(usd.index))).ffill()
    inr = (usd * fx.reindex(usd.index) * factor).dropna()
    inr = inr[[d >= start for d in inr.index]]
    frame = pd.DataFrame({"close": inr, "adj_close": inr})
    frame["dividend"] = 0.0
    frame["split"] = 0.0
    return frame


def search(query: str) -> list[dict]:
    q = query.strip().lower()
    out = []
    for name, (_, unit, _, label) in COMMODITIES.items():
        if q and (q in name.lower() or q in label.lower()):
            out.append({"symbol": f"CMDTY:{name}", "name": f"{label}, INR", "exchange": "CMDTY",
                        "held": False, "asset_class": "gold" if name == "GOLD" else "commodity"})
    return out
