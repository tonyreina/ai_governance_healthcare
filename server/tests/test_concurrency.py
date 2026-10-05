"""Two PATCHes at once must not lose one of them.

This is the test the design exists for. The app debounces edits and flushes
them 550 ms later, so two people editing different criteria on the same project
-- or one person on two tabs -- routinely produce overlapping PATCHes. A naive
read-modify-write loses whichever write read first:

    A reads {items: {s4-1: met}}          B reads {items: {s4-1: met}}
    A merges {items: {s4-2: met}}         B merges {items: {s4-3: met}}
    A writes {s4-1, s4-2}                 B writes {s4-1, s4-3}   <- s4-2 gone

``SELECT ... FOR UPDATE`` inside the transaction is what closes that window: B
blocks at the SELECT until A commits, then reads A's committed document.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from .conftest import requires_db

pytestmark = [requires_db, pytest.mark.db]

CONCURRENT = 12


async def test_concurrent_patches_to_different_fields_all_survive(
    client: AsyncClient, project: str
) -> None:
    responses = await asyncio.gather(
        *[
            client.patch(
                f"/api/projects/{project}",
                json={"items": {f"s9-{index}": {"status": "met"}}},
            )
            for index in range(CONCURRENT)
        ]
    )
    assert [r.status_code for r in responses] == [200] * CONCURRENT

    [stored] = (await client.get("/api/projects")).json()
    for index in range(CONCURRENT):
        assert stored["items"][f"s9-{index}"] == {"status": "met"}, (
            f"s9-{index} was lost: a concurrent PATCH overwrote it"
        )
    # The document the fixture started with is still there too.
    assert stored["items"]["s4-1"]["evidence"] == "validation report"
    assert stored["meta"]["solution"] == "Sepsis alert"


async def test_concurrent_patches_to_sibling_keys_of_one_object_all_survive(
    client: AsyncClient, project: str
) -> None:
    """The harder case: every writer touches the *same* nested object."""
    await asyncio.gather(
        *[
            client.patch(
                f"/api/projects/{project}",
                json={"items": {"s4-2": {f"field{index}": index}}},
            )
            for index in range(CONCURRENT)
        ]
    )
    [stored] = (await client.get("/api/projects")).json()
    item = stored["items"]["s4-2"]
    for index in range(CONCURRENT):
        assert item[f"field{index}"] == index
    assert item["status"] == "partial"
    assert item["owner"] == "A. Reviewer"


async def test_concurrent_patches_to_one_field_leave_one_winner(
    client: AsyncClient, project: str
) -> None:
    """Last writer wins, and the result is one of the values actually sent.

    Not a torn value, and not a value nobody wrote.
    """
    await asyncio.gather(
        *[
            client.patch(
                f"/api/projects/{project}", json={"meta": {"org": f"Org {index}"}}
            )
            for index in range(CONCURRENT)
        ]
    )
    [stored] = (await client.get("/api/projects")).json()
    assert stored["meta"]["org"] in {f"Org {index}" for index in range(CONCURRENT)}


async def test_every_patch_bumps_the_revision_exactly_once(
    client: AsyncClient, project: str
) -> None:
    """If two PATCHes had interleaved, rev would be short.

    rev is maintained by ``rev = rev + 1`` inside the same locked transaction,
    so it counts committed merges. CONCURRENT merges on a row created at rev 1
    must leave it at CONCURRENT + 1.
    """
    await asyncio.gather(
        *[
            client.patch(f"/api/projects/{project}", json={"items": {f"s8-{i}": {}}})
            for i in range(CONCURRENT)
        ]
    )
    async with client.app.state.db.acquire() as conn:
        rev = await conn.fetchval("SELECT rev FROM projects WHERE id = $1", project)
    assert rev == CONCURRENT + 1


async def test_concurrent_log_appends_all_land(
    client: AsyncClient, project: str
) -> None:
    """Appends take no lock and must not drop entries."""
    responses = await asyncio.gather(
        *[
            client.post(f"/api/projects/{project}/log", json={"text": f"entry {i}"})
            for i in range(CONCURRENT)
        ]
    )
    assert [r.status_code for r in responses] == [201] * CONCURRENT
    entries = (await client.get(f"/api/projects/{project}/log")).json()
    assert {e["text"] for e in entries} == {f"entry {i}" for i in range(CONCURRENT)}


async def test_a_patch_racing_a_delete_does_not_resurrect_the_project(
    client: AsyncClient, project: str
) -> None:
    """One of the two wins; neither leaves a half-deleted row behind."""
    delete, patch = await asyncio.gather(
        client.delete(f"/api/projects/{project}"),
        client.patch(f"/api/projects/{project}", json={"meta": {"org": "late"}}),
    )
    assert delete.status_code in (204, 404)
    assert patch.status_code in (200, 404)
    if delete.status_code == 204:
        assert (await client.get("/api/projects")).json() == []
