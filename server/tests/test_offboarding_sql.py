"""The offboarding SQL in docs/deploy.md must run and find the right projects (#42).

An operator copies it from the page the night before an account is disabled. A
statement that has never run, or that has drifted from the page, is a guess. So the
SQL is extracted from the page and executed against a real PostgreSQL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import AsyncClient

from .conftest import owner_connection, requires_db

pytestmark = [requires_db, pytest.mark.db]

DOC = Path(__file__).resolve().parents[2] / "docs" / "deploy.md"
LEAVER = "person@hospital.org"  # the placeholder the page uses


def documented_sql() -> tuple[str, str]:
    text = DOC.read_text(encoding="utf-8")
    section = text[text.index("### Offboarding, and emergency access") :]
    block = re.search(r"```sql\n(.*?)```", section, re.S).group(1)
    sole, every = (part.strip().rstrip(";") for part in re.split(r"\n\n(?=--)", block))
    return sole, every


async def store(pid: str, access) -> None:
    async with owner_connection() as conn:
        await conn.execute(
            "INSERT INTO projects (id, doc, created_by, updated_by) "
            "VALUES ($1, $2::jsonb, 'x', 'x')",
            pid,
            __import__("json").dumps({"meta": {"solution": pid}, "access": access}),
        )


async def test_the_sole_owner_query_finds_exactly_that_persons_projects(
    client: AsyncClient,
) -> None:
    sole, _ = documented_sql()
    await store("mine", {"owners": [LEAVER], "writers": [], "readers": []})
    await store("shared", {"owners": [LEAVER, "other@x"], "writers": [], "readers": []})
    await store("theirs", {"owners": ["other@x"], "writers": [LEAVER], "readers": []})
    await store("unclaimed", {})
    await store("odd-shape", {"owners": "not-a-list"})  # must not crash the query
    await store("no-access", None)
    async with owner_connection() as conn:
        rows = await conn.fetch(sole)
    assert [r["id"] for r in rows] == ["mine"]
    assert rows[0]["solution"] == "mine"


async def test_the_single_owner_report_lists_every_such_project(
    client: AsyncClient,
) -> None:
    _, every = documented_sql()
    await store("a", {"owners": ["z@x"], "writers": [], "readers": []})
    await store("b", {"owners": ["a@x"], "writers": [], "readers": []})
    await store("two", {"owners": ["a@x", "b@x"], "writers": [], "readers": []})
    await store("open", {})
    async with owner_connection() as conn:
        rows = await conn.fetch(every)
    assert [(r["id"], r["only_owner"]) for r in rows] == [("b", "a@x"), ("a", "z@x")]
