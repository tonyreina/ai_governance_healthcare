"""A denied request must leave a trace (#53).

An authenticated, correctly proxied user reaching for a record they have no role
on produced nothing at all: `require()` raised and nothing logged, and the 404
that hides a project's existence from a non-reader was equally silent. So "this
account was compromised; did it try records it had no business with?" had no
answer, short of Caddy's uncollected access log, which cannot tell a denial from
a hit. Denied access is the highest-signal, lowest-volume event this system
produces, so each denial now logs one line with a stable name, the actor, the
project, what was needed and what they held.

The line must not leak what the denial protected: the project id is necessary,
the document is not.
"""

from __future__ import annotations

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, TEST_HEADERS, requires_db

pytestmark = [requires_db, pytest.mark.db]

STRANGER = "stranger@hospital.example"
READER = "reader@hospital.example"
WRITER = "writer@hospital.example"
SECRET = "patient-identifier-MRN-4471-in-evidence"


def headers_for(email: str) -> dict[str, str]:
    return {**TEST_HEADERS, "X-Forwarded-Email": email}


def as_user(client: AsyncClient, email: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers=headers_for(email),
    )


@pytest.fixture
async def guarded(client: AsyncClient) -> str:
    response = await client.post(
        "/api/projects/guarded",
        json={
            "meta": {"solution": "Guarded"},
            "evidence": SECRET,
            "archived": False,
            "access": {
                "owners": [TEST_EMAIL],
                "writers": [WRITER],
                "readers": [READER],
            },
        },
    )
    assert response.status_code == 201
    return "guarded"


def denials(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith("access.denied")]


async def test_a_stranger_reading_a_project_is_logged(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    async with as_user(client, STRANGER) as other:
        response = await other.get(f"/api/projects/{guarded}/versions")
    assert response.status_code == 404, "the existence-hiding 404 is unchanged"
    found = denials(caplog)
    assert len(found) == 1, [r.getMessage() for r in caplog.records]
    line = found[0].getMessage()
    assert STRANGER in line and guarded in line
    assert "need=read" in line and "held=none" in line
    assert "status=404" in line


async def test_a_reader_trying_to_write_is_logged(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    async with as_user(client, READER) as reader:
        response = await reader.patch(
            f"/api/projects/{guarded}", json={"meta": {"x": 1}}
        )
    assert response.status_code == 403
    line = denials(caplog)[0].getMessage()
    assert READER in line and guarded in line
    assert "need=write" in line and "held=reader" in line and "status=403" in line


async def test_a_writer_changing_the_access_list_is_logged(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    async with as_user(client, WRITER) as writer:
        response = await writer.patch(
            f"/api/projects/{guarded}",
            json={"access": {"owners": [WRITER], "writers": [], "readers": []}},
        )
    assert response.status_code == 403
    line = denials(caplog)[0].getMessage()
    assert WRITER in line and guarded in line
    assert "need=own" in line and "held=writer" in line


async def test_a_writer_archiving_is_logged(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    async with as_user(client, WRITER) as writer:
        response = await writer.patch(
            f"/api/projects/{guarded}", json={"archived": True}
        )
    assert response.status_code == 403
    assert "need=own" in denials(caplog)[0].getMessage()


async def test_a_writer_deleting_is_logged(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    async with as_user(client, WRITER) as writer:
        response = await writer.delete(f"/api/projects/{guarded}")
    assert response.status_code == 403
    line = denials(caplog)[0].getMessage()
    assert "need=own" in line and guarded in line


async def test_a_stranger_reading_the_log_is_logged(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    async with as_user(client, STRANGER) as other:
        response = await other.get(f"/api/projects/{guarded}/log")
    assert response.status_code == 404
    assert any(STRANGER in r.getMessage() for r in denials(caplog))


async def test_the_line_does_not_leak_the_document(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with as_user(client, STRANGER) as other:
        await other.get(f"/api/projects/{guarded}/versions")
        await other.patch(f"/api/projects/{guarded}", json={"evidence": "x"})
    assert denials(caplog), "something must have been logged to check"
    for record in caplog.records:
        assert SECRET not in record.getMessage()
        assert "Guarded" not in record.getMessage()


async def test_permitted_requests_log_no_denial(
    client: AsyncClient, guarded: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with as_user(client, READER) as reader:
        assert (
            await reader.get(f"/api/projects/{guarded}/versions")
        ).status_code == 200
    async with as_user(client, WRITER) as writer:
        assert (
            await writer.patch(f"/api/projects/{guarded}", json={"meta": {"x": 2}})
        ).status_code == 200
    assert (await client.delete(f"/api/projects/{guarded}")).status_code == 204
    assert not denials(caplog), [r.getMessage() for r in denials(caplog)]


async def test_a_project_that_does_not_exist_is_not_a_denial(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing was protected, so nothing was denied. Only a real record is."""
    caplog.set_level(logging.WARNING)
    async with as_user(client, STRANGER) as other:
        assert (await other.get("/api/projects/no-such/versions")).status_code == 404
    assert not denials(caplog)
