"""Demergers (one company becomes two listed companies) and renames.

Example: Tata Motors (TATAMOTORS) demerged on 14 Oct 2025. Holders kept their
shares, renamed TMPV, and got one TMCV share for each; the purchase cost was
split 68.35% / 31.65% between them."""
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

from app.ledger.positions import build_positions, clip_oversells, held_on
from app.market import history
from tests.conftest import fake_fetch

EX = date(2025, 10, 14)


def trade(sym, when, side, qty, price):
    return NS(symbol=sym, traded_at=when, side=side, quantity=qty, price=price, id=None)


def demerger(parent, child, ratio, cost_share, when=EX):
    return NS(symbol=parent, ex_date=when, kind="demerger", value=ratio, target=child, cost_share=cost_share,
              source="manual", review="")


def rename(old, new, when=EX):
    return NS(symbol=old, ex_date=when, kind="rename", value=1.0, target=new, cost_share=0.0,
              source="manual", review="")


TATA = [trade("TATAMOTORS.NS", datetime(2025, 1, 2, 10), "BUY", 100, 1000.0),
        trade("TATAMOTORS.NS", datetime(2025, 3, 3, 10), "BUY", 50, 700.0)]
ACTIONS = [demerger("TATAMOTORS.NS", "TMCV.NS", 1.0, 0.3165), rename("TATAMOTORS.NS", "TMPV.NS")]


def test_demerger_moves_shares_and_cost_and_the_parent_continues_under_its_new_name():
    book = build_positions(TATA, ACTIONS)
    assert "TATAMOTORS.NS" not in book or book["TATAMOTORS.NS"].quantity == 0
    tmpv, tmcv = book["TMPV.NS"], book["TMCV.NS"]
    assert (tmpv.quantity, tmcv.quantity) == (150, 150)
    total = 100 * 1000 + 50 * 700
    assert tmpv.cost_value + tmcv.cost_value == pytest.approx(total)           # no cost created or lost
    assert tmcv.cost_value == pytest.approx(total * 0.3165)
    # FIFO order survives: the first lot of each is the January purchase
    assert list(tmpv.lots)[0] == [100, pytest.approx(1000 * 0.6835)]
    assert list(tmcv.lots)[0] == [100, pytest.approx(1000 * 0.3165)]


def test_demerger_ratio_other_than_one_to_one():
    book = build_positions(TATA[:1], [demerger("TATAMOTORS.NS", "NEWCO.NS", 0.5, 0.2)])
    child = book["NEWCO.NS"]
    assert child.quantity == 50                                                 # 1 new share for every 2 held
    assert child.avg_cost == pytest.approx(1000 * 0.2 / 0.5)
    assert book["TATAMOTORS.NS"].quantity == 100
    assert book["TATAMOTORS.NS"].avg_cost == pytest.approx(800)


def test_selling_the_new_stock_uses_its_share_of_the_cost():
    sale = trade("TMCV.NS", datetime(2025, 11, 3, 10), "SELL", 120, 400.0)
    book = build_positions(TATA + [sale], ACTIONS)
    # FIFO: 100 from the January lot (cost 316.5) and 20 from the March lot (cost 221.55)
    assert book["TMCV.NS"].realized_pnl == pytest.approx(100 * (400 - 316.5) + 20 * (400 - 700 * 0.3165))
    assert book["TMCV.NS"].quantity == 30


def test_a_sale_of_demerged_shares_is_not_treated_as_overselling():
    sale = trade("TMCV.NS", datetime(2025, 11, 3, 10), "SELL", 150, 400.0)
    kept, warnings = clip_oversells(TATA + [sale], ACTIONS)
    assert warnings == [] and sale in kept
    assert held_on(TATA, ACTIONS, "TMCV.NS", datetime(2025, 11, 3, 10)) == 150
    assert held_on(TATA, ACTIONS, "TMPV.NS", datetime(2025, 11, 3, 10)) == 150
    assert held_on(TATA, ACTIONS, "TATAMOTORS.NS", datetime(2025, 11, 3, 10)) == 0


def test_rename_alone_carries_the_whole_position():
    book = build_positions(TATA, [rename("TATAMOTORS.NS", "TMPV.NS")])
    assert book["TMPV.NS"].quantity == 150
    assert book["TMPV.NS"].cost_value == pytest.approx(135_000)


# ------------------------------------------------------------------ API


def setup_ledger(client):
    for t in TATA:
        r = client.post("/api/ledger/trades", json={"symbol": "TATAMOTORS", "side": "BUY", "quantity": t.quantity,
                                                     "price": t.price, "traded_at": t.traded_at.isoformat()})
        assert r.status_code == 201, r.text


def test_demerger_api_records_it_and_holdings_follow(client, monkeypatch):
    monkeypatch.setattr(history, "fetch", fake_fetch)
    setup_ledger(client)
    body = {"symbol": "TATAMOTORS", "ex_date": EX.isoformat(), "new_symbol": "TMCV", "new_name": "Tata Motors CV",
            "new_shares_per_share": 1, "cost_to_new_pct": 31.65, "continues_as": "TMPV"}
    res = client.post("/api/corporate-actions/demerger", json=body)
    assert res.status_code == 201, res.text
    held = {h["symbol"]: h for h in client.get("/api/metrics").json()["holdings"]}
    assert set(held) == {"TMPV.NS", "TMCV.NS"}
    assert held["TMCV.NS"]["quantity"] == 150 and held["TMCV.NS"]["last"] is not None   # prices fetched for it
    kinds = {(a["kind"], a.get("target")) for a in client.get("/api/corporate-actions").json()}
    assert ("demerger", "TMCV.NS") in kinds and ("rename", "TMPV.NS") in kinds

    # selling the new stock is accepted (the ledger knows it is held)
    sale = {"symbol": "TMCV", "side": "SELL", "quantity": 150, "price": 400, "traded_at": "2025-11-03T10:00:00"}
    assert client.post("/api/ledger/trades", json=sale).status_code == 201

    assert client.post("/api/corporate-actions/demerger", json=body).status_code == 409   # no double entry


@pytest.mark.parametrize("patch", [{"cost_to_new_pct": 0}, {"cost_to_new_pct": 100}, {"new_shares_per_share": 0},
                                   {"new_symbol": "TATAMOTORS"}, {"ex_date": "2999-01-01"},
                                   {"new_symbol": "BAD SYMBOL!"}])
def test_demerger_api_rejects_bad_input(client, patch):
    setup_ledger(client)
    body = {"symbol": "TATAMOTORS", "ex_date": EX.isoformat(), "new_symbol": "TMCV",
            "new_shares_per_share": 1, "cost_to_new_pct": 31.65, **patch}
    assert client.post("/api/corporate-actions/demerger", json=body).status_code in (400, 422)


def test_manual_actions_can_be_removed_and_a_demerger_takes_its_rename_with_it(client):
    setup_ledger(client)
    client.post("/api/corporate-actions/demerger", json={
        "symbol": "TATAMOTORS", "ex_date": EX.isoformat(), "new_symbol": "TMCV",
        "new_shares_per_share": 1, "cost_to_new_pct": 31.65, "continues_as": "TMPV"})
    dem = next(a for a in client.get("/api/corporate-actions").json() if a["kind"] == "demerger")
    assert client.delete(f"/api/corporate-actions/{dem['id']}").status_code == 200
    assert client.get("/api/corporate-actions").json() == []
    held = {h["symbol"] for h in client.get("/api/portfolio/holdings").json()["holdings"]}
    assert held == {"TATAMOTORS.NS"}
    assert client.delete("/api/corporate-actions/99999").status_code == 404


def test_split_entered_by_hand_doubles_the_holding(client):
    setup_ledger(client)
    res = client.post("/api/corporate-actions", json={"symbol": "TATAMOTORS.NS", "ex_date": "2025-06-02",
                                                      "kind": "split", "value": 2})
    assert res.status_code == 201
    h = client.get("/api/portfolio/holdings").json()["holdings"][0]
    assert h["quantity"] == 300 and h["avg_cost"] == pytest.approx(135_000 / 300)
