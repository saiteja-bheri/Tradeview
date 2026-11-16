"""How much a market downturn would cost the portfolio.

Four views, all from the same daily return history (in rupees) that drives
the risk metrics:

1. Market shock. If the benchmark falls by X% over a horizon, each holding's
   expected move is its beta times X: the conditional expectation when returns
   are jointly normal, E[r_i | r_m = X] = beta_i * X. The spread around that
   comes from the covariance left once the market move is known,
   Var(r_p | r_m) = w'Sw - (w'Sm)^2 / s_m^2, scaled to the horizon.
2. Historical replay. The benchmark's actual fall in past crises; each holding
   takes its own actual move when its price history covers the window, and
   beta times the market's move when it does not.
3. Monte Carlo. Many simulated horizons drawn from the covariance matrix with
   fat tails (Student t, 5 degrees of freedom, scaled to the same covariance),
   so large losses are as likely as markets have shown them to be.
4. Correlation breakdown. In crashes, correlations rise and diversification
   fails. VaR is recomputed with every pairwise correlation moved halfway to 1.

Each view covers both directions: market rallies as well as falls, past bull
runs as well as crashes, and the good tail of the simulations as well as the
bad one. None of these is a forecast: they describe what the past relationships
between your holdings imply."""
from __future__ import annotations

import math
from datetime import date

import numpy as np
from scipy.stats import norm

CRISES = (
    ("gfc", "2008 global financial crisis", date(2008, 1, 8), date(2008, 10, 27)),
    ("taper", "2013 taper tantrum", date(2013, 5, 20), date(2013, 8, 28)),
    ("china", "2015-16 China slowdown", date(2015, 3, 3), date(2016, 2, 29)),
    ("covid", "2020 COVID crash", date(2020, 1, 17), date(2020, 3, 23)),
    ("rates", "2022 rate-hike sell-off", date(2021, 10, 18), date(2022, 6, 17)),
)
# Rallies, replayed the same way, for the upside view.
RALLIES = (
    ("recovery09", "2009 post-crisis recovery", date(2009, 3, 9), date(2010, 11, 5)),
    ("election14", "2014 election rally", date(2013, 8, 28), date(2015, 3, 3)),
    ("covidrally", "2020-21 post-COVID rally", date(2020, 3, 23), date(2021, 10, 18)),
    ("rally23", "2023-24 rally", date(2023, 3, 28), date(2024, 9, 26)),
)
DEFAULT_SHOCKS = (-0.40, -0.30, -0.20, -0.10, -0.05, 0.05, 0.10, 0.20, 0.30, 0.40)


def betas(asset: np.ndarray, market: np.ndarray) -> np.ndarray:
    var_m = float(np.var(market, ddof=1))
    if var_m <= 0:
        return np.zeros(asset.shape[1])
    m = market - market.mean()
    return ((asset - asset.mean(axis=0)).T @ m) / (len(m) - 1) / var_m


def market_shock(values: np.ndarray, asset: np.ndarray, market: np.ndarray, shock: float,
                 horizon: int) -> dict:
    """Expected rupee P&L for a market move of `shock`, with a 90% band."""
    b = betas(asset, market)
    moves = np.clip(b * shock, -1.0, None)
    pnl = values * moves
    total = float(values.sum())
    w = values / total
    cov = np.cov(np.column_stack([asset, market]), rowvar=False, ddof=1) * horizon
    s_aa, s_am, s_mm = cov[:-1, :-1], cov[:-1, -1], cov[-1, -1]
    var_cond = float(w @ s_aa @ w - (w @ s_am) ** 2 / s_mm) if s_mm > 0 else float(w @ s_aa @ w)
    sd = total * math.sqrt(max(var_cond, 0.0))
    z = float(norm.ppf(0.95))
    exp = float(pnl.sum())
    return {"shock": shock, "pnl": exp, "pnl_pct": exp / total, "low": exp - z * sd, "high": exp + z * sd,
            "beta": float(w @ b), "by_holding": [float(x) for x in pnl], "moves": [float(x) for x in moves]}


def monte_carlo(values: np.ndarray, asset: np.ndarray, horizon: int, n: int = 10_000,
                df: int = 5, seed: int = 7) -> dict:
    """Distribution of rupee P&L over `horizon` days: zero mean (no assumed drift),
    covariance from history, Student-t tails."""
    total = float(values.sum())
    cov = np.cov(asset, rowvar=False, ddof=1) * horizon
    cov = np.atleast_2d(cov)
    try:
        chol = np.linalg.cholesky(cov + np.eye(len(cov)) * 1e-12)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(cov)
        chol = vecs @ np.diag(np.sqrt(np.clip(vals, 0, None)))
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, len(cov)))
    scale = np.sqrt(df / rng.chisquare(df, size=(n, 1))) * math.sqrt((df - 2) / df)  # unit-variance t
    rets = np.clip((z * scale) @ chol.T, -1.0, None)
    pnl = rets @ values
    pct = np.percentile(pnl, [1, 5, 25, 50, 75, 95, 99])
    es95 = float(pnl[pnl <= pct[1]].mean())
    es99 = float(pnl[pnl <= pct[0]].mean())
    eg95 = float(pnl[pnl >= pct[5]].mean())   # average of the best 5%
    counts, edges = np.histogram(pnl, bins=40)
    return {
        "simulations": n, "horizon_days": horizon,
        "percentiles": {k: float(v) for k, v in zip(("p1", "p5", "p25", "p50", "p75", "p95", "p99"), pct)},
        "expected_shortfall_95": es95, "expected_shortfall_99": es99, "expected_gain_95": eg95,
        "prob_loss": {f"{int(t * 100)}": float((pnl <= -t * total).mean()) for t in (0.05, 0.10, 0.20, 0.30)},
        "prob_gain": {f"{int(t * 100)}": float((pnl >= t * total).mean()) for t in (0.05, 0.10, 0.20, 0.30)},
        "histogram": {"edges": [float(e) for e in edges], "counts": [int(c) for c in counts]},
    }


def correlation_stress(values: np.ndarray, asset: np.ndarray, confidence: float, horizon: int,
                       pull: float = 0.5) -> dict:
    """Parametric VaR with historical correlations, and with every correlation moved `pull` of the way to 1."""
    total = float(values.sum())
    w = values / total
    cov = np.atleast_2d(np.cov(asset, rowvar=False, ddof=1))
    sd = np.sqrt(np.diag(cov))
    corr = cov / np.outer(sd, sd)
    stressed = corr + (1 - corr) * pull
    np.fill_diagonal(stressed, 1.0)
    z = float(norm.ppf(confidence))

    def var(c: np.ndarray) -> float:
        cv = c * np.outer(sd, sd)
        return total * z * math.sqrt(max(float(w @ cv @ w), 0.0)) * math.sqrt(horizon)

    n = len(w)
    off = corr[~np.eye(n, dtype=bool)] if n > 1 else np.array([1.0])
    return {"confidence": confidence, "horizon_days": horizon, "var_normal": var(corr), "var_stressed": var(stressed),
            "avg_correlation": float(off.mean()), "avg_correlation_stressed": float((off + (1 - off) * pull).mean())}
