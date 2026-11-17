from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

from app.ledger import upstox
from app.ledger.positions import build_positions


def test_upstox_parse_skips_preamble_and_derivatives(upstox_csv):
    result = upstox.parse(upstox_csv)
    assert [t.symbol for t in result.trades] == ["RELIANCE.NS", "TCS.NS", "RELIANCE.NS"]
    first = result.trades[0]
    assert (first.side, first.quantity, first.price) == ("BUY", 10, 1250.0)
    assert first.traded_at == datetime(2025, 1, 3, 9, 20, 11)  # day-first dates
    assert len(result.skipped) == 1 and "non-equity" in result.skipped[0]


def test_upstox_bse_maps_to_bo_suffix():
    csv = "Date,Exchange,Scrip Code,Side,Quantity,Price\n02-01-2025,BSE,500325,Buy,1,100\n"
    assert upstox.parse(csv).trades[0].symbol == "500325.BO"


def test_upstox_rejects_unrecognised_file():
    with pytest.raises(ValueError):
        upstox.parse("foo,bar\n1,2\n")


def trade(sym, when, side, qty, price):
    return NS(symbol=sym, traded_at=when, side=side, quantity=qty, price=price)


def action(sym, when, kind, value):
    return NS(symbol=sym, ex_date=when, kind=kind, value=value)


def test_split_dividend_and_fifo_sale():
    trades = [
        trade("X", datetime(2025, 1, 1, 10), "BUY", 10, 100.0),
        trade("X", datetime(2025, 4, 1, 10), "SELL", 5, 60.0),
    ]
    actions = [
        action("X", date(2025, 2, 1), "split", 2.0),      # 10 @ 100 -> 20 @ 50
        action("X", date(2025, 3, 1), "dividend", 2.0),   # 20 * 2 = 40
    ]
    pos = build_positions(trades, actions)["X"]
    assert pos.quantity == pytest.approx(15)
    assert pos.avg_cost == pytest.approx(50.0)
    assert pos.realized_pnl == pytest.approx(50.0)        # 5 * (60 - 50)
    assert pos.dividends == pytest.approx(40.0)


def test_bonus_keeps_total_cost_and_fifo_order():
    trades = [
        trade("X", datetime(2025, 1, 1, 10), "BUY", 10, 100.0),
        trade("X", datetime(2025, 1, 2, 10), "BUY", 10, 200.0),
        trade("X", datetime(2025, 3, 1, 10), "SELL", 30, 90.0),
    ]
    actions = [action("X", date(2025, 2, 1), "bonus", 2.0)]  # 1:1 bonus
    pos = build_positions(trades, actions)["X"]
    # lots become 20 @ 50 and 20 @ 100 ; sell 20 @ 50 then 10 @ 100
    assert pos.realized_pnl == pytest.approx(20 * 40 + 10 * -10)
    assert pos.quantity == pytest.approx(10) and pos.avg_cost == pytest.approx(100.0)


def test_action_before_purchase_does_not_apply_and_oversell_warns():
    trades = [
        trade("X", datetime(2025, 3, 1, 10), "BUY", 10, 100.0),
        trade("X", datetime(2025, 3, 2, 10), "SELL", 12, 110.0),
    ]
    actions = [action("X", date(2025, 2, 1), "split", 2.0), action("X", date(2025, 2, 1), "dividend", 5.0)]
    pos = build_positions(trades, actions)["X"]
    assert pos.dividends == 0 and pos.quantity == pytest.approx(0)
    assert pos.realized_pnl == pytest.approx(100.0)
    assert len(pos.warnings) == 1


def test_yahoo_dividend_before_a_later_split_counts_the_cash_actually_paid():
    """Yahoo restates past dividends in post-split shares (a ₹5 dividend before a
    2:1 split is listed as ₹2.50), but the ledger holds the pre-split quantity on
    that date. Income must be the cash actually received: 40 shares x ₹5."""
    def yahoo(sym, when, kind, value):
        return NS(symbol=sym, ex_date=when, kind=kind, value=value, source="yfinance")

    trades = [trade("X", datetime(2025, 1, 1, 10), "BUY", 40, 200.0)]
    actions = [
        yahoo("X", date(2025, 2, 1), "dividend", 2.5),     # paid ₹5 on 40 shares
        yahoo("X", date(2025, 3, 1), "split", 2.0),        # 40 -> 80
        yahoo("X", date(2025, 4, 1), "dividend", 1.0),     # after the split: ₹1 on 80 shares
    ]
    pos = build_positions(trades, actions)["X"]
    assert pos.quantity == pytest.approx(80)
    assert pos.dividends == pytest.approx(40 * 5.0 + 80 * 1.0)
    assert pos.income == [(date(2025, 2, 1), pytest.approx(200.0)), (date(2025, 4, 1), pytest.approx(80.0))]


def test_manual_dividends_are_taken_as_paid_even_before_a_split():
    trades = [trade("X", datetime(2025, 1, 1, 10), "BUY", 40, 200.0)]
    actions = [
        NS(symbol="X", ex_date=date(2025, 2, 1), kind="dividend", value=5.0, source="manual"),
        NS(symbol="X", ex_date=date(2025, 3, 1), kind="split", value=2.0, source="yfinance"),
    ]
    assert build_positions(trades, actions)["X"].dividends == pytest.approx(200.0)


def test_iso_dates_are_not_read_day_first():
    """A plain trade file with YYYY-MM-DD dates is read by the Upstox parser;
    2025-03-05 is 5 March, not 3 May."""
    from app.ledger import upstox

    text = "Date,Symbol,Exchange,Side,Quantity,Price,Trade ID\n2025-03-05,INFY,NSE,BUY,10,1500,T1\n05-03-2025,TCS,NSE,BUY,1,4000,T2\n"
    trades = upstox.parse(text).trades
    assert [t.traded_at.date() for t in trades] == [date(2025, 3, 5), date(2025, 3, 5)]
