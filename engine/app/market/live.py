"""Live price hub. A feed adapter pushes quotes in; the hub keeps the latest
quote per symbol, marks the portfolio to market, and fans a snapshot out to
every connected WebSocket client at most once a second. Read-only: nothing
here can send an order."""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Protocol

from fastapi import WebSocket

from app.ledger.positions import EPS, build_positions
from app.quant import service

BROADCAST_INTERVAL = 1.0
log = logging.getLogger(__name__)


def _finite(obj):
    """Copy of obj with NaN/inf floats replaced by None (strict JSON)."""
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_finite(v) for v in obj]
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


class Feed(Protocol):
    name: str
    retry_seconds: float

    async def run(self, hub: "LiveHub") -> None: ...


class LiveHub:
    def __init__(self, sessionmaker, feed: Feed):
        self._sessionmaker = sessionmaker
        self.feed = feed
        self.quotes: dict[str, dict] = {}
        self.clients: set[WebSocket] = set()
        self.status = {"source": feed.name, "state": "connecting", "detail": ""}
        self._dirty: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        self._feed_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._dirty = asyncio.Event()
        self._feed_task = asyncio.create_task(self._run_feed())
        self._tasks = [asyncio.create_task(self._broadcast())]

    async def stop(self) -> None:
        for task in [self._feed_task, *self._tasks]:
            task.cancel()
        await asyncio.gather(self._feed_task, *self._tasks, return_exceptions=True)
        self._tasks = []

    async def set_feed(self, feed: Feed) -> None:
        """Swap the price source without restarting the engine (e.g. after the
        Upstox token is saved or removed). Existing quotes are kept until replaced."""
        self._feed_task.cancel()
        await asyncio.gather(self._feed_task, return_exceptions=True)
        self.feed = feed
        self.set_status("connecting")
        self._feed_task = asyncio.create_task(self._run_feed())

    # --- called by feed adapters (on the event loop) ---

    def on_quote(self, symbol: str, ltp: float, prev_close: float | None, ts: float | None = None) -> None:
        # NaN slips past `ltp <= 0`, and one NaN makes the whole snapshot invalid
        # JSON, which the browser silently drops: every price would freeze.
        try:
            ltp = float(ltp)
            prev = float(prev_close) if prev_close is not None else None
        except (TypeError, ValueError):
            return
        if not math.isfinite(ltp) or ltp <= 0:
            return
        prev = prev if prev is not None and math.isfinite(prev) and prev > 0 else None
        self.quotes[symbol] = {
            "ltp": float(ltp),
            "prev_close": prev,
            "change": float(ltp - prev) if prev else None,
            "change_pct": float(ltp / prev - 1) if prev else None,
            "ts": float(ts) if ts and math.isfinite(ts) else time.time(),
        }
        if self._dirty is not None:
            self._dirty.set()

    def set_status(self, state: str, detail: str = "") -> None:
        new = {"source": self.feed.name, "state": state, "detail": detail}
        if new != self.status:
            self.status = new
            if self._dirty is not None:
                self._dirty.set()

    def held_symbols(self) -> list[str]:
        with self._sessionmaker() as session:
            positions = service.load_positions(session)
        return sorted(s for s, p in positions.items() if p.quantity > EPS)

    def tracked_symbols(self) -> list[str]:
        """Holdings plus the benchmark, so beta and alpha can move intraday.
        Feeds that can quote any Yahoo symbol use this; broker feeds that need
        instrument keys stay on held_symbols."""
        held = self.held_symbols()
        with self._sessionmaker() as session:
            bench = service.get_settings(session)["benchmark"]
        return held + ([bench] if held and bench and bench not in held else [])

    # --- called by API routes (possibly from worker threads) ---

    def poke(self) -> None:
        """Ledger changed: rebuild and resend the snapshot."""
        if self._loop and self._dirty:
            self._loop.call_soon_threadsafe(self._dirty.set)

    # --- snapshot and fan-out ---

    def snapshot(self, quotes: dict | None = None) -> dict:
        """`quotes` is a copy taken on the event loop; feeds keep adding to
        self.quotes while this runs on a worker thread."""
        quotes = dict(self.quotes) if quotes is None else quotes
        with self._sessionmaker() as session:
            trades, actions, rates, _ = service.inr_ledger(session)
        positions = build_positions(trades, actions)
        held = {s: p for s, p in positions.items() if p.quantity > EPS}
        rows: dict[str, dict] = {}
        for symbol, pos in held.items():
            quote = quotes.get(symbol)
            fx = rates.rate(symbol)      # quotes are in the listing's currency; the ledger is in INR
            if not quote or fx is None:
                continue
            value = pos.quantity * quote["ltp"] * fx
            rows[symbol] = {
                "value": value,
                "unrealized_pnl": value - pos.cost_value,
                "day_pnl": pos.quantity * quote["change"] * fx if quote["change"] is not None else None,
            }
        day = [r["day_pnl"] for r in rows.values() if r["day_pnl"] is not None]
        return {
            "type": "snapshot",
            "status": dict(self.status),
            "quotes": quotes,
            "portfolio": {
                "held": len(held),
                "priced": len(rows),
                "value": sum(r["value"] for r in rows.values()),
                "unrealized_pnl": sum(r["unrealized_pnl"] for r in rows.values()),
                "day_pnl": sum(day) if day else None,
                "holdings": rows,
            },
        }

    def quotes_copy(self) -> dict:
        """Copy of the quotes, taken on the event loop (where feeds write them)."""
        return {s: dict(q) for s, q in self.quotes.items()}

    def safe_snapshot(self, quotes: dict | None = None) -> dict:
        """The snapshot as strict JSON (non-finite numbers become null). If it
        cannot be built (e.g. the database is busy mid-import), the quotes and
        status still go out and the error is reported in the status detail."""
        quotes = self.quotes_copy() if quotes is None else quotes
        try:
            return _finite(self.snapshot(quotes))
        except Exception as exc:
            log.warning("live snapshot failed: %s", exc)
            status = {**self.status, "detail": f"Portfolio not updated: {exc.__class__.__name__}"}
            return _finite({"type": "snapshot", "status": status, "quotes": quotes, "portfolio": None})

    async def _encoded(self) -> str:
        message = await asyncio.to_thread(self.safe_snapshot, self.quotes_copy())
        return json.dumps(message, allow_nan=False)

    async def add(self, ws: WebSocket) -> None:
        await ws.send_text(await self._encoded())
        self.clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _broadcast(self) -> None:
        # One failure must never end this loop: if it did, every client would
        # keep its socket open but receive nothing again until a restart.
        while True:
            try:
                await self._dirty.wait()
                self._dirty.clear()
                if self.clients:
                    text = await self._encoded()
                    for ws in list(self.clients):
                        try:
                            await ws.send_text(text)
                        except Exception:
                            self.clients.discard(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:          # pragma: no cover - defensive
                log.exception("live broadcast failed: %s", exc)
            await asyncio.sleep(BROADCAST_INTERVAL)

    async def _run_feed(self) -> None:
        while True:
            try:
                await self.feed.run(self)
                self.set_status("connecting", "Feed closed; reconnecting")
                wait = self.feed.retry_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.set_status("error", str(exc) or exc.__class__.__name__)
                wait = getattr(exc, "retry_seconds", self.feed.retry_seconds)
            await asyncio.sleep(wait)
