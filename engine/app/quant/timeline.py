"""Portfolio value and net worth day by day, for the PERFORMANCE tab.

For each day in the period:
  market value   shares held that day x that day's close, in rupees at that
                 day's exchange rate. Yahoo's closes are adjusted for later
                 splits, so the shares are counted in the same adjusted terms:
                 shares held x the splits and bonuses still to come (a split
                 marked as already in the uploaded file is not counted twice).
  cash           portfolio cash: dividends, coupons and sale proceeds, less purchases
                 paid from it and recorded withdrawals (see app.quant.cashflow)
  money in       new money put in from outside, less withdrawals
  gain           market value + cash - money in
  other wealth   cash, deposits, pension and insurance. Only fixed deposits have
                 a known past (they accrue from their start date); everything
                 else is counted at today's value from its start date (or from
                 when it was entered), because its past balances are unknown.
  benchmark      the benchmark index, rebased to the portfolio's value on the
                 first day it held anything, for comparison.

Uses only cached prices; refreshing prices fills any gaps."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CorporateAction, Instrument, WealthItem
from app.market import history, symbols
from app.quant import cashflow, service, wealth

FACTOR_KINDS = ("split", "bonus")


def build(session: Session, start: date | None = None, end: date | None = None) -> dict:
    end = end or date.today()
    trades, _, rates, warnings = service.inr_ledger(session)
    raw_trades = sorted(trades, key=lambda t: t.traded_at)
    params = service.get_settings(session)
    bench = params["benchmark"]
    if not raw_trades:
        return {"dates": [], "series": {}, "warnings": ["No trades in the ledger yet"], "benchmark": bench}

    first = raw_trades[0].traded_at.date()
    start = max(start or first, first)
    syms = sorted({t.symbol for t in raw_trades})
    close, _ = history.load_prices(session, syms + [bench])
    if close.empty:
        return {"dates": [], "series": {}, "warnings": ["No cached prices yet; refresh prices first"], "benchmark": bench}

    index = [d for d in close.index if start <= d <= end]
    if not index:
        return {"dates": [], "series": {}, "warnings": ["No prices in this period"], "benchmark": bench}
    close = close.reindex(sorted(set(close.index) | set(index))).ffill().reindex(index)

    # Prices in rupees, day by day.
    for s in syms:
        if s in close.columns and symbols.fx_pair(rates.ccys.get(s, "INR")):
            r = rates.frame(s, close.index)
            close[s] = close[s] * r if r is not None else np.nan

    actions = session.scalars(select(CorporateAction).where(CorporateAction.kind.in_(FACTOR_KINDS))).all()
    splits: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for a in actions:
        if a.review != "skip" and a.value > 0:
            splits[a.symbol].append((a.ex_date, a.value))

    classes = {i.symbol: (i.asset_class or symbols.asset_class(i.symbol, i.name or ""))
               for i in session.scalars(select(Instrument).where(Instrument.symbol.in_(syms)))}
    n = len(index)
    market = np.zeros(n)
    invested = np.zeros(n)
    by_class: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(n))
    missing: set[str] = set()

    by_sym: dict[str, list] = defaultdict(list)
    for t in raw_trades:
        by_sym[t.symbol].append(t)
    cash_events = cashflow.events(session)
    cash = np.zeros(n)
    j, c, m_in = 0, 0.0, 0.0
    for k, d in enumerate(index):
        while j < len(cash_events) and cash_events[j]["date"] <= d:
            c, m_in = cash_events[j]["cash"], cash_events[j]["money_in"]
            j += 1
        cash[k], invested[k] = c, m_in

    for s, ts in by_sym.items():
        if s not in close.columns or close[s].isna().all():
            missing.add(s)
            continue
        events = sorted([(t.traded_at.date(), 1, t) for t in ts] + [(d, 0, f) for d, f in splits.get(s, [])],
                        key=lambda e: (e[0], e[1]))
        future = sorted(splits.get(s, []))
        shares, ei = 0.0, 0
        prices = close[s].to_numpy()
        cls = classes.get(s, symbols.asset_class(s))
        for k, d in enumerate(index):
            while ei < len(events) and events[ei][0] <= d:
                _, kind, ev = events[ei]
                if kind == 0:
                    shares *= ev                      # split / bonus on its ex-date
                else:
                    shares += ev.quantity if ev.side == "BUY" else -ev.quantity
                ei += 1
            later = np.prod([f for ex, f in future if ex > d]) if future else 1.0
            p = prices[k]
            if shares > 1e-9 and np.isfinite(p):
                v = shares * later * p
                market[k] += v
                by_class[cls][k] += v

    groups: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(n))
    for it in session.scalars(select(WealthItem)):
        if it.kind == "term_insurance":
            continue
        group = wealth.KINDS.get(it.kind, {}).get("group", "Other")
        since = it.start_date or (it.updated_at.date() if it.updated_at else date.today())
        for k, d in enumerate(index):
            if d >= since:
                groups[group][k] += wealth.value_of(it, d) if it.kind == "fixed_deposit" else it.amount

    other = sum(groups.values()) if groups else np.zeros(n)
    bench_series = None
    if bench in close.columns and close[bench].notna().any():
        b = close[bench].to_numpy()
        first_k = next((k for k in range(n) if market[k] > 0 and np.isfinite(b[k])), None)
        if first_k is not None:
            bench_series = b / b[first_k] * market[first_k]
            bench_series[:first_k] = np.nan

    if missing:
        warnings.append(f"No cached prices for {', '.join(sorted(missing))}; left out of the graph")

    clean = lambda a: [None if a is None or not np.isfinite(x) else round(float(x), 2) for x in a]  # noqa: E731
    return {
        "dates": [d.isoformat() for d in index],
        "series": {
            "market": clean(market),
            "invested": clean(invested),
            "cash": clean(cash),
            "gain": clean(market + cash - invested),
            "other_wealth": clean(other),
            "net_worth": clean(market + cash + other),
            "benchmark": clean(bench_series) if bench_series is not None else None,
        },
        "by_class": {c: clean(v) for c, v in by_class.items() if v.any()},
        "wealth_groups": {g: clean(v) for g, v in groups.items() if v.any()},
        "benchmark": bench,
        "benchmark_name": params["benchmark_name"] or bench,
        "warnings": warnings,
    }
