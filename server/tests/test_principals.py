"""Turning a user id into a person (#39).

The API learned who you are from the proxy on every request and kept only the id.
Every identity but the viewer's own therefore rendered as the literal word
"someone": in the access list, in the sign-off line, in the changelog, and in the
exports. A project owner doing the periodic access review the HIPAA workforce
rules assume saw "someone, someone, someone", and the printed record a committee
files said "Recorded by someone". The ids themselves (IAP numeric subject ids,
ALB `sub`) match nothing in a staff directory.

The fix reuses what the proxy already asserts: record name and email against the
id as people sign in, and resolve a batch on request. That creates a staff
directory as a side effect, so the lookup answers only for people the caller can
already see on a project they can read, not for anyone who asks.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, TEST_HEADERS, owner_connection, requires_db

pytestmark = [requires_db, pytest.mark.db]

ANN = "ann@hospital.example"
BOB = "bob@hospital.example"
CAT = "cat@hospital.example"


def as_user(client: AsyncClient, ident: str, name: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers={
            **TEST_HEADERS,
            "X-Forwarded-Email": ident,
            "X-Forwarded-User": name,
        },
    )


async def sign_in(client: AsyncClient, ident: str, name: str) -> None:
    async with as_user(client, ident, name) as http:
        assert (await http.get("/api/me")).status_code == 200


async def lookup(http: AsyncClient, *ids: str):
    return await http.get("/api/principals", params={"ids": ",".join(ids)})


async def test_signing_in_records_who_you_are(client: AsyncClient) -> None:
    await sign_in(client, ANN, "Ann Example")
    async with owner_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM principals WHERE id = $1", ANN)
    assert row["name"] == "Ann Example"
    assert row["email"] == ANN
    assert row["first_seen"] is not None and row["last_seen"] is not None


async def test_a_changed_name_is_updated_not_duplicated(client: AsyncClient) -> None:
    await sign_in(client, ANN, "Ann Example")
    await sign_in(client, ANN, "Ann Example-Smith")
    async with owner_connection() as conn:
        rows = await conn.fetch("SELECT name FROM principals WHERE id = $1", ANN)
    assert [r["name"] for r in rows] == ["Ann Example-Smith"]


async def test_the_lookup_resolves_people_on_a_project_you_can_read(
    client: AsyncClient,
) -> None:
    await sign_in(client, ANN, "Ann Example")
    await sign_in(client, BOB, "Bob Writer")
    created = await client.post(
        "/api/projects/team",
        json={"access": {"owners": [TEST_EMAIL], "writers": [BOB], "readers": [ANN]}},
    )
    assert created.status_code == 201
    async with as_user(client, ANN, "Ann Example") as ann:
        response = await lookup(ann, TEST_EMAIL, BOB, ANN)
    assert response.status_code == 200
    by_id = {p["id"]: p for p in response.json()}
    assert by_id[BOB]["name"] == "Bob Writer" and by_id[BOB]["email"] == BOB
    assert by_id[ANN]["name"] == "Ann Example"
    # The project's owner is on a project Ann can read, so Ann may see who they are.
    assert TEST_EMAIL in by_id


async def test_it_is_not_a_directory_anyone_can_enumerate(
    client: AsyncClient,
) -> None:
    """Cat shares no readable project with Bob, so Cat cannot learn who Bob is."""
    await sign_in(client, BOB, "Bob Writer")
    await sign_in(client, CAT, "Cat Stranger")
    await client.post(
        "/api/projects/private",
        json={"access": {"owners": [TEST_EMAIL], "writers": [BOB], "readers": []}},
    )
    async with as_user(client, CAT, "Cat Stranger") as cat:
        response = await lookup(cat, BOB, TEST_EMAIL, "someone-who-never-signed-in")
    assert response.status_code == 200
    assert response.json() == [], "Cat can read nothing, so can resolve nobody"
    # Cat can always resolve themself.
    async with as_user(client, CAT, "Cat Stranger") as cat:
        own = await lookup(cat, CAT)
    assert [p["id"] for p in own.json()] == [CAT]


async def test_people_in_sign_offs_and_the_log_are_resolvable(
    client: AsyncClient,
) -> None:
    await sign_in(client, BOB, "Bob Writer")
    await client.post(
        "/api/projects/signed",
        json={"access": {"owners": [TEST_EMAIL], "writers": [], "readers": [ANN]}},
    )
    await sign_in(client, ANN, "Ann Example")
    # Bob is on no access list. He appears only as the author of a log entry on a
    # project Ann can read, which is enough for Ann to learn who he is.
    async with owner_connection() as conn:
        await conn.execute(
            "INSERT INTO project_log (project_id, by_id, entry) VALUES ($1, $2, $3)",
            "signed",
            BOB,
            '{"at":"x","by":"' + BOB + '","text":"Checkpoint decided"}',
        )
    async with as_user(client, ANN, "Ann Example") as ann:
        response = await lookup(ann, BOB)
    assert [p["id"] for p in response.json()] == [BOB]


async def test_unknown_ids_are_omitted_not_errors(client: AsyncClient) -> None:
    response = await lookup(client, "nobody-ever", TEST_EMAIL)
    assert response.status_code == 200
    assert {p["id"] for p in response.json()} <= {TEST_EMAIL}


async def test_the_batch_is_bounded(client: AsyncClient) -> None:
    many = [f"user{i}@hospital.example" for i in range(101)]
    assert (await lookup(client, *many)).status_code == 422
    assert (await client.get("/api/principals")).status_code == 422
    assert (await client.get("/api/principals", params={"ids": ""})).status_code == 422
    long_id = "x" * 300
    assert (await lookup(client, long_id)).status_code == 422


async def test_recording_is_throttled(client: AsyncClient) -> None:
    """A write per request would be write amplification on every read."""
    await sign_in(client, ANN, "Ann Example")
    async with owner_connection() as conn:
        first = await conn.fetchval(
            "SELECT last_seen FROM principals WHERE id = $1", ANN
        )
    for _ in range(5):
        await sign_in(client, ANN, "Ann Example")
    async with owner_connection() as conn:
        later = await conn.fetchval(
            "SELECT last_seen FROM principals WHERE id = $1", ANN
        )
    assert later == first, "five identical requests within the window wrote nothing"


async def test_the_dev_and_anonymous_identities_are_not_recorded(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM principals WHERE id IN ('anonymous', '')"
        )
    assert count == 0


async def test_a_failure_to_record_does_not_fail_the_request(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Knowing someone's name is a convenience; the request is the point."""

    async def boom(*args, **kwargs):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(client.app.state.principals, "_write", boom)
    async with as_user(client, "new-person@hospital.example", "New Person") as http:
        assert (await http.get("/api/me")).status_code == 200
