"""Stress testing: market shocks, past crises, Monte Carlo and correlation breakdown."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes import require_token
from app.db.models import Instrument
from app.ledger.positions import EPS, build_positions
from app.market import fx, history, symbols
from app.quant import metrics as qm
from app.quant import service, stress

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])
MIN_DAYS = 60
LONG_START = date(2007, 12, 1)


class StressIn(BaseModel):
    shock_pct: float = Field(default=-15.0, ge=-90, le=100, description="Custom market move in percent: negative for a fall, positive for a rally")
    horizon_days: int = Field(default=21, ge=1, le=252, description="Days over which the move happens")
    simulations: int = Field(default=10_000, ge=1_000, le=50_000)
    history: bool = Field(default=True, description="Replay past crises (downloads long history once)")


def _inr_prices(session: Session, cols: list[str], rates: fx.Rates) -> pd.DataFrame:
    cols = list(dict.fromkeys(cols))   # the benchmark may also be a holding: convert it once
    _, adj = history.load_prices(session, cols)
    for s in cols:
        if s in adj.columns and symbols.fx_pair(rates.ccys.get(s, "INR")):
            r = rates.frame(s, adj.index)
            adj[s] = adj[s] * r if r is not None else np.nan
    return adj


def _at(series: pd.Series, d: date) -> float | None:
    s = series.dropna()
    s = s[s.index <= d]
    return float(s.iloc[-1]) if len(s) else None


def run_stress(session: Session, body: StressIn, fetcher=None) -> dict:
    params = service.get_settings(session)
    bench, lookback = params["benchmark"], int(params["lookback_days"])
    warnings = service.refresh_market(session, bench, fetcher, lookback_days=lookback)
    trades, actions, rates, fx_warn = service.inr_ledger(session)
    warnings += fx_warn
    positions = build_positions(trades, actions)
    held = sorted(s for s, p in positions.items() if p.quantity > EPS)
    if not held:
        raise HTTPException(status_code=409, detail="No holdings to stress yet")
    ccys = fx.currencies(session, held + [bench])
    rates = fx.Rates(session, ccys)
    prices = _inr_prices(session, held + [bench], rates)
    if bench not in prices.columns:
        raise HTTPException(status_code=409, detail=f"No price history for the benchmark {bench}")
    priced = [s for s in held if s in prices.columns and prices[s].notna().any()]
    last = {s: _at(prices[s], date.today()) for s in priced}
    values = np.array([positions[s].quantity * last[s] for s in priced])
    # Same alignment as the RISK tab, so both show the same betas.
    rets = qm.aligned_returns(prices, priced + [bench], bench).tail(lookback)
    if len(rets) < MIN_DAYS:
        raise HTTPException(status_code=409, detail=f"Only {len(rets)} days of overlapping returns; need {MIN_DAYS}")
    asset, market = rets[priced].to_numpy(), rets[bench].to_numpy()
    h = body.horizon_days
    total = float(values.sum())

    shocks = sorted({*stress.DEFAULT_SHOCKS, body.shock_pct / 100})
    shock_rows = [stress.market_shock(values, asset, market, s, h) for s in shocks]
    custom = next(r for r in shock_rows if abs(r["shock"] - body.shock_pct / 100) < 1e-12)
    b = stress.betas(asset, market)

    crises = []
    if body.history:
        for sym in [bench] + [s for s in priced if symbols.namespace(s) != "BOND"]:
            try:
                history.refresh_symbol(session, sym, LONG_START, fetcher=fetcher,
                                       with_actions=not sym.startswith("^"))
            except Exception as exc:
                session.rollback()
                warnings.append(f"Long history unavailable for {sym}: {exc}")
        for pair in fx.fx_symbols({s: c for s, c in ccys.items() if s in priced}):
            try:
                history.refresh_symbol(session, pair, LONG_START, fetcher=fetcher, with_actions=False)
            except Exception:
                session.rollback()
        rates = fx.Rates(session, ccys)
        full = _inr_prices(session, priced + [bench], rates)
        events = [(k, l, a, b, "crash") for k, l, a, b in stress.CRISES] +                  [(k, l, a, b, "rally") for k, l, a, b in stress.RALLIES]
        for key, label, start, end, kind in events:
            m0, m1 = _at(full[bench], start), _at(full[bench], end)
            if not (m0 and m1) or full[bench].dropna().index.min() > start + timedelta(days=7):
                crises.append({"id": key, "label": label, "kind": kind, "start": start.isoformat(),
                               "end": end.isoformat(), "available": False})
                continue
            move = m1 / m0 - 1
            rows, pnl = [], 0.0
            for i, s in enumerate(priced):
                series = full[s].dropna() if s in full.columns else pd.Series(dtype=float)
                if len(series) and series.index.min() <= start + timedelta(days=7):
                    r, how = (_at(series, end) or 0) / (_at(series, start) or 1) - 1, "actual"
                else:
                    r, how = max(b[i] * move, -1.0), "beta"
                rows.append({"symbol": s, "move": r, "pnl": values[i] * r, "method": how})
                pnl += values[i] * r
            crises.append({"id": key, "label": label, "kind": kind, "start": start.isoformat(),
                           "end": end.isoformat(), "available": True, "market_move": move, "pnl": pnl, "pnl_pct": pnl / total,
                           "actual_share": sum(1 for r in rows if r["method"] == "actual") / len(rows),
                           "by_holding": rows})

    names = {i.symbol: i.name for i in session.scalars(select(Instrument).where(Instrument.symbol.in_(priced)))}
    return _clean({
        "as_of": rets.index.max().isoformat(), "observations": len(rets), "benchmark": bench,
        "benchmark_name": params["benchmark_name"] or bench, "portfolio_value": total, "horizon_days": h,
        "portfolio_beta": float((values / total) @ b),
        "shocks": [{k: v for k, v in r.items() if k not in ("by_holding", "moves")} for r in shock_rows],
        "custom": {**{k: v for k, v in custom.items() if k not in ("by_holding", "moves")},
                   "holdings": [{"symbol": s, "name": names.get(s, ""), "value": float(values[i]), "beta": float(b[i]),
                                 "move": custom["moves"][i], "pnl": custom["by_holding"][i]}
                                for i, s in enumerate(priced)]},
        "crises": crises,
        "monte_carlo": stress.monte_carlo(values, asset, h, body.simulations),
        "correlation": stress.correlation_stress(values, asset, float(params["confidence"]), h),
        "unpriced": [s for s in held if s not in priced],
        "warnings": warnings,
    })


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, float | np.floating):
        v = float(obj)
        return v if np.isfinite(v) else None
    if isinstance(obj, np.integer):
        return int(obj)
    return obj


@router.post("/stress")
async def stress_test(body: StressIn, request: Request):
    fetcher = getattr(request.app.state, "price_fetcher", None)

    def run() -> dict:
        with request.app.state.sessionmaker() as s:
            return run_stress(s, body, fetcher)

    return await asyncio.to_thread(run)
