"""Glue between the database and the pure maths: loads the ledger, refreshes
prices, and assembles the JSON payload the UI consumes."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import BENCHMARK_NAMES, DEFAULT_SETTINGS, DISPLAY_CURRENCIES, INSIGHT_WINDOWS
from types import SimpleNamespace

from app.db.models import (Bond, BrokerHolding, CorporateAction, Instrument, Setting, Trade,
                           Watch)
from app.ledger import review
from app.ledger.positions import EPS, Position, build_positions, clip_oversells
from app.market import fx, history, symbols
from app.quant import metrics as qm
from app.quant import returns

MIN_OBSERVATIONS = 30
MIN_LOOKBACK_DAYS = 21     # one month; the RISK tab offers 1M
MAX_LOOKBACK_DAYS = 2520   # ten years of trading days
MAX_HORIZON_DAYS = 60      # VaR horizon
MAX_COV_HORIZON_DAYS = 252  # covariance horizon: up to a year of compounded returns
_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9^&_.=-]{0,29}$")


def _f(x) -> float | None:
    x = float(x)
    return x if math.isfinite(x) else None


def get_settings(session: Session) -> dict:
    out = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        row = session.get(Setting, key)
        if row is not None:
            out[key] = type(default)(row.value)
    if not out["benchmark_name"]:
        out["benchmark_name"] = BENCHMARK_NAMES.get(out["benchmark"], out["benchmark"])
    return out


def validate_settings(values: dict) -> dict:
    clean: dict = {}
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS or value is None:
            continue
        value = type(DEFAULT_SETTINGS[key])(value)
        if key == "benchmark":
            value = value.strip().upper()
            if not _SYMBOL.match(value):
                raise ValueError("benchmark must be a Yahoo Finance symbol, e.g. ^CRSLDX or NIFTYBEES.NS")
        if key == "benchmark_name":
            value = " ".join(value.split())[:80]
        if key == "confidence" and not 0.5 < value < 1:
            raise ValueError("confidence must be between 0.5 and 1 (e.g. 0.95 or 0.99)")
        if key == "horizon_days" and not 1 <= value <= MAX_HORIZON_DAYS:
            raise ValueError(f"{key} must be between 1 and {MAX_HORIZON_DAYS}")
        if key == "cov_horizon_days" and not 1 <= value <= MAX_COV_HORIZON_DAYS:
            raise ValueError(f"{key} must be between 1 and {MAX_COV_HORIZON_DAYS}")
        if key == "lookback_days" and not MIN_LOOKBACK_DAYS <= value <= MAX_LOOKBACK_DAYS:
            raise ValueError(f"lookback_days must be between {MIN_LOOKBACK_DAYS} and {MAX_LOOKBACK_DAYS}")
        if key == "cov_lookback_days" and value != 0 and not 60 <= value <= MAX_LOOKBACK_DAYS:
            raise ValueError(f"cov_lookback_days must be 0 (same as lookback_days) or 60 to {MAX_LOOKBACK_DAYS}")
        if key == "display_currency":
            value = value.strip().upper()
            if value not in DISPLAY_CURRENCIES:
                raise ValueError(f"display_currency must be one of {', '.join(DISPLAY_CURRENCIES)}")
        if key == "insight_frequency" and value not in INSIGHT_WINDOWS:
            raise ValueError("insight_frequency must be hourly or daily")
        if key == "risk_free_rate" and not 0 <= value < 1:
            raise ValueError("risk_free_rate is an annual fraction, e.g. 0.065")
        clean[key] = value
    # A new benchmark without a name must not keep the previous benchmark's name.
    if "benchmark" in clean and not clean.get("benchmark_name"):
        clean["benchmark_name"] = BENCHMARK_NAMES.get(clean["benchmark"], clean["benchmark"])
    return clean


def save_settings(session: Session, values: dict) -> dict:
    for key, value in validate_settings(values).items():
        row = session.get(Setting, key)
        if row:
            row.value = str(value)
        else:
            session.add(Setting(key=key, value=str(value)))
    session.commit()
    return get_settings(session)


def inr_ledger(session: Session):
    """Trades and corporate actions with every amount in rupees. International
    trades are costed at the FX rate on their trade date and their dividends
    at the rate on the ex-date. Returns (trades, actions, rates, warnings).

    Every reader of the ledger (positions, cash, returns, timeline, stress, the
    live hub) comes through here, so a sale larger than the holding is capped
    once, here: the unbacked excess never becomes cash or a return."""
    trades = session.scalars(select(Trade)).all()
    actions = session.scalars(select(CorporateAction)).all()
    trades, oversold = clip_oversells(trades, actions)
    trades = [t for t in trades if t.traded_at.date() <= date.today()]   # never count a future-dated row
    ccys = fx.currencies(session, sorted({t.symbol for t in trades}))
    rates = fx.Rates(session, ccys)
    foreign = {s for s, c in ccys.items() if symbols.fx_pair(c)}
    if not foreign:
        return trades, actions, rates, oversold
    warnings = oversold + [f"No {c}/INR rate cached yet; refresh prices to value holdings in {c}"
                           for c in sorted(rates.missing)]
    out_trades = []
    for t in trades:
        if t.symbol in foreign:
            rate = rates.rate(t.symbol, t.traded_at)
            if rate is not None:
                t = SimpleNamespace(id=t.id, symbol=t.symbol, side=t.side, quantity=t.quantity,
                                    price=t.price * rate, traded_at=t.traded_at, broker=t.broker,
                                    imported_at=t.imported_at)
        out_trades.append(t)
    out_actions = []
    for a in actions:
        if a.symbol in foreign and a.kind == "dividend":
            rate = rates.rate(a.symbol, a.ex_date)
            if rate is not None:
                a = SimpleNamespace(id=a.id, symbol=a.symbol, ex_date=a.ex_date, kind=a.kind,
                                    value=a.value * rate, source=a.source, review=a.review)
        out_actions.append(a)
    return out_trades, out_actions, rates, warnings


def load_positions(session: Session) -> dict[str, Position]:
    """Positions with cost, realized P&L and income in rupees."""
    trades, actions, _, _ = inr_ledger(session)
    return build_positions(trades, actions)


def native_positions(session: Session, wanted: set[str]) -> dict[str, Position]:
    """Positions in each instrument's own currency (for showing average cost)."""
    if not wanted:
        return {}
    trades = session.scalars(select(Trade).where(Trade.symbol.in_(wanted))).all()
    actions = session.scalars(select(CorporateAction).where(CorporateAction.symbol.in_(wanted))).all()
    return build_positions(trades, actions)


BROKER_LABELS = {"upstox": "Upstox", "zerodha": "Zerodha", "groww": "Groww"}


def reconcile(session: Session) -> list[dict]:
    """Compares each broker's last holdings snapshot with the positions built
    from that broker's trades in the ledger. Matching is by ISIN where known,
    so a stock bought on NSE and held as BSE (or the reverse) still lines up.
    Returns only the rows that disagree."""
    snapshots = session.scalars(select(BrokerHolding)).all()
    if not snapshots:
        return []
    isin_of = {i.symbol: i.isin for i in session.scalars(select(Instrument)) if i.isin}
    # NSE and BSE usually share the ticker, so the exchange-free ticker links a
    # symbol with no known ISIN (Kite's trade feed carries none) to one that has it.
    isin_of_ticker: dict[str, str] = {}
    for symbol, isin in list(isin_of.items()) + [(h.symbol, h.isin) for h in snapshots if h.isin]:
        isin_of_ticker.setdefault(symbol.rpartition(".")[0] or symbol, isin)

    def key_of(symbol: str, isin: str = "") -> str:
        ticker = symbol.rpartition(".")[0] or symbol
        return isin or isin_of.get(symbol) or isin_of_ticker.get(ticker) or ticker

    actions = session.scalars(select(CorporateAction)).all()
    out: list[dict] = []
    for broker in sorted({h.broker for h in snapshots}):
        trades = session.scalars(select(Trade).where(Trade.broker == broker)).all()
        ledger: dict[str, float] = {}
        names: dict[str, str] = {}
        for symbol, pos in build_positions(trades, actions).items():
            key = key_of(symbol)
            ledger[key] = ledger.get(key, 0.0) + pos.quantity
            names.setdefault(key, symbol)
        held: dict[str, float] = {}
        for h in (h for h in snapshots if h.broker == broker):
            key = key_of(h.symbol, h.isin)
            held[key] = held.get(key, 0.0) + h.quantity
            names[key] = h.symbol
        for key in sorted(set(ledger) | set(held)):
            lq, bq = ledger.get(key, 0.0), held.get(key, 0.0)
            if abs(lq - bq) > 1e-6:
                out.append({"broker": broker, "symbol": names[key], "isin": key if symbols.is_isin(key) else "",
                            "broker_quantity": bq, "ledger_quantity": lq})
    return out


def mismatch_warnings(rows: list[dict]) -> list[str]:
    return [
        f"{BROKER_LABELS.get(r['broker'], r['broker'])} holds {r['broker_quantity']:g} {r['symbol']}, "
        f"but the ledger has {r['ledger_quantity']:g} from {BROKER_LABELS.get(r['broker'], r['broker'])} trades "
        "(missing trades in the import?)"
        for r in rows
    ]


def display_currency(session: Session, choice: str, value: dict[str, float],
                     ccys: dict[str, str]) -> dict:
    """The currency to show money in and its latest rate (INR per unit).
    AUTO picks the currency holding the most value (London pence count as GBP)."""
    code = choice
    if choice == "AUTO":
        by_ccy: dict[str, float] = {}
        for sym, v in value.items():
            c = ccys.get(sym, "INR")
            c = symbols.MINOR_UNITS.get(c, (c, 1))[0]
            by_ccy[c] = by_ccy.get(c, 0.0) + v
        code = max(by_ccy, key=by_ccy.get) if by_ccy else "INR"
    if code == "INR":
        return {"choice": choice, "currency": "INR", "inr_per_unit": 1.0}
    rate = fx.Rates(session, {"x": code}).rate("x")
    if rate is None:  # rate not cached yet: show rupees rather than wrong numbers
        return {"choice": choice, "currency": "INR", "inr_per_unit": 1.0,
                "note": f"No {code}/INR rate cached yet; refresh prices"}
    return {"choice": choice, "currency": code, "inr_per_unit": rate}


def _portfolio_cash(session: Session) -> float:
    """Cash held in the portfolio today (see app.quant.cashflow)."""
    from app.quant import cashflow   # imported here: cashflow builds on this module

    return cashflow.balance(session)["balance"]


def history_start(session: Session, lookback_days: int = 252) -> date:
    """Earliest date to keep prices for: the first trade, or far enough back to
    fill the lookback window (trading days, with room for holidays), whichever is earlier."""
    first = session.scalar(select(Trade.traded_at).order_by(Trade.traded_at).limit(1))
    span = max(3 * 365, int(lookback_days * 365 / 252 * 1.1) + 45)
    floor = date.today() - timedelta(days=span)
    return min(first.date() - timedelta(days=7), floor) if first else floor


def refresh_market(session: Session, benchmark: str, fetcher=None, force: bool = False,
                   lookback_days: int = 252) -> list[str]:
    """Refreshes every traded symbol plus the benchmark. Failures become warnings
    so the terminal keeps working offline from the cache."""
    warnings: list[str] = []
    start = history_start(session, lookback_days)
    traded = list(session.scalars(select(Trade.symbol).distinct()))
    tracked = list(session.scalars(select(Watch.symbol).where(Watch.starred | Watch.watched)))
    # FX first, so international prices and costs convert with fresh rates. The
    # benchmark is included: a foreign index is compared in rupees like the holdings.
    ccys = fx.currencies(session, traded + tracked + [benchmark])
    shown = get_settings(session)["display_currency"]
    if shown not in ("AUTO", "INR"):
        ccys["__display__"] = shown
    pairs = fx.fx_symbols(ccys)
    todo = ([(s, True) for s in pairs] + [(s, False) for s in traded]
            + [(s, False) for s in tracked if s not in traded] + [(benchmark, True)])
    for symbol, is_index in todo:
        try:
            history.refresh_symbol(session, symbol, start, fetcher=fetcher,
                                   with_actions=not is_index, force=force)
        except Exception as exc:
            session.rollback()
            warnings.append(f"Could not refresh {symbol}: {exc}")
    return warnings


def _today_quotes(quotes: dict | None) -> dict[str, float]:
    """Latest live price per symbol, only for quotes stamped today (local time)."""
    if not quotes:
        return {}
    today = date.today()
    out: dict[str, float] = {}
    for s, q in quotes.items():
        try:
            ltp, ts = float(q.get("ltp")), float(q.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(ltp) and ltp > 0 and ts and datetime.fromtimestamp(ts).date() == today:
            out[s] = ltp
    return out


def apply_live_bar(close, adj, quotes: dict | None, held: list[str], benchmark: str | None):
    """Writes today's live prices as a provisional daily bar so beta, Sharpe and
    the rest move during the session. Only when the benchmark has a live quote
    and so does every listed holding: a holding without one would show a false
    0% day. Mutual funds, bonds and commodity proxies may lack a quote (their
    price is published once a day). Returns (close, adj, used)."""
    live = _today_quotes(quotes)
    if close is None or close.empty or not live or (benchmark and benchmark not in live):
        return close, adj, False
    need = [s for s in held if s in close.columns and symbols.namespace(s) is None]
    if any(s not in live for s in need):
        return close, adj, False
    today = date.today()
    last = close.index.max()
    if last > today:
        return close, adj, False
    cols = [s for s in [*held, benchmark] if s and s in live and s in close.columns]
    if not cols:
        return close, adj, False
    close, adj = close.copy(), adj.copy()
    if last < today:
        close.loc[today] = np.nan
        adj.loc[today] = np.nan
    for s in cols:              # today's bar has no later split or dividend, so adjusted = close
        close.loc[today, s] = live[s]
        adj.loc[today, s] = live[s]
    return close.sort_index(), adj.sort_index(), True


def inr_prices(session: Session, cols: list[str], quotes: dict | None = None,
               held: list[str] | None = None, benchmark: str | None = None):
    """Close and adjusted-close frames for `cols` with every price in rupees at
    that day's rate (international listings and a foreign benchmark alike),
    plus the local-currency closes. Columns with no rate are dropped.
    Returns (close_inr, adj_inr, close_local, rates, live_used)."""
    cols = list(dict.fromkeys(cols))            # the benchmark may also be a holding
    close, adj = history.load_prices(session, cols)
    close, adj, used = apply_live_bar(close, adj, quotes, held or [], benchmark)
    local_close = close.copy()
    ccys = fx.currencies(session, cols)
    rates = fx.Rates(session, ccys)
    for s in cols:
        if s not in close.columns or not symbols.fx_pair(rates.ccys.get(s, "INR")):
            continue
        r = rates.frame(s, close.index)
        if r is None:
            close = close.drop(columns=s)
            adj = adj.drop(columns=s)
            continue
        close[s] = close[s] * r
        adj[s] = adj[s] * r
    return close, adj, local_close, rates, used


def cov_lookback(params: dict) -> int:
    return int(params.get("cov_lookback_days") or 0) or int(params["lookback_days"])


def compute(session: Session, overrides: dict | None = None, *, refresh: bool = True,
            fetcher=None, quotes: dict | None = None) -> dict:
    """`quotes` are the live hub's latest quotes; when they cover the benchmark
    and the holdings, today's prices count as a provisional daily bar."""
    params = {**get_settings(session), **validate_settings(overrides or {})}
    benchmark = params["benchmark"]
    label = params["benchmark_name"] or benchmark
    lookback = int(params["lookback_days"])
    cov_days = cov_lookback(params)
    warnings = (refresh_market(session, benchmark, fetcher, lookback_days=max(lookback, cov_days))
                if refresh else [])

    pending = review.refresh(session)
    session.commit()
    if pending:
        warnings.append(f"{pending} split{'s' if pending > 1 else ''} or bonus issue{'s' if pending > 1 else ''} "
                        "may already be in your uploaded file; confirm under CHECK SPLITS")
    ledger_trades, ledger_actions, rates, fx_warnings = inr_ledger(session)
    warnings.extend(fx_warnings)
    positions = build_positions(ledger_trades, ledger_actions)
    for p in positions.values():
        warnings.extend(p.warnings)
    warnings.extend(mismatch_warnings(reconcile(session)))
    held = sorted(s for s, p in positions.items() if p.quantity > EPS)
    # Every price into rupees at that day's rate, the benchmark included.
    close, adj, local_close, prates, live_used = inr_prices(
        session, held + [benchmark], quotes, held, benchmark)
    foreign = [s for s in held if s in local_close.columns and symbols.fx_pair(prates.ccys.get(s, "INR"))]
    native = native_positions(session, set(foreign))

    priced = [s for s in held if s in close.columns and close[s].notna().any()]
    for s in held:
        if s not in priced:
            warnings.append(f"No price history for {s}; excluded from value and risk")

    last = {s: float(close[s].dropna().iloc[-1]) for s in priced}
    value = {s: positions[s].quantity * last[s] for s in priced}
    total = sum(value.values())
    weight = {s: value[s] / total for s in priced} if total > 0 else {}

    result = {
        "as_of": close.index.max().isoformat() if len(close) else None,
        "params": params,
        "portfolio_value": _f(total),
        "net_delta": _f(total),  # cash equity: delta 1, so exposure equals market value
        "realized_pnl": _f(sum(p.realized_pnl for p in positions.values())),
        "dividends": _f(sum(p.dividends for p in positions.values())),
        "unrealized_pnl": _f(sum(value[s] - positions[s].cost_value for s in priced)),
        "metrics": None,
        "covariance": None,
        "observations": 0,
        "live": False,
        "warnings": warnings,
        "pending_reviews": pending,
        # Dividends, coupons and sale proceeds stay as cash until spent on a purchase or withdrawn.
        "portfolio_cash": _f(_portfolio_cash(session)),
    }
    holdings = {
        s: {
            "symbol": s,
            "quantity": _f(positions[s].quantity),
            # Average cost and last price in the instrument's own currency; value and P&L in INR.
            "avg_cost": _f((native.get(s) or positions[s]).avg_cost),
            "last": (_f(float(local_close[s].dropna().iloc[-1])) if s in last and s in native
                     else _f(last[s]) if s in last else None),
            "currency": rates.ccys.get(s, "INR") if s in rates.ccys else "INR",
            "fx_rate": _f(rates.rate(s)) if s in native and rates.rate(s) else None,
            "value": _f(value[s]) if s in value else None,
            "weight": _f(weight[s]) if s in weight else None,
            "unrealized_pnl": _f(value[s] - positions[s].cost_value) if s in value else None,
            "realized_pnl": _f(positions[s].realized_pnl),
            "dividends": _f(positions[s].dividends),
            "beta": None,
            "component_var": None,
        }
        for s in held
    }
    # Returns (money-weighted, dividends and coupons included) and asset classes.
    instruments = {i.symbol: i for i in session.scalars(select(Instrument))}
    per, overall = returns.compute_returns(ledger_trades, positions, value)
    result["returns"] = {k: _f(v) if v is not None else None for k, v in overall.items()}
    allocation: dict[str, float] = {}
    for s in held:
        inst = instruments.get(s)
        cls = (inst.asset_class if inst and inst.asset_class else
               symbols.asset_class(s, inst.name if inst else ""))
        r = per.get(s, {})
        holdings[s].update({
            "name": inst.name if inst else "",
            "asset_class": cls,
            "total_return": _f(r["total_return"]) if r.get("total_return") is not None else None,
            "total_return_pct": _f(r["total_return_pct"]) if r.get("total_return_pct") is not None else None,
            "xirr": _f(r["xirr"]) if r.get("xirr") is not None else None,
        })
        if s in value:
            allocation[cls] = allocation.get(cls, 0.0) + value[s]
    result["allocation"] = [
        {"asset_class": cls, "value": _f(v), "weight": _f(v / total) if total > 0 else None}
        for cls, v in sorted(allocation.items(), key=lambda kv: -kv[1])
    ]
    for bond in session.scalars(select(Bond).where(Bond.symbol.in_(held))):
        if bond.maturity <= date.today():
            warnings.append(f"{bond.symbol} matured on {bond.maturity:%d %b %Y}; record the redemption "
                            "as a SELL at face value")

    result["display"] = display_currency(session, params["display_currency"], value, rates.ccys)
    result["holdings"] = list(holdings.values())
    if not priced:
        return result

    has_bench = benchmark in adj.columns and adj[benchmark].notna().any()
    if not has_bench:
        warnings.append(f"No price history for benchmark {label}; beta and alpha unavailable")
    cols = priced + ([benchmark] if has_bench else [])
    # Markets keep different holidays: returns are measured on the benchmark's
    # trading days, carrying a holding's price over its own closed days (at most
    # a week), so both sides of beta cover the same calendar span.
    all_rets = qm.aligned_returns(adj, cols, benchmark if has_bench else None)
    rets = all_rets.tail(lookback)
    result["observations"] = len(rets)
    result["live"] = bool(live_used and len(rets) and rets.index.max() == date.today())

    _covariance(result, warnings, all_rets[priced].tail(cov_days), int(params["cov_horizon_days"]), cov_days)

    need = min(MIN_OBSERVATIONS, lookback)
    if need <= len(rets) < lookback:
        warnings.append(
            f"Lookback is {lookback} trading days but only {len(rets)} overlapping daily returns "
            "exist for these holdings and the benchmark; metrics use what is available"
        )
    if len(rets) < need:
        warnings.append(
            f"Only {len(rets)} overlapping daily returns; need {need} for risk metrics"
        )
        return result

    w = np.array([weight[s] for s in priced])
    asset_rets = rets[priced]
    rp = asset_rets.to_numpy() @ w
    cov = np.atleast_2d(np.cov(asset_rets.to_numpy(), rowvar=False, ddof=1))
    var = qm.parametric_var(w, cov, total, params["confidence"], int(params["horizon_days"]))
    rf = params["risk_free_rate"]

    m = {
        "beta": None,
        "jensens_alpha_annualized": None,
        "sharpe": _f(qm.sharpe_ratio(rp, rf)),
        "sortino": _f(qm.sortino_ratio(rp, rf)),
        "max_drawdown": _f(qm.max_drawdown(rp)),
        "volatility_annualized": _f(qm.annualized_volatility(rp)),
        # Compound annual return of today's mix over the lookback (used for projections).
        "return_annualized": _f(float(np.prod(1 + rp)) ** (qm.TRADING_DAYS / len(rp)) - 1),
        "var": _f(var["var"]),
        "var_pct": _f(var["var"] / total),
        "var_z": _f(var["z"]),
    }
    if has_bench:
        rb = rets[benchmark].to_numpy()
        m["beta"] = _f(qm.beta(rp, rb))
        m["jensens_alpha_annualized"] = _f(qm.jensens_alpha_annualized(rp, rb, rf))
        for s in priced:
            holdings[s]["beta"] = _f(qm.beta(asset_rets[s].to_numpy(), rb))
    for s, c in zip(priced, var["component"]):
        holdings[s]["component_var"] = _f(c)

    result["metrics"] = m
    return result


PERIODS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "6M": 126, "1Y": 252, "YTD": 0}


def period_returns(session: Session, period: str, quotes: dict | None = None) -> dict:
    """Each holding's total return (dividends included, in rupees) over the
    period, from cached prices plus today's live quotes, and the benchmark's
    over the same days, so a tile can be read as beating or lagging the market."""
    params = get_settings(session)
    benchmark = params["benchmark"]
    trades, actions, _, _ = inr_ledger(session)
    held = sorted(s for s, p in build_positions(trades, actions).items() if p.quantity > EPS)
    out = {"period": period, "benchmark": benchmark, "benchmark_name": params["benchmark_name"] or benchmark,
           "benchmark_return": None, "from": None, "to": None, "returns": {}, "live": False}
    if not held:
        return out
    _, adj, _, _, live_used = inr_prices(session, held + [benchmark], quotes, held, benchmark)
    if adj.empty:
        return out
    end = adj.index.max()
    if period == "YTD":
        start_day = date(end.year, 1, 1)
        idx = [d for d in adj.index if d < start_day]
        start = idx[-1] if idx else adj.index.min()      # last close of the previous year
    else:
        days = PERIODS[period]
        bench_days = adj[benchmark].dropna().index if benchmark in adj.columns else adj.index
        pos = max(len(bench_days) - 1 - days, 0)
        start = bench_days[pos]
    out.update({"from": start.isoformat(), "to": end.isoformat(), "live": bool(live_used and end == date.today())})

    def ret(sym: str) -> float | None:
        if sym not in adj.columns:
            return None
        s = adj[sym].dropna()
        a, b = s[s.index <= start], s[s.index <= end]
        if a.empty or b.empty or a.iloc[-1] <= 0:
            return None
        return _f(b.iloc[-1] / a.iloc[-1] - 1)

    out["returns"] = {s: ret(s) for s in held}
    out["benchmark_return"] = ret(benchmark)
    return out


ROLLING_KEYS = ("sharpe", "sortino", "volatility", "return", "beta", "alpha")


def rolling(session: Session, window: int, span: int | None = None, quotes: dict | None = None) -> dict:
    """Trailing `window`-day metrics of today's mix of holdings, one point per
    trading day over the last `span` days (default: the risk lookback). Same
    data and formulas as the RISK tab, so the last point equals its figures
    when window = lookback."""
    params = get_settings(session)
    benchmark = params["benchmark"]
    span = span or int(params["lookback_days"])
    rf = float(params["risk_free_rate"])
    trades, actions, _, _ = inr_ledger(session)
    positions = build_positions(trades, actions)
    held = sorted(s for s, p in positions.items() if p.quantity > EPS)
    out = {"window": window, "span": span, "benchmark": benchmark,
           "benchmark_name": params["benchmark_name"] or benchmark, "risk_free_rate": rf,
           "dates": [], "series": {k: [] for k in ROLLING_KEYS}, "live": False, "warnings": []}
    if not held:
        return out
    close, adj, _, _, live_used = inr_prices(session, held + [benchmark], quotes, held, benchmark)
    priced = [s for s in held if s in close.columns and close[s].notna().any()]
    if not priced:
        return out
    last = {s: float(close[s].dropna().iloc[-1]) for s in priced}
    value = {s: positions[s].quantity * last[s] for s in priced}
    total = sum(value.values())
    if total <= 0:
        return out
    w = np.array([value[s] / total for s in priced])
    has_bench = benchmark in adj.columns and adj[benchmark].notna().any()
    cols = priced + ([benchmark] if has_bench else [])
    rets = qm.aligned_returns(adj, cols, benchmark if has_bench else None).tail(span + window - 1)
    if len(rets) < window + 1:
        out["warnings"].append(f"Only {len(rets)} overlapping daily returns; a {window}-day window needs "
                               f"at least {window + 1}")
        return out
    rp = pd.Series(rets[priced].to_numpy() @ w, index=rets.index)
    frame = qm.rolling_metrics(rp, rets[benchmark] if has_bench else None, rf, window)
    out["dates"] = [d.isoformat() for d in frame.index]
    out["series"] = {k: ([_f(v) for v in frame[k]] if k in frame.columns else [None] * len(frame))
                     for k in ROLLING_KEYS}
    out["live"] = bool(live_used and frame.index.max() == date.today())
    if not has_bench:
        out["warnings"].append(f"No price history for benchmark {out['benchmark_name']}; rolling beta unavailable")
    return out


def _covariance(result: dict, warnings: list[str], rets, h: int, window: int) -> None:
    """Covariance of compounded h-day returns over the last `window` daily
    returns (overlapping windows, so every day is used). Long horizons on a
    short window have few independent periods; that is reported, not hidden."""
    syms = list(rets.columns)
    if not syms:
        return
    period = qm.horizon_returns(rets.to_numpy(), h)
    if len(period) < MIN_OBSERVATIONS:
        warnings.append(f"Not enough history for a {h}-day covariance matrix: {len(period)} overlapping "
                        f"{h}-day returns in {len(rets)} days, need {MIN_OBSERVATIONS}. "
                        "Pick a longer covariance window or a shorter horizon")
        return
    independent = len(rets) // h
    if h > 1 and independent < 10:
        warnings.append(f"The {h}-day covariance rests on about {independent} non-overlapping periods in "
                        f"{len(rets)} days; treat it as rough or lengthen the covariance window")
    cov_h = np.atleast_2d(np.cov(period, rowvar=False, ddof=1))
    result["covariance"] = {
        "symbols": syms,
        "horizon_days": h,
        "window_days": window,
        "observations": len(period),
        "independent_periods": independent,
        "from": rets.index.min().isoformat(),
        "to": rets.index.max().isoformat(),
        "matrix": [[_f(v) for v in row] for row in cov_h],
        "annualized": [[_f(v) for v in row] for row in cov_h * (qm.TRADING_DAYS / h)],
        "correlation": [[_f(v) for v in row] for row in qm.correlation(cov_h)],
    }
