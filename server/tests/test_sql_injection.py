"""SQL is never built from text a person typed (#155).

Two things, both needed. A guard on the code: every call that runs SQL passes a constant
string, with values traveling as parameters, except the two places that run trusted
DDL (the migration files, and the role the API serves as), which are named here with the
reason. And a test on the behavior: hostile text in every place the API accepts text is
stored and returned as text, and the tables are still there afterward.

The guard needs no database. The behavior test needs a real PostgreSQL, because what it
shows is what the database did with the text.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, owner_connection, requires_db

APP = Path(__file__).resolve().parent.parent / "app"
SQL_CALLS = {
    "execute", "executemany", "fetch", "fetchrow", "fetchval", "prepare", "cursor",
    "copy_to_table", "copy_records_to_table",
}  # fmt: skip

# The only places that pass SQL that is not a constant string, and why that is safe.
TRUSTED_DDL = {
    ("db.py", "migrate"): (
        "runs the migration files in this repository, and takes an advisory lock whose "
        "id is a module constant"
    ),
    ("roles.py", "provision"): (
        "creates the role the API serves as: the name passes check_role_name, and the "
        "name and password are quoted by the server's format(%I, %L), never by Python"
    ),
}


def dynamic_sql(source: str, filename: str) -> list[str]:
    """SQL calls whose first argument is not a constant string, outside the allowlist."""
    tree = ast.parse(source)
    found = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for call in ast.walk(func):
            if not (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr in SQL_CALLS
                and call.args
            ):
                continue
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                continue
            if (filename, func.name) in TRUSTED_DDL:
                continue
            found.append(f"{filename}:{call.lineno} in {func.name}()")
    return sorted(set(found))


def test_every_sql_call_passes_a_constant_string() -> None:
    problems = []
    for path in sorted(APP.glob("*.py")):
        problems += dynamic_sql(path.read_text(encoding="utf-8"), path.name)
    assert not problems, "SQL built at run time: " + "; ".join(problems)


def test_the_guard_notices_each_way_text_reaches_sql() -> None:
    planted = {
        "an f-string": "async def f(c, x):\n    await c.fetch(f\"SELECT * FROM t WHERE a = '{x}'\")",
        "concatenation": 'async def f(c, x):\n    await c.execute("DELETE FROM t WHERE a = " + x)',
        "a format call": 'async def f(c, x):\n    await c.fetchrow("SELECT {}".format(x))',
        "a percent format": 'async def f(c, x):\n    await c.fetchval("SELECT %s" % x)',
        "a variable": "async def f(c, sql):\n    await c.execute(sql)",
    }
    for label, source in planted.items():
        assert dynamic_sql(source, "x.py"), label
    safe = 'async def f(c, x):\n    await c.fetch("SELECT * FROM t WHERE a = $1", x)'
    assert not dynamic_sql(safe, "x.py")
    # The allowlist is by file and function: the same code elsewhere is not excused.
    assert dynamic_sql(planted["a variable"], "routes.py")
    assert not dynamic_sql(planted["a variable"].replace("f(", "migrate("), "db.py")


def test_every_allowed_exception_still_exists_and_says_why() -> None:
    for (filename, func), why in TRUSTED_DDL.items():
        tree = ast.parse((APP / filename).read_text(encoding="utf-8"))
        names = {
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert func in names, (
            f"{filename}:{func} no longer exists; remove its exception"
        )
        assert len(why) > 40


# --- the behavior, against a real database ----------------------------------------

pytestmark_db = requires_db

HOSTILE = [
    "'; DROP TABLE projects; --",
    '" OR 1=1 --',
    "'); DELETE FROM project_log; --",
    "$$; DROP TABLE project_version; $$",
    "\\'; SELECT pg_sleep(5); --",
    "x' UNION SELECT doc FROM projects --",
    "\u0000 null byte",
    "%' OR '%'='",
]


def acting_as(client: AsyncClient, email: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers={"X-Forwarded-Email": email, "X-Forwarded-User": email},
    )


async def tables_intact() -> bool:
    async with owner_connection() as conn:
        found = {
            r["tablename"]
            for r in await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
    return {"projects", "project_log", "project_version", "access_event"} <= found


@requires_db
@pytest.mark.parametrize("text", HOSTILE)
async def test_hostile_text_is_stored_and_returned_as_text(
    client: AsyncClient, text: str
) -> None:
    text = text.replace("\u0000", "")  # a NUL has its own test, below
    pid = "inj-" + str(abs(hash(text)) % 10**6)
    created = await client.post(
        f"/api/projects/{pid}",
        json={
            "meta": {"solution": text, "org": text},
            "items": {"s1-1": {"status": "met", "evidence": text}},
            "access": {"owners": [TEST_EMAIL], "writers": [text], "readers": []},
        },
    )
    assert created.status_code == 201, created.text
    assert (
        await client.patch(f"/api/projects/{pid}", json={"meta": {"scope": text}})
    ).status_code == 200
    assert (
        await client.post(f"/api/projects/{pid}/log", json={"text": text})
    ).status_code == 201
    hold = await client.post(
        f"/api/projects/{pid}/hold", json={"action": "place", "reason": text}
    )
    assert hold.status_code == 200, hold.text

    got = (await client.get("/api/projects")).json()
    doc = next(p for p in got if p["id"] == pid)
    assert doc["meta"]["solution"] == text and doc["items"]["s1-1"]["evidence"] == text
    log = (await client.get(f"/api/projects/{pid}/log")).json()
    assert any(entry["text"] == text for entry in log)
    held = (await client.get(f"/api/projects/{pid}/hold")).json()
    assert held["history"][0]["reason"] == text.strip()  # a reason is trimmed
    assert await tables_intact()
    async with owner_connection() as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM projects WHERE id = $1", pid) == 1
        )


@requires_db
@pytest.mark.parametrize("text", HOSTILE[:5])
async def test_hostile_text_in_the_things_a_url_or_header_carries(
    client: AsyncClient, text: str
) -> None:
    # Query strings, a cursor and a list of ids: all refused or ignored, never run.
    assert (
        await client.get("/api/projects/p1/log", params={"before": text})
    ).status_code in (400, 404, 422)
    assert (
        await client.get("/api/projects/p1/log", params={"limit": text})
    ).status_code in (404, 422)
    assert (await client.get("/api/principals", params={"ids": text})).status_code in (
        200,
        422,
    )
    # An id outside the allowed characters never reaches the database.
    assert (await client.get("/api/projects/" + "x" + "%27%3B--/hold")).status_code in (
        404,
        422,
    )
    # Identity is only ever recorded as data: a hostile address in the proxy header.
    hostile = text.replace("\u0000", "")[:60]
    async with acting_as(client, hostile) as other:
        created = await other.post(
            "/api/projects/hdr1", json={"meta": {"solution": "S"}}
        )
        assert created.status_code in (201, 400, 401, 403, 409, 422)
    assert await tables_intact()


@requires_db
async def test_a_hostile_project_id_is_refused_before_it_reaches_the_database(
    client: AsyncClient,
) -> None:
    for pid in ["a b", "a;b", "a'b", 'a"b', "a$$b", "a/b", "../x", "a%00b"]:
        r = await client.post(f"/api/projects/{pid}", json={"meta": {}})
        assert r.status_code in (404, 405, 422), (pid, r.status_code)
    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT count(*) FROM projects") == 0
    assert json.dumps(HOSTILE)  # the payloads are plain data


@requires_db
async def test_a_nul_character_is_refused_cleanly_not_with_a_server_error(
    client: AsyncClient,
) -> None:
    """PostgreSQL text and jsonb cannot hold U+0000. Whatever the API does with one, it
    is not a 500: that would be a way for any writer to make requests fail noisily."""
    nul = "bad\u0000text"
    made = await client.post("/api/projects/nul1", json={"meta": {"solution": "S"}})
    assert made.status_code == 201
    for call in (
        client.post("/api/projects/nul2", json={"meta": {"solution": nul}}),
        client.patch("/api/projects/nul1", json={"meta": {"scope": nul}}),
        client.post("/api/projects/nul1/log", json={"text": nul}),
        client.post("/api/projects/nul1/hold", json={"action": "place", "reason": nul}),
    ):
        response = await call
        assert response.status_code == 422, (response.status_code, response.text[:120])
    # Nothing was half-written: the project is as it was.
    doc = next(
        p for p in (await client.get("/api/projects")).json() if p["id"] == "nul1"
    )
    assert "scope" not in doc["meta"] or doc["meta"]["scope"] == ""
    assert await tables_intact()
