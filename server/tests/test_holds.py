"""Litigation holds through the API (#57, R-56, D-62).

A hold stops disposal of a project until it is lifted. The owner chose a hold per
project, placed and lifted with a reason by an owner of the project, append-only.
The database side (what a hold stops) is server/tests/test_retention.py; this is
who may place one, what is recorded, and what is refused.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, owner_connection, requires_db
from .test_security_events import Capture, make_settings

pytestmark = requires_db

PID = "held1"
ACCESS = {"owners": [TEST_EMAIL], "writers": ["w@x.org"], "readers": ["r@x.org"]}


def acting_as(client: AsyncClient, email: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers={"X-Forwarded-Email": email, "X-Forwarded-User": email},
    )


async def make(client: AsyncClient) -> None:
    r = await client.post(
        f"/api/projects/{PID}", json={"meta": {"solution": "S"}, "access": ACCESS}
    )
    assert r.status_code == 201, r.text


async def hold(client: AsyncClient, action: str, reason: str = "Smith v. Hospital"):
    return await client.post(
        f"/api/projects/{PID}/hold", json={"action": action, "reason": reason}
    )


async def test_an_owner_places_and_lifts_a_hold(client: AsyncClient) -> None:
    await make(client)
    r = await client.get(f"/api/projects/{PID}/hold")
    assert r.status_code == 200 and r.json() == {"held": False, "history": []}

    r = await hold(client, "place")
    assert r.status_code == 200, r.text
    assert r.json()["held"] is True
    placed = r.json()["history"][0]
    assert placed["action"] == "place" and placed["by"] == TEST_EMAIL
    assert placed["reason"] == "Smith v. Hospital"

    r = await hold(client, "lift", "Case settled")
    assert r.json()["held"] is False
    assert [h["action"] for h in r.json()["history"]] == ["lift", "place"]
    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT retention_held($1)", PID) is False
        assert await conn.fetchval("SELECT count(*) FROM retention_hold") == 2


async def test_only_an_owner_may_see_or_change_a_hold(client: AsyncClient) -> None:
    await make(client)
    for email, status in [("w@x.org", 403), ("r@x.org", 403), ("nobody@x.org", 404)]:
        async with acting_as(client, email) as other:
            assert (await other.get(f"/api/projects/{PID}/hold")).status_code == status
            assert (await hold(other, "place")).status_code == status
    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT count(*) FROM retention_hold") == 0


async def test_placing_twice_or_lifting_nothing_is_a_conflict(
    client: AsyncClient,
) -> None:
    await make(client)
    assert (await hold(client, "lift")).status_code == 409
    assert (await hold(client, "place")).status_code == 200
    assert (await hold(client, "place")).status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"action": "place", "reason": "   "},
        {"action": "place"},
        {"action": "suspend", "reason": "r"},
        {"action": "place", "reason": "x" * 1001},
    ],
)
async def test_a_hold_needs_a_known_action_and_a_reason(
    client: AsyncClient, body: dict
) -> None:
    await make(client)
    r = await client.post(f"/api/projects/{PID}/hold", json=body)
    assert r.status_code == 422, r.text


async def test_the_project_log_says_a_hold_changed_but_not_why(
    client: AsyncClient,
) -> None:
    await make(client)
    await hold(client, "place", "Deposition of Dr. A")
    entries = (await client.get(f"/api/projects/{PID}/log")).json()
    text = " ".join(e["text"] for e in entries)
    assert "Litigation hold placed" in text
    assert "Deposition" not in text  # the reason is legal detail, kept with the hold


async def test_a_deleted_projects_history_can_be_held(client: AsyncClient) -> None:
    await make(client)
    assert (await client.delete(f"/api/projects/{PID}")).status_code == 204
    r = await hold(client, "place")
    assert r.status_code == 200 and r.json()["held"] is True


async def test_placing_and_lifting_are_security_events() -> None:
    async with Capture(make_settings()) as cap:
        from .conftest import TEST_HEADERS, reset_database

        await reset_database()
        async with cap.client(**TEST_HEADERS) as http:
            await http.post(f"/api/projects/{PID}", json={"meta": {"solution": "S"}})
            await http.post(
                f"/api/projects/{PID}/hold",
                json={"action": "place", "reason": "Secret matter"},
            )
            await http.post(
                f"/api/projects/{PID}/hold", json={"action": "lift", "reason": "Done"}
            )
        for name in ("hold.placed", "hold.lifted"):
            found = cap.events(name)
            assert len(found) == 1, name
            assert found[0]["actor"] == TEST_EMAIL and found[0]["project"] == PID
        assert "Secret matter" not in cap.buffer.getvalue()
