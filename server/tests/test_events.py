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

import pytest
import uvicorn
from app.config import Settings
from app.events import Event
from app.main import create_app
from httpx import AsyncClient

from .conftest import TEST_HEADERS, requires_db

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
