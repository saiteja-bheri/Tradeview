"""Live price hub. A feed adapter pushes quotes in; the hub keeps the latest
quote per symbol, marks the portfolio to market, and fans a snapshot out to
every connected WebSocket client at most once a second. Read-only: nothing
here can send an order."""
from __future__ import annotations

import asyncio
import time
from typing import Protocol

from fastapi import WebSocket

from app.ledger.positions import EPS, build_positions
from app.quant import service

BROADCAST_INTERVAL = 1.0


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
        if not ltp or ltp <= 0:
            return
        prev = prev_close if prev_close and prev_close > 0 else None
        self.quotes[symbol] = {
            "ltp": float(ltp),
            "prev_close": prev,
            "change": float(ltp - prev) if prev else None,
            "change_pct": float(ltp / prev - 1) if prev else None,
            "ts": ts or time.time(),
        }
        self._dirty.set()

    def set_status(self, state: str, detail: str = "") -> None:
        new = {"source": self.feed.name, "state": state, "detail": detail}
        if new != self.status:
            self.status = new
            self._dirty.set()

    def held_symbols(self) -> list[str]:
        with self._sessionmaker() as session:
            positions = service.load_positions(session)
        return sorted(s for s, p in positions.items() if p.quantity > EPS)

    # --- called by API routes (possibly from worker threads) ---

    def poke(self) -> None:
        """Ledger changed: rebuild and resend the snapshot."""
        if self._loop and self._dirty:
            self._loop.call_soon_threadsafe(self._dirty.set)

    # --- snapshot and fan-out ---

    def snapshot(self) -> dict:
        with self._sessionmaker() as session:
            trades, actions, rates, _ = service.inr_ledger(session)
        positions = build_positions(trades, actions)
        held = {s: p for s, p in positions.items() if p.quantity > EPS}
        rows: dict[str, dict] = {}
        for symbol, pos in held.items():
            quote = self.quotes.get(symbol)
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
            "status": self.status,
            "quotes": self.quotes,
            "portfolio": {
                "held": len(held),
                "priced": len(rows),
                "value": sum(r["value"] for r in rows.values()),
                "unrealized_pnl": sum(r["unrealized_pnl"] for r in rows.values()),
                "day_pnl": sum(day) if day else None,
                "holdings": rows,
            },
        }

    async def add(self, ws: WebSocket) -> None:
        await ws.send_json(await asyncio.to_thread(self.snapshot))
        self.clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def _broadcast(self) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            if self.clients:
                message = await asyncio.to_thread(self.snapshot)
                for ws in list(self.clients):
                    try:
                        await ws.send_json(message)
                    except Exception:
                        self.clients.discard(ws)
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
