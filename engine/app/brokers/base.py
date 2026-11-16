"""Shared shape of a broker or data source.

A source declares the credential fields it needs, what it can do
(`capabilities`), and how a login session is opened. Credentials live in the
OS keychain through `TokenStore`s and are never returned by the API: the UI
only learns whether each field is set and where it came from."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.ledger.upstox import ParsedTrade
    from app.secrets import TokenStore

# Broker access tokens in India expire every morning around 06:00 IST.
SESSION_RESET_HOUR = 6


class BrokerError(RuntimeError):
    """A failure the user can act on. `status` becomes the HTTP status."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class FeedUnavailable(RuntimeError):
    retry_seconds = 60.0


class UnavailableFeed:
    """Stands in for a chosen price source that cannot run yet, so the ribbon
    says why (for example, 'log in to Zerodha') instead of silently falling back."""

    retry_seconds = 60.0

    def __init__(self, name: str, message: str):
        self.name = name
        self.message = message

    async def run(self, hub) -> None:
        raise FeedUnavailable(self.message)


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    secret: bool = True
    required: bool = True
    help: str = ""


@dataclass
class Holding:
    symbol: str          # Yahoo symbol
    isin: str
    name: str
    quantity: float
    avg_price: float


def last_reset(now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    reset = now.replace(hour=SESSION_RESET_HOUR, minute=0, second=0, microsecond=0)
    return reset if now >= reset else reset - timedelta(days=1)


class Source:
    """Base class. Subclasses set the class attributes and override what they support."""

    id: str = ""
    label: str = ""
    kind: str = "broker"                 # broker | data
    fields: tuple[Field, ...] = ()
    capabilities: frozenset[str] = frozenset()   # csv | holdings | trades | live
    login: str = "none"                  # none | redirect | generate
    experimental: bool = False
    notes: str = ""
    live_note: str = ""

    def __init__(self, stores: dict[str, "TokenStore"] | None = None):
        self.stores = stores or {}

    # ---- credentials

    def value(self, name: str) -> str | None:
        store = self.stores.get(name)
        return store.get() if store else None

    def configured(self) -> bool:
        return all(self.value(f.name) for f in self.fields if f.required)

    def save(self, values: dict[str, str]) -> None:
        known = {f.name for f in self.fields}
        unknown = sorted(set(values) - known)
        if unknown:
            raise BrokerError(f"{self.label} has no field named {', '.join(unknown)}", status=400)
        for name, raw in values.items():
            value = (raw or "").strip()
            if not value:
                continue  # an empty box keeps what is already saved
            if any(c.isspace() for c in value):
                raise BrokerError(f"{self._label_of(name)} contains spaces; paste it again", status=400)
            try:
                self.stores[name].set(value)
            except RuntimeError as exc:
                raise BrokerError(str(exc), status=500) from exc
        self.end_session()  # new credentials invalidate an old session

    def clear(self) -> None:
        for store in self.stores.values():
            store.clear()

    def _label_of(self, name: str) -> str:
        return next((f.label for f in self.fields if f.name == name), name)

    # ---- login session (brokers whose access token expires daily)

    def session_token(self) -> str | None:
        """The access token if one exists and was issued after the last 06:00 reset."""
        store = self.stores.get("access_token")
        raw = store.get() if store else None
        if not raw:
            return None
        if store.source() == "environment":
            return raw  # the user manages its lifetime
        issued, _, token = raw.partition("|")
        try:
            fresh = datetime.fromisoformat(issued) >= last_reset()
        except ValueError:
            return None
        return token if fresh and token else None

    def _store_session(self, token: str) -> None:
        self.stores["access_token"].set(f"{datetime.now().isoformat(timespec='seconds')}|{token}")

    def end_session(self) -> None:
        store = self.stores.get("access_token")
        if store is not None and store.source() != "environment":
            store.clear()

    def session_state(self) -> dict[str, Any]:
        if self.login == "none":
            return {"needed": False, "active": self.configured()}
        store = self.stores.get("access_token")
        raw = store.get() if store else None
        issued = raw.partition("|")[0] if raw and "|" in raw else None
        return {"needed": True, "active": self.session_token() is not None, "issued": issued}

    def login_url(self) -> str | None:
        return None

    def start_session(self, value: str | None) -> None:
        raise BrokerError(f"{self.label} has no login step", status=400)

    # ---- data

    def fetch_holdings(self) -> list[Holding]:
        raise BrokerError(f"{self.label} does not provide holdings here", status=400)

    def fetch_trades(self) -> list["ParsedTrade"]:
        raise BrokerError(f"{self.label} does not provide trades here", status=400)

    def make_feed(self, cache_dir: Path):
        return None

    # ---- what the UI sees

    def status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "capabilities": sorted(self.capabilities),
            "login": self.login,
            "experimental": self.experimental,
            "notes": self.notes,
            "live_note": self.live_note,
            "configured": self.configured(),
            "session": self.session_state(),
            "fields": [
                {"name": f.name, "label": f.label, "secret": f.secret, "required": f.required,
                 "help": f.help, "set": bool(self.value(f.name)),
                 "source": self.stores[f.name].source() if f.name in self.stores else None}
                for f in self.fields
            ],
        }
