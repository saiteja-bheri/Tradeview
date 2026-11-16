from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Caches and instrument lists go to a temp folder, never the user's real data dir."""
    monkeypatch.setenv("QT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("QT_FEED", raising=False)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Broker, fund and BSE calls all go through app.brokers.http; tests that
    need them replace these with fakes."""
    from app.brokers import http

    def blocked(*a, **k):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(http, "get_bytes", blocked)
    monkeypatch.setattr(http, "call", blocked)


@pytest.fixture
def client(tmp_path):
    app = create_app(db_url=f"sqlite:///{(tmp_path / 'test.sqlite3').as_posix()}", token="")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def upstox_csv() -> bytes:
    return (FIXTURES / "upstox_tradebook.csv").read_bytes()


def fake_fetch(symbol, start):
    """Deterministic price path per symbol; no network."""
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)
    rng = np.random.default_rng(sum(map(ord, symbol)))
    market = np.random.default_rng(7).normal(0.0004, 0.01, len(days))
    own = rng.normal(0.0, 0.008, len(days))
    rets = market if symbol.startswith("^") else 1.2 * market + own
    close = 1000 * np.cumprod(1 + rets)
    frame = pd.DataFrame({"close": close, "adj_close": close, "dividend": 0.0, "split": 0.0},
                         index=days.date)
    return frame
