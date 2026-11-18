"""Reset everything: every table emptied; saved keys only when asked."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.secrets import MemoryStore


def make(tmp_path):
    upstox, gemini = MemoryStore("u" * 40), MemoryStore("g" * 40)
    app = create_app(db_url=f"sqlite:///{(tmp_path / 'r.sqlite3').as_posix()}", token="",
                     token_store=upstox, gemini_store=gemini)
    return app, upstox, gemini


def fill(c):
    assert c.post("/api/ledger/trades", json={"symbol": "INFY", "side": "BUY", "quantity": 5, "price": 1500,
                                              "traded_at": "2025-01-02T10:00:00", "name": "Infosys"}).status_code == 201
    assert c.post("/api/corporate-actions", json={"symbol": "INFY.NS", "ex_date": "2025-06-02",
                                                  "kind": "split", "value": 2}).status_code == 201
    assert c.put("/api/settings", json={"benchmark": "^NSEBANK", "risk_free_rate": 0.07}).status_code == 200
    assert c.put("/api/watchlist/TCS.NS", json={"starred": True}).status_code == 200


def test_reset_needs_the_typed_confirmation(tmp_path):
    app, *_ = make(tmp_path)
    with TestClient(app) as c:
        fill(c)
        assert c.post("/api/reset", json={"confirm": "reset please"}).status_code == 400
        assert c.post("/api/reset", json={}).status_code == 422
        assert len(c.get("/api/ledger/trades").json()) == 1


def test_reset_clears_every_table_and_keeps_saved_keys_by_default(tmp_path):
    app, upstox, gemini = make(tmp_path)
    with TestClient(app) as c:
        fill(c)
        res = c.post("/api/reset", json={"confirm": "RESET"})
        assert res.status_code == 200 and res.json()["credentials_removed"] is False
        assert c.get("/api/ledger/trades").json() == []
        assert c.get("/api/corporate-actions").json() == []
        assert c.get("/api/watchlist").json() == []
        settings = c.get("/api/settings").json()
        assert settings["benchmark"] == "^NSEI" and settings["risk_free_rate"] == 0.065
        assert c.get("/api/portfolio/holdings").json()["holdings"] == []
    with app.state.sessionmaker() as s:
        from sqlalchemy import text

        from app.db.models import Base
        for table in Base.metadata.sorted_tables:
            assert s.execute(text(f"SELECT COUNT(*) FROM {table.name}")).scalar() == 0, table.name
    assert upstox.get() and gemini.get()


def test_reset_can_also_remove_saved_keys(tmp_path):
    app, upstox, gemini = make(tmp_path)
    with TestClient(app) as c:
        fill(c)
        res = c.post("/api/reset", json={"confirm": "RESET", "credentials": True})
        assert res.status_code == 200 and res.json()["credentials_removed"] is True
    assert upstox.get() is None and gemini.get() is None
    assert all(src.value(f.name) is None for src in app.state.sources.values() for f in src.fields)
