"""The documented repair for access lists stored with Google IAP's prefix (#35).

Run against a real PostgreSQL, and against the SQL **extracted from the page the
operator reads**, not a copy of it: a repair statement that has never run is a
guess, and one the docs have drifted from is worse.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import AsyncClient

from .conftest import TEST_EMAIL, requires_db

pytestmark = [requires_db, pytest.mark.db]

DOC = Path(__file__).resolve().parents[2] / "docs" / "self-hosting.md"
PREFIX = "accounts.google.com:"


def documented_sql() -> tuple[str, str]:
    """(the count query, the repair statement) from the self-hosting guide."""
    text = DOC.read_text(encoding="utf-8")
    section = text[text.index("If access lists were already stored with the prefix") :]
    block = re.search(r"```sql\n(.*?)```", section, re.S).group(1)
    count, repair = (part.strip() for part in re.split(r"\n(?=-- remove it)", block))
    return count, repair


async def store(client: AsyncClient, pid: str, access: dict) -> None:
    async with client.app.state.db.acquire() as conn:
        await conn.execute(
            "INSERT INTO projects (id, doc, created_by, updated_by) "
            "VALUES ($1, $2, 'x', 'x')",
            pid,
            {
                "meta": {"solution": pid},
                "evidence": "mentions accounts.google.com: here",
                "access": access,
            },
        )


async def visible(client: AsyncClient) -> set[str]:
    return {p["id"] for p in (await client.get("/api/projects")).json()}


async def test_the_documented_repair_makes_a_locked_out_project_visible(
    client: AsyncClient,
) -> None:
    count, repair = documented_sql()
    await store(
        client,
        "locked",
        {
            "owners": [PREFIX + TEST_EMAIL, PREFIX + "other@hospital.example"],
            "writers": [PREFIX + "w@hospital.example"],
            "readers": [PREFIX + "r@hospital.example"],
        },
    )
    await store(client, "fine", {"owners": [TEST_EMAIL], "writers": [], "readers": []})

    assert "locked" not in await visible(client), "locked out, as the issue describes"
    assert "fine" in await visible(client)

    async with client.app.state.db.acquire() as conn:
        assert await conn.fetchval(count) == 4

        await conn.execute(repair)

        assert await conn.fetchval(count) == 0, "no prefixed entries remain"
        row = await conn.fetchrow("SELECT doc FROM projects WHERE id = 'locked'")
        access = row["doc"]["access"]
        assert access["owners"] == [TEST_EMAIL, "other@hospital.example"]
        assert access["writers"] == ["w@hospital.example"]
        assert access["readers"] == ["r@hospital.example"]
        # Nothing but the access list is rewritten, including prose that happens
        # to contain the prefix text.
        assert row["doc"]["evidence"] == "mentions accounts.google.com: here"
        assert row["doc"]["meta"] == {"solution": "locked"}

    assert "locked" in await visible(client), "the owner can see it again"


async def test_the_repair_leaves_other_projects_and_runs_twice_safely(
    client: AsyncClient,
) -> None:
    _, repair = documented_sql()
    await store(
        client, "fine", {"owners": [TEST_EMAIL], "writers": ["w@x"], "readers": []}
    )
    await store(client, "open", {})  # unclaimed: no owners at all
    async with client.app.state.db.acquire() as conn:
        before = [
            r["doc"] for r in await conn.fetch("SELECT doc FROM projects ORDER BY id")
        ]
        await conn.execute(repair)
        await conn.execute(repair)
        after = [
            r["doc"] for r in await conn.fetch("SELECT doc FROM projects ORDER BY id")
        ]
    assert before == after
    assert await visible(client) >= {"fine", "open"}
