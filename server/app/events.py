"""Change notification: PostgreSQL ``LISTEN``/``NOTIFY`` fanned out as SSE.

``subscribeAll`` and ``subscribeLog`` are live subscriptions. Over HTTP that is
``GET /api/events``, a ``text/event-stream`` that emits one small event per
change. The event carries only what changed, never the document:

* ``project.created`` / ``project.updated`` / ``project.deleted`` -- ``{"id"}``
* ``log.appended`` -- ``{"id"}``
* ``resync`` -- no id; the client should refetch everything

Small payloads are not an aesthetic choice. ``NOTIFY`` caps the payload at
8000 bytes, and a project document can exceed that. Sending an id and letting
the client refetch is the only shape that stays correct as documents grow.

``NOTIFY`` rather than an in-process pub/sub because the whole point is
horizontal scale: with three replicas behind a load balancer, a PATCH that
lands on replica A has to reach the SSE stream a colleague is holding open on
replica C. The database is the one thing all three share.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import asyncpg

from .db import Database

log = logging.getLogger("chai.events")

NOTIFY_PAYLOAD_LIMIT = 7900  # PostgreSQL's hard limit is 8000 bytes

PROJECT_CREATED = "project.created"
PROJECT_UPDATED = "project.updated"
PROJECT_DELETED = "project.deleted"
LOG_APPENDED = "log.appended"
RESYNC = "resync"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class Event:
    """One change, as it goes over the wire."""

    type: str
    id: str | None = None
    at: str = ""

    def with_time(self) -> Event:
        return self if self.at else Event(self.type, self.id, _now())

    def to_json(self) -> str:
        return json.dumps(
            {"type": self.type, "id": self.id, "at": self.at or _now()},
            separators=(",", ":"),
        )

    @staticmethod
    def from_json(payload: str) -> Event:
        data: dict[str, Any] = json.loads(payload)
        return Event(
            type=str(data.get("type") or RESYNC),
            id=data.get("id"),
            at=str(data.get("at") or _now()),
        )

    def sse(self) -> str:
        """Format as an SSE frame."""
        return f"event: {self.type}\ndata: {self.to_json()}\n\n"


class _Subscriber:
    """One open SSE stream.

    A slow or stalled reader must not hold events in memory for everyone else,
    so an overflowing queue is emptied and replaced by a single ``resync``:
    the client refetches and is correct again, which is what it would have been
    after replaying the backlog anyway.
    """

    __slots__ = ("_maxsize", "queue")

    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)

    def offer(self, event: Event) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            while not self.queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    self.queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                self.queue.put_nowait(Event(RESYNC, None, _now()))
            log.warning("SSE subscriber fell behind; sent resync instead of backlog")


class EventBroker:
    """Publishes changes to every replica, and hands them to local streams."""

    def __init__(
        self,
        db: Database,
        *,
        channel: str = "chai_events",
        queue_size: int = 256,
    ) -> None:
        self._db = db
        self._channel = channel
        self._queue_size = queue_size
        self._subscribers: set[_Subscriber] = set()
        self._conn: asyncpg.Connection | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._stopping = False
        self.local_only = False
        """True when LISTEN could not be established.

        Events still reach streams served by *this* process, but not other
        replicas. Happens behind a transaction-pooling connection proxy such as
        PgBouncer, which cannot hold a listening session. Run a single replica,
        or point the API at the database directly, if you see this.
        """

    # --- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        self._stopping = False
        try:
            await self._open_listener()
        except (OSError, asyncpg.PostgresError) as exc:
            self.local_only = True
            log.error(
                "could not LISTEN on %r (%s). Falling back to in-process events: "
                "changes will NOT reach other replicas.",
                self._channel,
                exc,
            )
            return
        self._supervisor = asyncio.create_task(
            self._supervise(), name="chai-events-supervisor"
        )

    async def _open_listener(self) -> None:
        conn = await self._db.listener_connection()
        await conn.add_listener(self._channel, self._on_notify)
        self._conn = conn
        self.local_only = False
        log.info("listening for changes on channel %r", self._channel)

    async def _supervise(self) -> None:
        """Reopen the listening connection if the database drops it.

        A managed Postgres failover closes every session. Without this the SSE
        streams stay open and silently stop delivering, which is the worst of
        both worlds.
        """
        while not self._stopping:
            await asyncio.sleep(5.0)
            conn = self._conn
            if conn is not None and not conn.is_closed():
                continue
            if self._stopping:
                return
            log.warning("listener connection lost; reconnecting")
            try:
                await self._open_listener()
            except (OSError, asyncpg.PostgresError) as exc:
                log.warning("listener reconnect failed: %s", exc)
                continue
            # Anything that happened while we were disconnected was missed.
            self._fanout(Event(RESYNC, None, _now()))

    async def stop(self) -> None:
        self._stopping = True
        if self._supervisor is not None:
            self._supervisor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._supervisor
            self._supervisor = None
        conn, self._conn = self._conn, None
        if conn is not None and not conn.is_closed():
            with contextlib.suppress(Exception):
                await conn.remove_listener(self._channel, self._on_notify)
            with contextlib.suppress(Exception):
                await conn.close()

    # --- publish / subscribe ---------------------------------------------

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        """asyncpg calls this on the event loop thread, so no locking needed."""
        try:
            event = Event.from_json(payload)
        except (ValueError, TypeError) as exc:
            log.warning("ignoring malformed notification %r: %s", payload, exc)
            return
        self._fanout(event)

    def _fanout(self, event: Event) -> None:
        for sub in list(self._subscribers):
            sub.offer(event)

    async def publish(self, event: Event, conn: asyncpg.Connection) -> None:
        """Announce a change.

        Call this as the **last statement inside** the writing transaction. The
        notification is then queued by PostgreSQL and delivered only if the
        transaction commits, so a rolled-back write never produces an event.

        In ``local_only`` mode there is no transactional guarantee available,
        so the fan-out happens immediately. The only failure that can follow is
        the commit itself, and a spurious event costs one client refetch.
        """
        event = event.with_time()
        payload = event.to_json()
        if len(payload.encode("utf-8")) > NOTIFY_PAYLOAD_LIMIT:  # pragma: no cover
            payload = Event(RESYNC, None, event.at).to_json()
        if self.local_only:
            self._fanout(event)
            return
        # The notify runs on the CALLER'S connection, inside the caller's write
        # transaction -- that is deliberate, so no event is delivered for a
        # write that later rolls back. But it means a failed pg_notify leaves
        # PostgreSQL's transaction in the ABORTED state, where every later
        # statement, including the caller's COMMIT, fails. Catching the error
        # here is then actively harmful: the caller believes it may continue,
        # and its write is silently lost while subscribers have been told it
        # succeeded.
        #
        # The savepoint confines that. asyncpg issues SAVEPOINT rather than
        # BEGIN when a transaction is already open, so a failure rolls back to
        # the savepoint and the outer transaction stays usable.
        try:
            async with conn.transaction():
                await conn.execute("SELECT pg_notify($1, $2)", self._channel, payload)
        except asyncpg.PostgresError as exc:  # pragma: no cover - degraded path
            log.warning("pg_notify failed (%s); delivering locally", exc)
            self._fanout(event)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Event]]:
        """``async with broker.subscribe() as queue:`` for one SSE stream."""
        sub = _Subscriber(self._queue_size)
        self._subscribers.add(sub)
        log.debug("SSE subscriber attached (%d open)", len(self._subscribers))
        try:
            yield sub.queue
        finally:
            self._subscribers.discard(sub)
            log.debug("SSE subscriber detached (%d open)", len(self._subscribers))

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
