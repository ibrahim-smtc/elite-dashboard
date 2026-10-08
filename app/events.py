"""
Live change events: Postgres LISTEN -> server-sent events -> the dashboard.

One dedicated connection sits on the `dsr_change` channel (see db/triggers.sql).
It dials LISTEN_DSN rather than the pooled DSN: LISTEN registers interest on a
single backend, so it is silently useless through a transaction-mode pooler and
needs the session-mode port. See the note in db.py.
Whatever writes to the database - the dashboard, the bulk loader, tools/sql.py,
an agent - the trigger fires, this listener wakes, and every open dashboard is
told to refetch.

Doing the fan-out here rather than letting each browser poll means one database
connection serves any number of dashboards, and an idle dealership generates no
query traffic at all.

The LISTEN runs on a background *thread* with a synchronous connection, not on
the event loop with an async one. That is deliberate: psycopg's async mode
refuses to run on the ProactorEventLoop that asyncio uses by default on Windows,
and the alternative - forcing WindowsSelectorEventLoopPolicy process-wide - only
works if the app is started through run.py and breaks silently under
`uvicorn app.main:app`. A thread works the same way everywhere.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading

from typing import AsyncIterator

import psycopg

from .db import LISTEN_DSN

log = logging.getLogger("dsr.events")

CHANNEL = "dsr_change"

# Bursts are the norm, not the exception: saving an allotment touches allotment,
# booking and vehicle, and a workbook reload fires thousands of times. Changes
# inside this window collapse into one event so the browser re-renders once.
COALESCE_SECONDS = 0.4

# How often the listener thread checks whether it has been asked to stop.
POLL_SECONDS = 1.0

# A slow or stalled browser must not hold anything up, so each subscriber gets a
# small queue and is dropped from the broadcast if it fills.
QUEUE_SIZE = 32

# What a workbook upload rewrites, and therefore what the dashboard must refetch
# when one lands.
WORKBOOK_TABLES = {
    "lead", "booking", "test_drive", "allotment", "registration", "vehicle",
    "target_daily_tracker", "target_channel_funnel",
    "target_consultant_scorecard", "target_booking_commitment", "etl_run",
}


class ChangeBroker:
    """Fans database notifications out to any number of SSE subscribers."""

    def __init__(self, dsn: str = LISTEN_DSN):
        self.dsn = dsn
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._connected = False
        self._last_error: str | None = None
        self._events_seen = 0
        # Tables changed since the last flush, plus the handle of the pending
        # flush. Both are only touched on the event loop.
        self._pending: set[str] = set()
        self._flush_handle: asyncio.TimerHandle | None = None

    # -- lifecycle ----------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._listen_thread, name="dsr-listen", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stopping.set()
        if self._thread:
            # The thread wakes at least every POLL_SECONDS, so this is bounded.
            await asyncio.to_thread(self._thread.join, POLL_SECONDS * 3)
        if self._flush_handle:
            self._flush_handle.cancel()
        for queue in list(self._subscribers):
            queue.put_nowait(None)

    @property
    def status(self) -> dict:
        return {
            "connected": self._connected,
            "subscribers": len(self._subscribers),
            "events_seen": self._events_seen,
            "last_error": self._last_error,
        }

    # -- the listener thread ------------------------------------------

    def _listen_thread(self) -> None:
        """Hold a LISTEN connection open, reconnecting with backoff if it drops."""
        delay = 1.0
        while not self._stopping.is_set():
            try:
                self._listen_once()
                delay = 1.0
            except Exception as exc:                      # noqa: BLE001
                self._connected = False
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.warning("change listener dropped (%s); retrying in %.0fs",
                            exc, delay)
                if self._stopping.wait(delay):
                    break
                delay = min(delay * 2, 30.0)
        self._connected = False

    def _listen_once(self) -> None:
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(f"LISTEN {CHANNEL}")
            self._connected = True
            self._last_error = None
            log.info("listening on %s", CHANNEL)

            while not self._stopping.is_set():
                # Yields whatever arrives within the window, then returns, which
                # is what gives the stop flag a chance to be seen.
                for note in conn.notifies(timeout=POLL_SECONDS):
                    self._events_seen += 1
                    try:
                        table = json.loads(note.payload).get("table", "?")
                    except (ValueError, AttributeError):
                        table = "?"
                    if self._loop is not None:
                        self._loop.call_soon_threadsafe(self._note, table)

    # -- coalescing, on the event loop --------------------------------

    async def notify(self, kind: str, table: str, data: dict | None = None) -> None:
        """
        Announce a change made by this process, without waiting for the database.

        A bulk load is the case that needs it: the loader writes inside one
        transaction over the transaction pooler, so the trigger's NOTIFY may not
        reach the listener at all. Telling the subscribers directly means an
        upload refreshes every open dashboard even when LISTEN is unavailable.

        `kind` and `data` describe the change for future use; the browser only
        needs the table list, which is what the flush already sends.
        """
        tables = [table]
        if kind == "workbook_reload":
            # A workbook rewrites every fact table, so ask for a full refetch
            # rather than naming the one row that recorded the run.
            tables = sorted(WORKBOOK_TABLES)
        for name in tables:
            self._note(name)

    def notify_sync(self, table: str) -> None:
        """Trigger an immediate notification to subscribers from any thread."""
        try:
            if self._loop is not None and not self._loop.is_closed():
                self._loop.call_soon_threadsafe(self._note, table)
        except Exception as exc:
            log.debug("notify_sync failed: %s", exc)

    def _note(self, table: str) -> None:
        self._pending.add(table)
        if self._flush_handle is None and self._loop is not None:
            self._flush_handle = self._loop.call_later(COALESCE_SECONDS, self._flush)

    def _flush(self) -> None:
        self._flush_handle = None
        if not self._pending:
            return
        event = {"tables": sorted(self._pending)}
        self._pending.clear()
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # The browser is not keeping up. Drop it; EventSource reconnects
                # on its own and refetches everything.
                log.info("dropping a subscriber whose queue was full")
                self._subscribers.discard(queue)

    # -- subscription -------------------------------------------------

    async def stream(self) -> AsyncIterator[str]:
        """Yield SSE frames for one browser, until it disconnects."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(queue)
        try:
            # Tell the client it is connected, so it can show a live indicator
            # without waiting for the first real change.
            yield _frame("ready", self.status)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    # A comment frame stops proxies closing an idle stream.
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                yield _frame("change", event)
        finally:
            self._subscribers.discard(queue)


def _frame(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


broker = ChangeBroker()
