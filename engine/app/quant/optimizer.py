"""Mean-variance (Markowitz) portfolio optimisation for the starred stocks.

Inputs are daily returns in rupees (international holdings include the
currency move), annualised over 252 trading days.

  * Covariance: Ledoit-Wolf shrinkage towards a scaled identity. Sample
    covariance from a year of data is noisy and pushes the optimiser to
    extreme weights; shrinkage is the standard fix.
  * Expected returns: the historical mean. This is the weakest input in any
    Markowitz model (past returns predict future ones poorly), so the minimum-
    variance portfolio, which does not use expected returns at all, is shown
    beside the maximum-Sharpe one.
  * Constraints: fully invested, long-only, and at most `max_weight` in any one
    stock, which keeps the answer diversified and closer to something investable.

Outputs: the maximum-Sharpe (tangency) portfolio, the minimum-variance
portfolio, an equal-weight reference, your current mix of the same stocks
when you hold them, and the efficient frontier."""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize

TRADING_DAYS = 252


def ledoit_wolf(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Shrunk covariance of the rows of x (observations x assets) and the shrinkage used."""
    n, p = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / n
    mu = np.trace(s) / p
    target = mu * np.eye(p)
    d2 = np.sum((s - target) ** 2)
    if d2 <= 0:
        return s, 0.0
    b2 = sum(np.sum((np.outer(row, row) - s) ** 2) for row in x) / n ** 2
    shrink = min(b2, d2) / d2
    return shrink * target + (1 - shrink) * s, float(shrink)


def _stats(w: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float) -> dict:
    ret = float(w @ mu)
    vol = float(math.sqrt(max(w @ cov @ w, 0.0)))
    return {"return": ret, "volatility": vol, "sharpe": (ret - rf) / vol if vol > 0 else None}


def _solve(objective, n: int, cap: float, extra=(), floor: float = 0.0) -> np.ndarray | None:
    w0 = np.full(n, 1.0 / n)
    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}, *extra]
    res = minimize(objective, w0, method="SLSQP", bounds=[(floor, cap)] * n, constraints=cons,
                   options={"maxiter": 500, "ftol": 1e-12})
    if not res.success:
        return None
    w = np.clip(res.x, floor, cap)
    return w / w.sum()


def optimise(daily_returns: np.ndarray, symbols: list[str], rf: float, max_weight: float,
             current: dict[str, float] | None = None, frontier_points: int = 24,
             min_weight: float = 0.0, target_return: float | None = None,
             target_volatility: float | None = None) -> dict:
    """`min_weight` / `max_weight` bound every stock's weight. `target_return`
    (annual) adds the lowest-risk mix earning that much; `target_volatility`
    (annual) adds the highest-return mix within that risk. Either lands in
    portfolios["target"] when reachable."""
    n = len(symbols)
    cap = max(max_weight, 1.0 / n)   # a cap below 1/n cannot be fully invested
    floor = min(max(min_weight, 0.0), 1.0 / n)   # nor can a floor above 1/n
    floor = min(floor, cap)
    cov_daily, shrink = ledoit_wolf(daily_returns)
    cov = cov_daily * TRADING_DAYS
    mu = daily_returns.mean(axis=0) * TRADING_DAYS

    def pack(w: np.ndarray | None) -> dict | None:
        if w is None:
            return None
        out = _stats(w, mu, cov, rf)
        out["weights"] = {s: float(round(x, 6)) for s, x in zip(symbols, w)}
        return out

    def solve(objective, extra=()):
        return _solve(objective, n, cap, extra, floor)

    w_min = solve(lambda w: w @ cov @ w)

    def neg_sharpe(w):
        vol = math.sqrt(max(w @ cov @ w, 1e-18))
        return -(w @ mu - rf) / vol

    w_sharpe = solve(neg_sharpe)
    w_top = solve(lambda w: -(w @ mu))          # highest return reachable under the bounds

    frontier = []
    lo = float(w_min @ mu) if w_min is not None else None
    hi = float(w_top @ mu) if w_top is not None else None
    if lo is not None and hi is not None:
        for target in np.linspace(lo, max(hi, lo), frontier_points):
            w = solve(lambda w: w @ cov @ w,
                      extra=[{"type": "eq", "fun": lambda w, t=target: w @ mu - t}])
            if w is not None:
                s = _stats(w, mu, cov, rf)
                frontier.append({"return": s["return"], "volatility": s["volatility"], "sharpe": s["sharpe"],
                                 "weights": {sym: float(round(x, 6)) for sym, x in zip(symbols, w)}})

    target = None
    target_note = None
    if target_return is not None and lo is not None and hi is not None:
        if lo - 1e-9 <= target_return <= hi + 1e-9:
            target = solve(lambda w: w @ cov @ w,
                           extra=[{"type": "eq", "fun": lambda w: w @ mu - target_return}])
        else:
            target_note = (f"Target return {target_return:.1%} is outside what these stocks reached "
                           f"under the weight limits ({lo:.1%} to {hi:.1%})")
    elif target_volatility is not None and w_min is not None:
        floor_vol = _stats(w_min, mu, cov, rf)["volatility"]
        if target_volatility + 1e-9 >= floor_vol:
            target = solve(lambda w: -(w @ mu),
                           extra=[{"type": "ineq", "fun": lambda w: target_volatility ** 2 - w @ cov @ w}])
        else:
            target_note = (f"Target volatility {target_volatility:.1%} is below the lowest reachable "
                           f"({floor_vol:.1%})")

    portfolios = {
        "max_sharpe": pack(w_sharpe),
        "min_variance": pack(w_min),
        "equal_weight": pack(np.full(n, 1.0 / n)),
    }
    if target is not None:
        portfolios["target"] = pack(target)
    if current:
        w = np.array([current.get(s, 0.0) for s in symbols])
        if w.sum() > 0:
            portfolios["current"] = pack(w / w.sum())
    assets = []
    for i, s in enumerate(symbols):
        vol = math.sqrt(cov[i, i])
        assets.append({"symbol": s, "return": float(mu[i]), "volatility": vol,
                       "sharpe": (float(mu[i]) - rf) / vol if vol > 0 else None})
    return {"portfolios": portfolios, "frontier": frontier, "assets": assets,
            "shrinkage": shrink, "max_weight": cap, "min_weight": floor, "target_note": target_note}
