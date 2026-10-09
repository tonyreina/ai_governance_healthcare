"""Evidence references survive concurrent edits (R-61).

References are stored as an object keyed by reference id, not as an array, so
two people who each add one at the same moment both keep theirs: an array would
be replaced wholesale by whichever write landed second (see ``merge.py``). A
removal is a ``null`` at one key and must touch nothing else.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from .conftest import requires_db

pytestmark = [requires_db, pytest.mark.db]

REF = {"title": "Validation report", "url": "https://example.org/v", "date": ""}
SHA = "a" * 64


def ref(n: int) -> dict:
    file = {"name": f"f{n}", "size": n, "sha256": SHA}
    return {**REF, "title": f"reference {n}", "file": file}


async def test_concurrent_adds_to_one_item_keep_every_reference(
    client: AsyncClient, project: str
) -> None:
    count = 12
    await asyncio.gather(
        *[
            client.patch(
                f"/api/projects/{project}",
                json={"items": {"s4-1": {"refs": {f"rtest{n:03d}x": ref(n)}}}},
            )
            for n in range(count)
        ]
    )
    [stored] = (await client.get("/api/projects")).json()
    refs = stored["items"]["s4-1"]["refs"]
    assert sorted(refs) == [f"rtest{n:03d}x" for n in range(count)]
    assert refs["rtest005x"]["file"]["sha256"] == SHA
    assert stored["items"]["s4-1"]["evidence"] == "validation report"


async def test_removing_one_reference_leaves_the_others(
    client: AsyncClient, project: str
) -> None:
    for n in range(3):
        await client.patch(
            f"/api/projects/{project}",
            json={"items": {"s4-2": {"refs": {f"rkeep{n}xyz": ref(n)}}}},
        )
    await client.patch(
        f"/api/projects/{project}",
        json={"items": {"s4-2": {"refs": {"rkeep1xyz": None}}}},
    )
    [stored] = (await client.get("/api/projects")).json()
    refs = stored["items"]["s4-2"]["refs"]
    assert refs["rkeep1xyz"] is None
    assert refs["rkeep0xyz"]["title"] == "reference 0"
    assert refs["rkeep2xyz"]["title"] == "reference 2"
    assert stored["items"]["s4-2"]["owner"] == "A. Reviewer"
