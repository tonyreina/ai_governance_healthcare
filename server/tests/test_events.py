"""The change stream, over a real socket.

These tests run uvicorn rather than going through ``httpx.ASGITransport``,
because that transport buffers the whole response body before returning it --
an endless ``text/event-stream`` can never be read through it. Testing SSE
without a socket would be testing something other than SSE.

What this covers that nothing else does: a write on one connection reaches a
subscriber on another, by way of PostgreSQL ``LISTEN``/``NOTIFY``. That is the
mechanism that lets a second replica serve the stream for a change written by
the first.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator

import asyncpg
import pytest
import uvicorn
from app.config import Settings
from app.events import Event
from app.main import create_app
from httpx import AsyncClient

from .conftest import TEST_EMAIL, TEST_HEADERS, requires_db

pytestmark = [requires_db, pytest.mark.db]


@pytest.fixture
async def base_url(settings: Settings) -> AsyncIterator[str]:
    """A uvicorn server on an ephemeral port, torn down after the test."""
    app = create_app(settings)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())

    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:  # pragma: no cover - startup failure
        server.should_exit = True
        await serving
        pytest.fail("uvicorn did not start")

    sock: socket.socket = server.servers[0].sockets[0]
    async with app.state.db.acquire() as conn:
        await conn.execute("TRUNCATE project_log, projects RESTART IDENTITY CASCADE")

    try:
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        await serving


async def read_events(
    url: str, want: str, timeout: float = 15.0
) -> list[tuple[str, dict]]:
    """Hold the stream open until ``want`` arrives, then return what was seen."""
    seen: list[tuple[str, dict]] = []

    async def pump() -> None:
        async with AsyncClient(base_url=url, headers=TEST_HEADERS) as http:
            async with http.stream("GET", "/api/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                assert response.headers["x-accel-buffering"] == "no"
                assert "no-cache" in response.headers["cache-control"]
                name = ""
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        seen.append((name, json.loads(line.split(":", 1)[1])))
                        if name == want:
                            return

    await asyncio.wait_for(pump(), timeout=timeout)
    return seen


async def test_a_change_reaches_an_open_stream(base_url: str) -> None:
    async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
        assert (await http.post("/api/projects/pev1", json={"a": 1})).status_code == 201

        reader = asyncio.create_task(read_events(base_url, "project.updated"))
        await asyncio.sleep(0.5)  # let the subscription attach before writing
        assert (
            await http.patch("/api/projects/pev1", json={"b": 2})
        ).status_code == 200
        seen = await reader

    names = [name for name, _ in seen]
    assert names[0] == "hello", "the stream must emit a frame immediately"
    assert "project.updated" in names
    payload = dict(seen[-1][1])
    assert payload["id"] == "pev1"
    assert payload["at"]


async def test_each_kind_of_change_announces_itself(base_url: str) -> None:
    async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
        reader = asyncio.create_task(read_events(base_url, "project.deleted"))
        await asyncio.sleep(0.5)
        await http.post("/api/projects/pev2", json={"a": 1})
        await http.post("/api/projects/pev2/log", json={"text": "created"})
        await http.delete("/api/projects/pev2")
        seen = await reader

    names = [name for name, _ in seen]
    assert "project.created" in names
    assert "log.appended" in names
    assert "project.deleted" in names


async def test_the_stream_carries_ids_not_documents(base_url: str) -> None:
    """Keeps every event far below NOTIFY's 8000-byte payload cap."""
    big = {"card": {"intended_use": "x" * 20000}}
    async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
        await http.post("/api/projects/pev3", json={"a": 1})
        reader = asyncio.create_task(read_events(base_url, "project.updated"))
        await asyncio.sleep(0.5)
        assert (await http.patch("/api/projects/pev3", json=big)).status_code == 200
        seen = await reader

    _, payload = seen[-1]
    assert set(payload) == {"type", "id", "at"}
    assert "x" * 100 not in json.dumps(payload)
    assert len(json.dumps(payload).encode()) < 200


async def test_a_rolled_back_write_produces_no_event(base_url: str) -> None:
    """The notify is issued inside the transaction, so a 409 is silent."""
    async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
        await http.post("/api/projects/pev4", json={"a": 1})

        collected: list[str] = []

        async def pump() -> None:
            async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as stream:
                async with stream.stream("GET", "/api/events") as response:
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            collected.append(line.split(":", 1)[1].strip())

        reader = asyncio.create_task(pump())
        await asyncio.sleep(0.5)
        assert (await http.post("/api/projects/pev4", json={"a": 2})).status_code == 409
        assert (
            await http.patch("/api/projects/pnothere", json={"a": 1})
        ).status_code == 404
        await asyncio.sleep(1.0)
        reader.cancel()

    assert collected == ["hello"], f"a failed write emitted {collected}"


async def test_an_idle_stream_sends_a_heartbeat(base_url: str) -> None:
    """Without it, an idle stream is indistinguishable from a dead one, and
    every cloud load balancer eventually closes it."""
    chunks: list[str] = []

    async def pump() -> None:
        async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
            async with http.stream("GET", "/api/events") as response:
                async for line in response.aiter_lines():
                    chunks.append(line)
                    if line.startswith(": ping"):
                        return

    # sse_keepalive_seconds is 1.0 in the test settings.
    await asyncio.wait_for(pump(), timeout=15)
    assert any(line.startswith(": ping") for line in chunks)


def test_sse_framing_is_well_formed() -> None:
    frame = Event("project.updated", "p1", "2026-10-05T12:00:00.000+00:00").sse()
    assert frame.startswith("event: project.updated\ndata: {")
    assert frame.endswith("\n\n")
    name, data = frame.strip().split("\n", 1)
    assert json.loads(data.removeprefix("data: ")) == {
        "type": "project.updated",
        "id": "p1",
        "at": "2026-10-05T12:00:00.000+00:00",
    }
    assert name == "event: project.updated"


async def watch_events(
    url: str, email: str, *, window: float = 2.5
) -> list[tuple[str, dict]]:
    """Hold a stream open for `window` seconds and return every frame seen.

    Unlike read_events() this does not wait for a particular event, because
    the interesting assertion here is usually that NOTHING arrived.

    The loop ends on its own deadline rather than being canceled from the
    outside by wait_for(). Canceling mid-iteration leaves the connection open
    as far as uvicorn is concerned, and the server fixture's graceful shutdown
    then waits on it until the whole test session times out -- which is also
    why read_events() above returns from inside its loop rather than being
    canceled.

    The 1s keepalive in the test settings is what makes the deadline prompt: a
    stream with nothing to say still delivers a `: ping` comment line.
    """
    seen: list[tuple[str, dict]] = []
    deadline = asyncio.get_running_loop().time() + window

    async with AsyncClient(base_url=url, headers={"X-Forwarded-Email": email}) as http:
        async with http.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            name = ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    seen.append((name, json.loads(line.split(":", 1)[1])))
                if asyncio.get_running_loop().time() >= deadline:
                    break
    return seen


class TestStreamsAreFiltered:
    """A stream must only carry ids its holder is allowed to know changed.

    Before this, every authenticated user received project.created/.updated/
    .deleted/log.appended for every project in the portfolio, including ones
    GET /api/projects correctly filtered out of their view -- so the id and
    the change cadence of a restricted record leaked to anyone with an
    account.
    """

    async def test_a_stranger_does_not_see_a_restricted_project_change(
        self, base_url: str
    ) -> None:
        async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
            await http.post(
                "/api/projects/pef1",
                json={
                    "meta": {"solution": "Restricted"},
                    "access": {
                        "owners": [TEST_EMAIL],
                        "writers": [],
                        "readers": [],
                    },
                },
            )
            watcher = asyncio.create_task(watch_events(base_url, "stranger@elsewhere"))
            await asyncio.sleep(0.5)
            await http.patch("/api/projects/pef1", json={"meta": {"org": "Secret"}})
            await http.post("/api/projects/pef1/log", json={"text": "signed off"})
            seen = await watcher

        names = [name for name, _ in seen]
        assert names == ["hello"], f"stranger saw {names}"

    async def test_a_reader_does_see_it(self, base_url: str) -> None:
        async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
            await http.post(
                "/api/projects/pef2",
                json={
                    "meta": {"solution": "Shared"},
                    "access": {
                        "owners": [TEST_EMAIL],
                        "writers": [],
                        "readers": ["reader@x"],
                    },
                },
            )
            watcher = asyncio.create_task(watch_events(base_url, "reader@x"))
            await asyncio.sleep(0.5)
            await http.patch("/api/projects/pef2", json={"meta": {"org": "Visible"}})
            seen = await watcher

        names = [name for name, _ in seen]
        assert "project.updated" in names, names
        assert any(
            payload.get("id") == "pef2" for name, payload in seen if name != "hello"
        )

    async def test_an_unclaimed_project_is_visible_to_everyone(
        self, base_url: str, settings: Settings
    ) -> None:
        """Unclaimed means unrestricted, exactly as access.py has it.

        The row is inserted directly rather than created and then stripped of
        its owner: guard_access_change correctly refuses to remove the last
        owner, so there is no way to reach this state through the API. It is
        the state of every project created before access control existed.
        """
        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.set_type_codec(
                "jsonb",
                encoder=json.dumps,
                decoder=json.loads,
                schema="pg_catalog",
            )
            await conn.execute(
                "INSERT INTO projects (id, doc) VALUES ('pef3', $1) "
                "ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc",
                {"meta": {"solution": "Legacy"}},
            )
        finally:
            await conn.close()

        async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
            watcher = asyncio.create_task(watch_events(base_url, "anyone@elsewhere"))
            await asyncio.sleep(0.5)
            assert (
                await http.patch("/api/projects/pef3", json={"meta": {"org": "X"}})
            ).status_code == 200
            seen = await watcher

        assert "project.updated" in [name for name, _ in seen]


class TestAudienceNeverLeaves:
    def test_the_audience_never_reaches_a_client(self) -> None:
        """to_json() is the SSE frame; to_notify() is the internal payload."""
        event = Event("project.updated", "p1", "2026-01-01", frozenset({"a@b"}))
        assert "a@b" not in event.to_json()
        assert "a@b" not in event.sse()
        assert "a@b" in event.to_notify(), "other replicas still need it"

    def test_an_audience_survives_a_round_trip_through_notify(self) -> None:
        event = Event("project.updated", "p1", "2026-01-01", frozenset({"a@b"}))
        assert Event.from_json(event.to_notify()).audience == frozenset({"a@b"})

    def test_with_time_keeps_the_audience(self) -> None:
        event = Event("project.updated", "p1", audience=frozenset({"a@b"}))
        assert event.with_time().audience == frozenset({"a@b"})

    def test_visibility(self) -> None:
        unrestricted = Event("project.updated", "p1")
        assert unrestricted.visible_to(None)
        assert unrestricted.visible_to("anyone@x")

        restricted = Event("project.updated", "p1", audience=frozenset({"a@b"}))
        assert restricted.visible_to("a@b")
        assert not restricted.visible_to("c@d")
        assert not restricted.visible_to(None)
