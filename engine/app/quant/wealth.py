"""Everything you own outside the market portfolio, and the overall picture.

Kinds, with how each is valued today:
  cash               bank and wallet balances: the balance
  fixed_deposit      principal compounding quarterly at its rate from the start date
                     (to maturity, after which it stops growing until renewed)
  recurring_deposit  the balance you enter; grows with its rate and instalment
  ppf, epf, nps,
  pension            the balance or fund value you enter
  life_insurance     endowment, money-back or ULIP: the fund / surrender value you
                     enter; its sum assured counts as protection
  term_insurance     no cash value; only its cover counts, as protection

Liquidity: cash is available now; deposits can be broken early (with a
penalty); pension savings and policies are locked until their rules allow.
Default growth rates (used when you leave the rate blank) are the published
rates for PPF and EPF and typical figures for the rest; edit any of them."""
from __future__ import annotations

from datetime import date

KINDS: dict[str, dict] = {
    "cash": {"label": "Cash & savings", "group": "Cash", "liquidity": "liquid", "rate": 3.0},
    "fixed_deposit": {"label": "Fixed deposit", "group": "Deposits", "liquidity": "deposit", "rate": 7.0},
    "recurring_deposit": {"label": "Recurring deposit", "group": "Deposits", "liquidity": "deposit", "rate": 6.8},
    "ppf": {"label": "PPF", "group": "Retirement", "liquidity": "locked", "rate": 7.1},
    "epf": {"label": "EPF", "group": "Retirement", "liquidity": "locked", "rate": 8.25},
    "nps": {"label": "NPS", "group": "Retirement", "liquidity": "locked", "rate": 9.0},
    "pension": {"label": "Other pension fund", "group": "Retirement", "liquidity": "locked", "rate": 8.0},
    "life_insurance": {"label": "Life insurance (savings / ULIP)", "group": "Insurance", "liquidity": "locked", "rate": 5.5},
    "term_insurance": {"label": "Term insurance", "group": "Insurance", "liquidity": "protection", "rate": 0.0},
}


def rate_of(item) -> float:
    """Annual growth rate in percent: the item's own, or the default for its kind."""
    return item.rate if item.rate else KINDS.get(item.kind, {}).get("rate", 0.0)


def value_of(item, on: date | None = None) -> float:
    """Value today (or on a given day) in INR."""
    on = on or date.today()
    if item.kind == "term_insurance":
        return 0.0
    if item.kind == "fixed_deposit" and item.start_date:
        end = min(on, item.maturity_date) if item.maturity_date else on
        years = max((end - item.start_date).days, 0) / 365.0
        return item.amount * (1 + rate_of(item) / 100 / 4) ** (4 * years)
    return item.amount


def item_json(item) -> dict:
    meta = KINDS.get(item.kind, {"label": item.kind, "group": "Other", "liquidity": "locked"})
    today = date.today()
    return {
        "id": item.id, "kind": item.kind, "kind_label": meta["label"], "group": meta["group"],
        "liquidity": meta["liquidity"], "name": item.name, "institution": item.institution,
        "amount": item.amount, "rate": item.rate, "effective_rate": rate_of(item),
        "start_date": item.start_date.isoformat() if item.start_date else None,
        "maturity_date": item.maturity_date.isoformat() if item.maturity_date else None,
        "monthly_contribution": item.monthly_contribution, "cover": item.cover, "premium": item.premium,
        "notes": item.notes, "value": value_of(item),
        "matures_in_days": (item.maturity_date - today).days if item.maturity_date else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def summary(items, market_value: float, market_by_class: dict[str, float], portfolio_cash: float = 0.0) -> dict:
    """Net worth and how it is spread: market portfolio, portfolio cash (dividends,
    coupons and sale proceeds not yet withdrawn or reinvested) and everything else."""
    rows = [item_json(i) for i in items]
    portfolio_cash = max(portfolio_cash, 0.0)
    other = sum(r["value"] for r in rows) + portfolio_cash
    net = market_value + other
    groups: dict[str, float] = {}
    for cls, v in market_by_class.items():
        groups[_MARKET_GROUP.get(cls, "Equity")] = groups.get(_MARKET_GROUP.get(cls, "Equity"), 0.0) + v
    for r in rows:
        if r["value"] > 0:
            groups[r["group"]] = groups.get(r["group"], 0.0) + r["value"]
    if portfolio_cash > 0:
        groups["Cash"] = groups.get("Cash", 0.0) + portfolio_cash
    liquid = sum(r["value"] for r in rows if r["liquidity"] == "liquid") + portfolio_cash
    deposits = sum(r["value"] for r in rows if r["liquidity"] == "deposit")
    locked = sum(r["value"] for r in rows if r["liquidity"] == "locked")
    return {
        "net_worth": net,
        "market_value": market_value,
        "portfolio_cash": portfolio_cash,
        "other_assets": other,
        "groups": [{"group": g, "value": v, "weight": v / net if net > 0 else None}
                   for g, v in sorted(groups.items(), key=lambda kv: -kv[1])],
        "liquidity": {"cash": liquid, "market": market_value, "deposits": deposits, "locked": locked},
        "protection": {"life_cover": sum(r["cover"] for r in rows), "annual_premium": sum(r["premium"] for r in rows),
                       "policies": sum(1 for r in rows if r["kind"] in ("life_insurance", "term_insurance"))},
        "monthly_contributions": sum(r["monthly_contribution"] for r in rows),
        "maturing_within_90_days": [r for r in rows if r["matures_in_days"] is not None and 0 <= r["matures_in_days"] <= 90],
        "items": rows,
    }


# Asset classes of the market portfolio, grouped for the net-worth view.
_MARKET_GROUP = {"equity": "Equity", "etf": "Equity", "mutual_fund": "Mutual funds", "gold": "Gold",
                 "commodity": "Commodities", "bond": "Bonds"}
