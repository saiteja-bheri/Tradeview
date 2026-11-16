"""What the portfolio could be worth if you keep investing (a SIP), at equal
intervals into the future.

Market part (stocks, ETFs, funds, gold...):
  * Expected return and volatility come either from a market outlook
    (cautious / neutral / optimistic expected returns per asset class, weighted
    by your current mix) or from the portfolio's own past performance (its
    annualised return and volatility over the risk lookback).
  * Each month the SIP is invested first, then the month's return is applied.
    Returns are lognormal, so values cannot go below zero, with the monthly
    drift set so the expected annual return matches the assumption.
  * Thousands of simulated paths give, at every interval, the median (a typical
    outcome) and the 10th and 90th percentiles (a bad and a good case).

Everything else (deposits, PPF, EPF, NPS, pension, insurance fund values) grows
at its own rate with its own monthly contribution, deterministically.

Tax (rates the user enters; nothing is assumed about their slab):
  * Market gains: `tax_gains_pct` on the gain above `gains_exemption` if
    everything were sold at that point. The gain is measured from what was
    actually paid (today's cost basis plus every SIP), so gains already in the
    portfolio are taxed too. Shown as "after tax" next to the pre-tax figures.
  * Interest on cash, fixed and recurring deposits: `tax_interest_pct` is taken
    out of the interest as it is earned, so deposits compound at the after-tax
    rate. PPF, EPF, NPS, pension and insurance values grow untaxed (they are
    tax-exempt or taxed under their own rules, which this does not model).

Deposits at maturity: by default a fixed or recurring deposit is assumed to be
renewed at the same rate when it matures (`renew_deposits`). Otherwise its
value moves to savings at the cash rate from its maturity date.

This is arithmetic on assumptions, not a forecast. Past returns, especially
over a year or two, are a poor guide to the future, which is why the outlook
presets are the default."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
from dateutil.relativedelta import relativedelta

from app.quant import wealth

# Expected annual return and volatility (percent) per asset class, per outlook.
# Long-run figures for Indian markets; they are assumptions, shown to the user.
OUTLOOKS: dict[str, dict[str, tuple[float, float]]] = {
    "cautious": {"equity": (7.0, 16.0), "gold": (5.0, 14.0), "commodity": (3.0, 22.0), "bond": (6.5, 3.0)},
    "neutral": {"equity": (11.0, 16.0), "gold": (8.0, 14.0), "commodity": (6.0, 22.0), "bond": (7.0, 3.0)},
    "optimistic": {"equity": (14.0, 17.0), "gold": (10.0, 14.0), "commodity": (9.0, 22.0), "bond": (7.5, 3.0)},
}
CLASS_GROUP = {"equity": "equity", "etf": "equity", "mutual_fund": "equity", "gold": "gold",
               "commodity": "commodity", "bond": "bond"}
STEPS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def market_assumptions(by_class: dict[str, float], outlook: str, metrics: dict, observations: int) -> dict:
    """Expected annual return and volatility (fractions) for the market part."""
    warnings: list[str] = []
    total = sum(by_class.values())
    weights = ({CLASS_GROUP.get(c, "equity"): 0.0 for c in by_class} if total > 0 else {"equity": 1.0})
    for c, v in by_class.items():
        if total > 0:
            weights[CLASS_GROUP.get(c, "equity")] += v / total
    if outlook == "past":
        ret, vol = metrics.get("return_annualized"), metrics.get("volatility_annualized")
        if ret is None or vol is None or observations < 60:
            warnings.append("Not enough price history for past performance; using the neutral outlook instead")
            outlook = "neutral"
        else:
            if ret > 0.25 or ret < -0.10:
                warnings.append(f"The past {observations} trading days returned {ret:.1%} a year; a run like that "
                                "rarely repeats, so treat this projection with caution")
            elif ret < 0:
                warnings.append(f"The past {observations} trading days lost {abs(ret):.1%} a year; this assumes the "
                                "portfolio keeps losing at that rate every year, which is a bleak case, not a likely one. "
                                "Compare with the outlook presets.")
            return {"source": "past", "expected_return": float(ret), "volatility": float(vol),
                    "per_class": None, "weights": weights, "warnings": warnings}
    table = OUTLOOKS[outlook]
    ret = sum(w * table[g][0] / 100 for g, w in weights.items())
    if metrics.get("volatility_annualized") and observations >= 60:
        vol, vol_source = float(metrics["volatility_annualized"]), "your portfolio's own volatility"
    else:
        vol = sum(w * table[g][1] / 100 for g, w in weights.items())
        vol_source = "typical volatility for each asset class"
    return {"source": outlook, "expected_return": ret, "volatility": vol, "volatility_source": vol_source,
            "per_class": {g: {"expected_return": table[g][0] / 100, "volatility": table[g][1] / 100}
                          for g in weights}, "weights": weights, "warnings": warnings}


TAXED_INTEREST = ("cash", "fixed_deposit", "recurring_deposit")
DEPOSITS = ("fixed_deposit", "recurring_deposit")


def _other_paths(items, months: int, tax_interest_pct: float = 0.0, renew_deposits: bool = True,
                 today: date | None = None) -> np.ndarray:
    """Month-by-month value of the non-market items (deterministic)."""
    today = today or date.today()
    out = np.zeros(months + 1)
    cash_rate = wealth.KINDS["cash"]["rate"]
    for it in items:
        if it.kind == "term_insurance":
            continue
        keep = 1 - tax_interest_pct / 100 if it.kind in TAXED_INTEREST else 1.0
        matures = None
        if it.kind in DEPOSITS and it.maturity_date and not renew_deposits:
            matures = max((it.maturity_date.year - today.year) * 12 + it.maturity_date.month - today.month, 0)
        v = wealth.value_of(it)
        out[0] += v
        for m in range(1, months + 1):
            matured = matures is not None and m > matures
            rate = (cash_rate if matured else wealth.rate_of(it)) / 100 / 12 * keep
            v = v * (1 + rate) + (0.0 if matured else it.monthly_contribution)
            out[m] += v
    return out


def after_tax(value: float, cost: float, rate_pct: float, exemption: float) -> float:
    """Value left if sold: tax at `rate_pct` on the gain above `exemption`."""
    gain = value - cost - exemption
    return value - rate_pct / 100 * gain if gain > 0 else value


def project(*, start_value: float, by_class: dict[str, float], metrics: dict, observations: int,
            monthly_sip: float, step_up_pct: float, years: int, interval: str, outlook: str,
            wealth_items, simulations: int = 5000, risk_free: float = 0.065, seed: int = 11,
            start_cost: float | None = None, tax_gains_pct: float = 0.0, gains_exemption: float = 0.0,
            tax_interest_pct: float = 0.0, renew_deposits: bool = True) -> dict:
    a = market_assumptions(by_class, outlook, metrics, observations)
    mu, sigma = a["expected_return"], max(a["volatility"], 1e-6)
    months = years * 12
    sig_m = sigma / math.sqrt(12)
    drift_m = math.log(1 + mu) / 12 - sig_m ** 2 / 2       # so E[growth over a year] = 1 + mu
    rng = np.random.default_rng(seed)
    shocks = rng.normal(drift_m, sig_m, size=(simulations, months))
    growth = np.exp(shocks)

    values = np.full(simulations, float(start_value))
    expected = float(start_value)
    invested = float(start_value)
    cost = float(start_value if start_cost is None else start_cost)   # what was actually paid, for tax
    sip = float(monthly_sip)
    step = STEPS[interval]
    other = _other_paths(wealth_items, months, tax_interest_pct, renew_deposits)
    other_contrib = sum(it.monthly_contribution for it in wealth_items if it.kind != "term_insurance")
    other_invested = float(other[0])
    today = date.today()

    def point(m: int) -> dict:
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        tx = lambda v: after_tax(float(v), cost, tax_gains_pct, gains_exemption)  # noqa: E731
        return {"month": m, "date": (today + relativedelta(months=m)).isoformat(),
                "invested": invested, "cost": cost, "expected": expected,
                "p10": float(p10), "p50": float(p50), "p90": float(p90),
                "p10_after_tax": tx(p10), "p50_after_tax": tx(p50), "p90_after_tax": tx(p90),
                "other": float(other[m]), "other_invested": other_invested,
                "total_p10": float(p10 + other[m]), "total_p50": float(p50 + other[m]),
                "total_p90": float(p90 + other[m]),
                "total_p50_after_tax": tx(p50) + float(other[m])}

    points = [point(0)]
    for m in range(1, months + 1):
        if m > 1 and (m - 1) % 12 == 0:
            sip *= 1 + step_up_pct / 100                    # step-up once a year
        values = (values + sip) * growth[:, m - 1]
        expected = (expected + sip) * (1 + mu) ** (1 / 12)
        invested += sip
        cost += sip
        other_invested += other_contrib
        if m % step == 0:
            points.append(point(m))

    final = points[-1]
    added = final["invested"] - start_value

    def cagr(end: float) -> float | None:
        """Money-weighted annual return that turns the contributions into `end`."""
        flows = [(0, -start_value)] if start_value > 0 else []
        s = float(monthly_sip)
        for m in range(months):
            if m > 0 and m % 12 == 0:
                s *= 1 + step_up_pct / 100
            flows.append((m, -s))
        flows.append((months, end))
        lo, hi = -0.99, 2.0
        f = lambda r: sum(cf / (1 + r) ** (t / 12) for t, cf in flows)  # noqa: E731
        if f(lo) * f(hi) > 0:
            return None
        for _ in range(100):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
        return (lo + hi) / 2

    return {
        "assumptions": {**{k: v for k, v in a.items() if k != "warnings"}, "risk_free_rate": risk_free,
                        "monthly_sip": monthly_sip, "step_up_pct": step_up_pct, "years": years,
                        "interval": interval, "start_value": start_value, "simulations": simulations,
                        "start_cost": float(start_value if start_cost is None else start_cost),
                        "tax_gains_pct": tax_gains_pct, "gains_exemption": gains_exemption,
                        "tax_interest_pct": tax_interest_pct, "renew_deposits": renew_deposits},
        "points": points,
        "summary": {
            "invested_total": final["invested"], "added_by_sip": added,
            "median": final["p50"], "bad_case": final["p10"], "good_case": final["p90"],
            "expected": final["expected"],
            "median_annual_return": cagr(final["p50"]),
            "chance_below_invested": float((values < final["invested"]).mean()),
            "other_assets": final["other"], "total_median": final["total_p50"],
            "median_after_tax": final["p50_after_tax"], "bad_case_after_tax": final["p10_after_tax"],
            "good_case_after_tax": final["p90_after_tax"],
            "tax_on_median": final["p50"] - final["p50_after_tax"],
            "median_annual_return_after_tax": cagr(final["p50_after_tax"]),
            "total_median_after_tax": final["total_p50_after_tax"],
        },
        "warnings": a["warnings"],
    }
