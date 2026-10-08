"""A LISTEN that fails at startup must be retried, and must be visible (#43).

``EventBroker.start()`` used to try ``_open_listener()`` once, and on failure set
``local_only`` and return WITHOUT starting the supervisor that reconnects. So a
transient refusal at boot, which is exactly when the database is most likely to
refuse (the API starts the moment it reports healthy), left the process in
local-only mode for its whole life. With more than one replica a change written
on one never reached a browser on another, and the only signal was one log line.

The database here is real. What is made to fail is the *listening connection*,
the way a database that is not yet accepting connections fails it: a wrapper
refuses the first attempts and then delegates to the real ``Database``.
"""

from __future__ import annotations

import asyncio

import pytest
from app.events import PROJECT_UPDATED, Event, EventBroker
from httpx import AsyncClient

from .conftest import requires_db

pytestmark = [requires_db, pytest.mark.db]


class FlakyListener:
    """The real Database, except the first ``refuse`` listener connections fail."""

    def __init__(self, db, refuse: int | float) -> None:
        self._db = db
        self.refuse = refuse
        self.attempts = 0

    def __getattr__(self, name: str):
        return getattr(self._db, name)

    async def listener_connection(self):
        self.attempts += 1
        if self.attempts <= self.refuse:
            raise ConnectionRefusedError("the database is not accepting connections")
        return await self._db.listener_connection()


async def until(predicate, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_a_listen_that_fails_at_startup_is_retried(client: AsyncClient) -> None:
    db = FlakyListener(client.app.state.db, refuse=2)
    broker = EventBroker(db, channel="chai_events_retry", retry_seconds=0.05)
    await broker.start()
    try:
        assert broker.local_only, "the first attempt failed, so it starts degraded"
        assert await until(lambda: not broker.local_only), (
            f"never recovered after {db.attempts} attempts: the supervisor is not "
            "running, so a startup failure is permanent"
        )
        assert db.attempts == 3
    finally:
        await broker.stop()


async def test_after_recovering_a_change_travels_through_postgres(
    client: AsyncClient,
) -> None:
    """Recovered means LISTEN works, not just that a flag flipped."""
    db = FlakyListener(client.app.state.db, refuse=1)
    broker = EventBroker(db, channel="chai_events_retry2", retry_seconds=0.05)
    await broker.start()
    try:
        assert await until(lambda: not broker.local_only)
        async with broker.subscribe(None) as queue:
            while not queue.empty():  # the resync sent on recovery
                queue.get_nowait()
            async with db.acquire() as conn, conn.transaction():
                await broker.publish(Event(PROJECT_UPDATED, "p1"), conn)
            event = await asyncio.wait_for(queue.get(), timeout=5)
        assert event.id == "p1"
    finally:
        await broker.stop()


async def test_a_listener_that_never_works_backs_off(client: AsyncClient) -> None:
    """PgBouncer cannot LISTEN at all. Retrying forever is right; hammering is not."""
    db = FlakyListener(client.app.state.db, refuse=float("inf"))
    broker = EventBroker(
        db, channel="chai_events_retry3", retry_seconds=0.02, max_retry_seconds=0.5
    )
    await broker.start()
    try:
        await asyncio.sleep(1.0)
        assert broker.local_only
        # 0.02 flat would be about 50 attempts in a second; doubling to a 0.5
        # ceiling is about 7.
        assert 2 <= db.attempts <= 12, db.attempts
    finally:
        await broker.stop()


async def test_health_says_when_events_are_local_only(client: AsyncClient) -> None:
    healthy = (await client.get("/api/health")).json()
    assert healthy["events"] == "live"

    broker = client.app.state.broker
    await broker.stop()
    broker._db = FlakyListener(client.app.state.db, refuse=float("inf"))
    await broker.start()  # a real failed start, not a flag set by hand
    try:
        response = await client.get("/api/health")
        assert response.status_code == 200, "degraded is not down"
        assert response.json()["events"] == "local-only"
        assert response.json()["status"] == "ok"
    finally:
        await broker.stop()
