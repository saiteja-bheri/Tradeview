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
            # The past figure is a compound (geometric) growth rate. The simulation
            # takes the expected (arithmetic) return, whose median growth is
            # (1 + mu) * exp(-sigma^2 / 2); reproducing the past compound rate on the
            # likely path therefore needs mu = (1 + g) * exp(sigma^2 / 2) - 1.
            # Feeding g in directly understated every year by about sigma^2 / 2.
            mu = (1 + float(ret)) * math.exp(float(vol) ** 2 / 2) - 1
            return {"source": "past", "expected_return": mu, "past_compound_return": float(ret),
                    "volatility": float(vol), "per_class": None, "weights": weights, "warnings": warnings}
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
                 today: date | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Month-by-month value of the non-market items (deterministic), and the
    money put into them (today's value plus contributions actually made: a
    deposit that has matured into savings takes no more instalments)."""
    today = today or date.today()
    out = np.zeros(months + 1)
    put_in = np.zeros(months + 1)
    cash_rate = wealth.KINDS["cash"]["rate"]
    for it in items:
        if it.kind == "term_insurance":
            continue
        keep = 1 - tax_interest_pct / 100 if it.kind in TAXED_INTEREST else 1.0
        matures = None
        if it.kind in DEPOSITS and it.maturity_date and not renew_deposits:
            matures = max((it.maturity_date.year - today.year) * 12 + it.maturity_date.month - today.month, 0)
        v = wealth.value_of(it)
        paid = v
        out[0] += v
        put_in[0] += v
        for m in range(1, months + 1):
            matured = matures is not None and m > matures
            rate = (cash_rate if matured else wealth.rate_of(it)) / 100 / 12 * keep
            add = 0.0 if matured else it.monthly_contribution
            v = v * (1 + rate) + add
            paid += add
            out[m] += v
            put_in[m] += paid
    return out, put_in


def after_tax(value: float, cost: float, rate_pct: float, exemption: float) -> float:
    """Value left if sold: tax at `rate_pct` on the gain above `exemption`."""
    gain = value - cost - exemption
    return value - rate_pct / 100 * gain if gain > 0 else value


# How often the SIP is paid: instalments per year. Daily SIPs run on market
# days, about 250 a year in India; the rest are calendar schedules.
SIP_FREQUENCIES: dict[str, int] = {
    "daily": 250, "weekly": 52, "monthly": 12, "bimonthly": 6, "quarterly": 4, "halfyearly": 2, "yearly": 1,
}


def sip_schedule(amount: float, frequency: str, years: int, step_up_pct: float) -> list[tuple[float, float]]:
    """[(time in months from today, rupees)] for every instalment. The first is
    paid today; the amount steps up once a year (instalments in year 2 pay
    amount x (1 + step-up), and so on)."""
    per_year = SIP_FREQUENCIES[frequency]
    gap = 12 / per_year
    out = []
    for j in range(per_year * years):
        t = j * gap
        out.append((t, amount * (1 + step_up_pct / 100) ** int(t / 12 + 1e-9)))
    return out


def _grown(shock: np.ndarray, amts: np.ndarray, fracs: np.ndarray) -> np.ndarray:
    """Per path, sum of amt_k * exp(shock * frac_k): each instalment grown by the
    rest of the month. Daily and weekly instalments within a month are equal and
    evenly spaced, so the sum is a geometric series with a closed form, which
    keeps a 25-year daily plan fast. Anything else is summed directly."""
    n = len(amts)
    d = fracs[0] - fracs[1] if n > 1 else 0.0
    if n > 2 and np.allclose(amts, amts[0]) and np.allclose(np.diff(fracs), -d):
        x = -shock * d                                   # ratio between consecutive terms is exp(x)
        with np.errstate(divide="ignore", invalid="ignore"):
            series = np.where(np.abs(x) > 1e-12, np.expm1(x * n) / np.expm1(x), float(n))
        return amts[0] * np.exp(shock * fracs[0]) * series
    return np.exp(np.outer(shock, fracs)) @ amts


def project(*, start_value: float, by_class: dict[str, float], metrics: dict, observations: int,
            monthly_sip: float, step_up_pct: float, years: int, interval: str, outlook: str,
            wealth_items, simulations: int = 5000, risk_free: float = 0.065, seed: int = 11,
            start_cost: float | None = None, tax_gains_pct: float = 0.0, gains_exemption: float = 0.0,
            tax_interest_pct: float = 0.0, renew_deposits: bool = True,
            sip_amount: float | None = None, sip_frequency: str = "monthly") -> dict:
    """`sip_amount` is paid every `sip_frequency` (daily, weekly, monthly,
    bimonthly = every 2 months, quarterly, halfyearly, yearly). Without it,
    `monthly_sip` is paid monthly (the original behaviour)."""
    if sip_amount is None:
        sip_amount, sip_frequency = monthly_sip, "monthly"
    if sip_frequency not in SIP_FREQUENCIES:
        raise ValueError(f"sip_frequency must be one of {', '.join(SIP_FREQUENCIES)}")
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
    schedule = sip_schedule(float(sip_amount), sip_frequency, years, step_up_pct)
    # Instalments by the month they fall in (1-based), with the share of that
    # month still to run once they are invested: a payment at the start of a
    # month earns the whole month's return, one mid-month about half of it.
    by_month: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for t, amt in schedule:
        m = int(math.floor(t + 1e-9)) + 1
        amts, fracs = by_month.get(m, ([], []))
        amts.append(amt)
        fracs.append(m - t)
        by_month[m] = (amts, fracs)
    by_month = {m: (np.array(a_), np.array(f_)) for m, (a_, f_) in by_month.items()}
    step = STEPS[interval]
    other, other_put_in = _other_paths(wealth_items, months, tax_interest_pct, renew_deposits)
    today = date.today()

    def point(m: int) -> dict:
        p10, p50, p90 = np.percentile(values, [10, 50, 90])
        tx = lambda v: after_tax(float(v), cost, tax_gains_pct, gains_exemption)  # noqa: E731
        return {"month": m, "date": (today + relativedelta(months=m)).isoformat(),
                "invested": invested, "cost": cost, "expected": expected,
                "p10": float(p10), "p50": float(p50), "p90": float(p90),
                "p10_after_tax": tx(p10), "p50_after_tax": tx(p50), "p90_after_tax": tx(p90),
                "other": float(other[m]), "other_invested": float(other_put_in[m]),
                "total_p10": float(p10 + other[m]), "total_p50": float(p50 + other[m]),
                "total_p90": float(p90 + other[m]),
                "total_p50_after_tax": tx(p50) + float(other[m])}

    points = [point(0)]
    monthly_growth = (1 + mu) ** (1 / 12)
    for m in range(1, months + 1):
        g = growth[:, m - 1]
        amts, fracs = by_month.get(m, (np.empty(0), np.empty(0)))
        if amts.size and np.allclose(fracs, 1.0):
            values = (values + amts.sum()) * g              # paid at the month's start: the full month
        elif amts.size:
            # Each instalment grows by the part of this month's move still to come
            # (the month's log-return spread evenly across it).
            values = values * g + _grown(shocks[:, m - 1], amts, fracs)
        else:
            values = values * g
        expected = expected * monthly_growth + float((amts * monthly_growth ** fracs).sum())
        paid = float(amts.sum())
        invested += paid
        cost += paid
        if m % step == 0:
            points.append(point(m))

    final = points[-1]
    added = final["invested"] - start_value
    flow_t = np.array(([0.0] if start_value > 0 else []) + [t for t, _ in schedule] + [float(months)])
    flow_base = np.array(([-float(start_value)] if start_value > 0 else []) + [-amt for _, amt in schedule] + [0.0])

    def cagr(end: float) -> float | None:
        """Money-weighted annual return that turns the contributions into `end`."""
        cf = flow_base.copy()
        cf[-1] = end
        lo, hi = -0.99, 2.0
        f = lambda r: float((cf / (1 + r) ** (flow_t / 12)).sum())  # noqa: E731
        if f(lo) * f(hi) > 0:
            return None
        for _ in range(100):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
        return (lo + hi) / 2

    per_year = SIP_FREQUENCIES[sip_frequency]

    return {
        "assumptions": {**{k: v for k, v in a.items() if k != "warnings"}, "risk_free_rate": risk_free,
                        "monthly_sip": float(sip_amount) * per_year / 12,   # the same money spread per month
                        "sip_amount": float(sip_amount), "sip_frequency": sip_frequency,
                        "installments_per_year": per_year, "sip_first_year": float(sip_amount) * per_year,
                        "installments": len(schedule), "step_up_pct": step_up_pct, "years": years,
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
