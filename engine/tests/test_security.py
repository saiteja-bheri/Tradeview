"""Security guards from the audit: what a web page can reach, broker writes,
upload limits and spreadsheet formulas in exports."""
import csv
import io
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.brokers import http
from app.brokers.base import BrokerError
from app.brokers.groww import ReadOnlyClient
from app.ledger import table
from app.main import create_app

APP_DIR = Path(__file__).parents[1] / "app"
EVIL = "https://evil.example"


def upload(client, data, headers=None):
    return client.post("/api/ledger/import", files={"file": ("tradebook.csv", data, "text/csv")},
                       headers=headers or {})


# ------------------------------------------------------------------ web pages


def test_without_a_token_only_local_pages_get_in(client, upstox_csv):
    assert client.get("/api/settings").status_code == 200                       # curl, /docs
    assert client.get("/api/settings", headers={"origin": "http://localhost:5173"}).status_code == 200
    assert client.get("/api/settings", headers={"origin": "http://127.0.0.1:8765"}).status_code == 200
    for origin in (EVIL, "null", "file://", "http://localhost.evil.example"):
        assert client.get("/api/settings", headers={"origin": origin}).status_code == 403, origin

    # a form post from a web page is refused before it touches the ledger
    assert upload(client, upstox_csv, {"origin": EVIL}).status_code == 403
    assert client.get("/api/ledger/trades").json() == []


def test_cors_preflight_from_a_site_is_refused(client):
    res = client.options("/api/ledger/trades", headers={"origin": EVIL, "access-control-request-method": "DELETE"})
    assert res.status_code == 403 and "access-control-allow-origin" not in res.headers


def test_dns_rebinding_host_is_refused(client):
    assert client.get("/api/settings", headers={"host": "evil.example:8765"}).status_code == 403
    assert client.get("/health", headers={"host": "evil.example"}).status_code == 403
    assert client.get("/api/settings", headers={"host": "127.0.0.1:8765"}).status_code == 200


def test_websocket_from_a_site_is_refused(client):
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/ws/ticks", headers={"origin": EVIL}) as ws:
            ws.receive_json()
    assert refused.value.code == 4403
    with client.websocket_connect("/ws/ticks", headers={"origin": "http://localhost:5173"}) as ws:
        assert ws.receive_json()["type"] == "snapshot"


def test_desktop_app_still_works_with_its_token(tmp_path):
    """The packaged UI is loaded from disk and sends Origin null; the token is the lock."""
    app = create_app(db_url=f"sqlite:///{(tmp_path / 't.sqlite3').as_posix()}", token="s" * 48)
    with TestClient(app) as c:
        assert c.get("/api/settings", headers={"origin": "null", "x-qt-token": "s" * 48}).status_code == 200
        assert c.get("/api/settings", headers={"origin": "null"}).status_code == 401
        assert c.get("/api/settings", headers={"x-qt-token": "s" * 47}).status_code == 401
        assert c.get("/api/settings", headers={"host": "evil.example", "x-qt-token": "s" * 48}).status_code == 403


# ------------------------------------------------------------------ brokers


def test_broker_http_refuses_every_write_but_the_kite_login():
    http.check_read_only("GET", "https://api.kite.trade/portfolio/holdings")
    http.check_read_only("POST", "https://api.kite.trade/session/token")
    for method, url in [("POST", "https://api.kite.trade/orders/regular"),
                        ("PUT", "https://api.kite.trade/orders/regular/1"),
                        ("DELETE", "https://api.kite.trade/orders/regular/1"),
                        ("POST", "https://api.kite.trade/session/token/../orders/regular"),
                        ("POST", "https://evil.example/session/token"),
                        ("post", "https://api.groww.in/v1/order/create")]:
        with pytest.raises(BrokerError) as blocked:
            http.check_read_only(method, url)
        assert blocked.value.status == 403


def test_broker_http_checks_before_it_sends():
    text = (APP_DIR / "brokers" / "http.py").read_text()
    body = text[text.index("def call("):]
    assert body.index("check_read_only(method, url)") < body.index("urlopen(")


def test_every_broker_call_in_the_source_is_a_read():
    calls = []
    for path in APP_DIR.rglob("*.py"):
        for m in re.finditer(r"http\.call\(\s*\"(\w+)\"\s*,\s*([^,]+)", path.read_text()):
            calls.append((path.name, m.group(1), m.group(2).strip()))
    writes = [c for c in calls if c[1] != "GET"]
    assert calls and writes == [("zerodha.py", "POST", 'f"{API}/session/token"')]


def test_no_order_methods_anywhere_in_the_engine():
    banned = re.compile(r"(place|modify|cancel|exit|create)_\w*order|order_(place|modify|cancel)", re.I)
    hits = [(p.name, m.group(0)) for p in APP_DIR.rglob("*.py") for m in banned.finditer(p.read_text())]
    assert hits == []


def test_groww_client_exposes_only_reads():
    class FakeSdk:
        SEGMENT_CASH = "CASH"

        def get_ltp(self, **kw):
            return {"NSE_INFY": 1500.0}

        def place_order(self, **kw):  # pragma: no cover - must never be reachable
            raise AssertionError("order placed")

        cancel_order = modify_order = place_order

    client = ReadOnlyClient(FakeSdk())
    assert client.SEGMENT_CASH == "CASH" and client.get_ltp() == {"NSE_INFY": 1500.0}
    for name in ("place_order", "cancel_order", "modify_order", "_client.place_order"):
        with pytest.raises(AttributeError):
            getattr(client, name)
    with pytest.raises(AttributeError):
        client.place_order = lambda **kw: None


# ------------------------------------------------------------------ files


def test_oversized_upload_is_refused(client):
    from app.api import routes

    big = b"x" * (routes.MAX_UPLOAD_BYTES + 1)
    res = upload(client, big)
    assert res.status_code == 413 and "MB" in res.json()["detail"]


def test_excel_that_unpacks_too_far_is_refused(client, monkeypatch):
    template = client.get("/api/import/everything/template").content
    assert template[:2] == b"PK"
    monkeypatch.setattr(table, "MAX_UNPACKED_BYTES", 1024)
    with pytest.raises(ValueError, match="unpack"):
        table.open_workbook(template)


def test_export_neutralises_spreadsheet_formulas_and_still_round_trips(client):
    evil = '=HYPERLINK("https://evil.example","click")'
    made = client.post("/api/ledger/trades", json={
        "symbol": "INFY", "side": "BUY", "quantity": 1, "price": 1500.0,
        "traded_at": "2025-03-03T10:00:00", "name": evil})
    assert made.status_code == 201
    text = client.get("/api/ledger/export").text
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["Company"] == "'" + evil
    assert not any(v.startswith(("=", "+", "-", "@")) for v in row.values() if v)

    again = upload(client, text.encode()).json()
    assert (again["imported"], again["duplicates"]) == (0, 1)


# ------------------------------------------------------------------ Cloudflare


def test_upstox_requests_carry_a_client_name_and_firewall_blocks_are_not_blamed_on_the_token(monkeypatch, tmp_path):
    import urllib.error
    import urllib.request

    from app.market.feeds import upstox

    seen = {}

    def refused(request, timeout=None):
        seen["ua"] = request.get_header("User-agent")
        body = io.BytesIO(b'{"title":"Error 1010: Access denied","detail":"cloudflare"}')
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, body)

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    with pytest.raises(upstox.FeedAuthError) as err:
        upstox.UpstoxFeed("eyJ" + "x" * 40, tmp_path)._authorize()
    assert seen["ua"] == upstox.USER_AGENT and "Python-urllib" not in seen["ua"]
    assert "not a token problem" in str(err.value)

    def rejected(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"status":"error"}'))

    monkeypatch.setattr(urllib.request, "urlopen", rejected)
    with pytest.raises(upstox.FeedAuthError, match="rejected the token"):
        upstox.UpstoxFeed("eyJ" + "x" * 40, tmp_path)._authorize()


# ------------------------------------------------------------------ concurrency


def test_database_serves_every_request_thread_at_once(tmp_path):
    """The web server runs up to 40 requests in parallel threads, plus background
    workers. Each holds one connection; a pool smaller than that made bursts wait
    30 s and then fail with server errors."""
    import threading

    from sqlalchemy import text

    app = create_app(db_url=f"sqlite:///{(tmp_path / 'p.sqlite3').as_posix()}", token="")
    sessionmaker = app.state.sessionmaker
    together = threading.Barrier(54, timeout=10)
    failures = []

    def hold():
        try:
            with sessionmaker() as s:
                s.execute(text("SELECT 1"))
                together.wait()
        except Exception as exc:  # noqa: BLE001
            failures.append(type(exc).__name__)

    threads = [threading.Thread(target=hold) for _ in range(54)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert failures == []


def test_heavy_calculations_run_at_most_two_at_a_time(client, monkeypatch):
    """Many request threads computing at once fight over Python's global lock;
    on macOS a burst of 20 took 19 s instead of under 2 s. compute() admits two
    at a time; the rest wait their turn."""
    import threading
    import time

    from app.quant import service

    active, peak = [0], [0]
    lock = threading.Lock()
    real = service.inr_ledger

    def slow_ledger(session):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return real(session)

    monkeypatch.setattr(service, "inr_ledger", slow_ledger)
    sessionmaker = client.app.state.sessionmaker

    def run():
        with sessionmaker() as s:
            service.compute(s, refresh=False)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert 1 <= peak[0] <= service.COMPUTE_SLOTS


def test_compute_inside_compute_does_not_deadlock(client, monkeypatch):
    from app.quant import service

    sessionmaker = client.app.state.sessionmaker
    real = service.inr_ledger
    depth = [0]

    def nested(session):
        if depth[0] < service.COMPUTE_SLOTS + 1:   # deeper than the number of slots
            depth[0] += 1
            service.compute(session, refresh=False)
        return real(session)

    monkeypatch.setattr(service, "inr_ledger", nested)
    with sessionmaker() as s:
        assert service.compute(s, refresh=False)["holdings"] == []


# ------------------------------------------------------------------ number edges

TRADE = '{"symbol": "TCS", "side": "BUY", "quantity": %s, "price": %s, "traded_at": "%s"}'


@pytest.mark.parametrize("qty, price", [("1", "NaN"), ("1", "Infinity"), ("1", "-Infinity"), ("NaN", "100"),
                                        ("1", "1e309"), ("1e400", "100")])
def test_non_finite_numbers_are_refused_not_a_server_error(client, qty, price):
    res = client.post("/api/ledger/trades", content=TRADE % (qty, price, "2025-01-03T10:00:00"),
                      headers={"content-type": "application/json"})
    assert res.status_code == 422 and "finite" in res.json()["detail"]
    assert client.get("/api/ledger/trades").json() == []


def test_non_finite_numbers_refused_on_every_route(client):
    res = client.put("/api/settings", content='{"confidence": NaN}', headers={"content-type": "application/json"})
    assert res.status_code == 422


@pytest.mark.parametrize("qty, price", [("1e308", "100"), ("1", "1e308"), ("2e9", "100"), ("1", "2e9")])
def test_absurd_trade_sizes_are_refused(client, qty, price):
    res = client.post("/api/ledger/trades", content=TRADE % (qty, price, "2025-01-03T10:00:00"),
                      headers={"content-type": "application/json"})
    assert res.status_code == 422


def test_trades_before_1900_are_refused(client):
    res = client.post("/api/ledger/trades", content=TRADE % ("1", "100", "1800-01-01T00:00:00"),
                      headers={"content-type": "application/json"})
    assert res.status_code == 422
