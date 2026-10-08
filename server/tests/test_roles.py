"""The serving role must not be able to undo the append-only guarantees (#48).

The history's evidentiary value rests on triggers: a log that refuses UPDATE, a
version table that refuses DELETE, a tombstone that refuses everything. A table's
owner can switch any of them off in one statement, and the API used to connect as
the owner (a superuser, in the compose stack). So these are the tests that matter:
not "the role can do its job" (the whole suite does that, see TEST_APP_ROLE), but
"the role is REFUSED" each statement that would remove a guarantee.

Real PostgreSQL throughout: what is under test is what the database permits.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg
import pytest
from app.roles import GRANTS, NO_ACCESS, grant_statements, provision
from httpx import AsyncClient

from .conftest import DB_URL, requires_db

pytestmark = [requires_db, pytest.mark.db]

ROLE = "chai_app_test"
PASSWORD = "p'a\"ss;w--rd/with?awkward#chars=0123456789"
SERVER = Path(__file__).resolve().parents[1]


def dsn_as(role: str, password: str) -> str:
    parts = urlsplit(DB_URL)
    host = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit(
        (
            parts.scheme,
            f"{quote(role, safe='')}:{quote(password, safe='')}@{host}",
            parts.path,
            parts.query,
            parts.fragment,
        )
    )


@pytest.fixture
async def owner(client: AsyncClient):
    """An owner connection, after the schema exists (the client fixture migrates)."""
    conn = await asyncpg.connect(DB_URL)
    await conn.execute(f"DROP OWNED BY {ROLE}") if await conn.fetchval(
        "SELECT 1 FROM pg_roles WHERE rolname = $1", ROLE
    ) else None
    await conn.execute(f"DROP ROLE IF EXISTS {ROLE}")
    try:
        yield conn
    finally:
        if await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", ROLE):
            await conn.execute(f"DROP OWNED BY {ROLE}")
            await conn.execute(f"DROP ROLE {ROLE}")
        await conn.close()


@pytest.fixture
async def app_conn(owner):
    await provision(owner, ROLE, PASSWORD)
    conn = await asyncpg.connect(dsn_as(ROLE, PASSWORD))
    try:
        yield conn
    finally:
        await conn.close()


async def test_the_role_is_a_plain_login_role(owner, app_conn) -> None:
    row = await owner.fetchrow("SELECT * FROM pg_roles WHERE rolname = $1", ROLE)
    assert row["rolcanlogin"]
    for dangerous in (
        "rolsuper",
        "rolcreatedb",
        "rolcreaterole",
        "rolreplication",
        "rolbypassrls",
    ):
        assert not row[dangerous], dangerous
    assert await app_conn.fetchval("SELECT current_user") == ROLE


async def test_it_owns_nothing(owner, app_conn) -> None:
    owned = await owner.fetch(
        "SELECT tablename FROM pg_tables WHERE tableowner = $1", ROLE
    )
    assert owned == []


async def test_its_table_privileges_are_exactly_the_documented_ones(
    owner, app_conn
) -> None:
    rows = await owner.fetch(
        "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = $1 AND table_schema = 'public'",
        ROLE,
    )
    granted: dict[str, set[str]] = {}
    for r in rows:
        granted.setdefault(r["table_name"], set()).add(r["privilege_type"])
    assert granted == {t: set(p) for t, p in GRANTS.items()}


async def test_every_table_has_a_decided_grant(owner) -> None:
    """Adding a table without deciding what the API may do to it must fail here."""
    tables = {
        r["tablename"]
        for r in await owner.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    }
    undecided = tables - set(GRANTS) - set(NO_ACCESS)
    assert not undecided, (
        f"{sorted(undecided)} exist but are in neither GRANTS nor NO_ACCESS in "
        "app/roles.py: decide what the API may do to them"
    )


async def test_it_can_do_its_job(owner, app_conn) -> None:
    await app_conn.execute(
        "INSERT INTO projects (id, doc, created_by, updated_by) "
        "VALUES ('r1', '{}', 'x', 'x')"
    )
    await app_conn.execute(
        "INSERT INTO project_log (project_id, by_id, entry) VALUES ('r1', 'x', '{}')"
    )
    await app_conn.execute("UPDATE projects SET doc = '{\"a\":1}' WHERE id = 'r1'")
    assert await app_conn.fetchval("SELECT count(*) FROM project_log") == 1
    # Deleting the project cascades to its log, with no DELETE grant on the log:
    # referential actions run with the table owner's rights.
    await app_conn.execute("DELETE FROM projects WHERE id = 'r1'")
    assert await app_conn.fetchval("SELECT count(*) FROM project_log") == 0


REFUSED = [
    # Switching off or removing the guarantees themselves.
    "ALTER TABLE project_log DISABLE TRIGGER ALL",
    "ALTER TABLE project_version DISABLE TRIGGER ALL",
    "ALTER TABLE project_deletion DISABLE TRIGGER ALL",
    "ALTER TABLE project_log DISABLE TRIGGER project_log_no_update",
    "DROP TRIGGER project_log_no_update ON project_log",
    "ALTER TABLE project_log ENABLE REPLICA TRIGGER project_log_no_update",
    # Wiping history.
    "TRUNCATE project_log",
    "TRUNCATE project_version",
    "TRUNCATE project_deletion",
    "TRUNCATE projects CASCADE",
    # Rewriting the schema.
    "ALTER TABLE project_log ADD COLUMN x int",
    "ALTER TABLE project_version DROP COLUMN doc",
    "DROP TABLE project_version",
    "CREATE TABLE sneaky (x int)",
    "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS 'SELECT 1'",
    "CREATE OR REPLACE FUNCTION project_log_is_append_only() RETURNS trigger "
    "LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'",
    # Rows the grants withhold, independent of the triggers.
    "DELETE FROM project_version",
    "DELETE FROM project_deletion",
    "UPDATE project_deletion SET deleted_by = 'x'",
    "DELETE FROM project_log",
    "SELECT * FROM schema_migrations",
    "INSERT INTO schema_migrations (version) VALUES ('x')",
    # Making someone, or becoming a bigger one. (The statements that name the
    # owner role are built in the test, because its name differs by environment.)
    "CREATE ROLE intruder LOGIN SUPERUSER",
    "ALTER ROLE chai_app_test SUPERUSER",
    "ALTER TABLE project_log OWNER TO chai_app_test",
]


async def test_it_is_refused_every_statement_that_removes_a_guarantee(
    owner, app_conn
) -> None:
    """One role, every statement: report them ALL, not just the first."""
    wrongly_allowed: list[str] = []
    wrong_reason: list[str] = []
    for statement in REFUSED:
        try:
            await app_conn.execute(statement)
        except asyncpg.PostgresError as exc:
            # Refused for a privilege, not because the test has a typo in it.
            if isinstance(
                exc,
                (
                    asyncpg.PostgresSyntaxError,
                    asyncpg.UndefinedColumnError,
                    asyncpg.UndefinedObjectError,
                ),
            ):
                wrong_reason.append(f"{statement}: {type(exc).__name__}: {exc}")
        else:
            wrongly_allowed.append(statement)
    assert not wrongly_allowed, f"the serving role was ALLOWED: {wrongly_allowed}"
    assert not wrong_reason, f"refused, but not for a privilege: {wrong_reason}"


async def test_it_cannot_become_or_reconfigure_the_owner(owner, app_conn) -> None:
    owner_name = await owner.fetchval("SELECT current_user")
    for statement in (
        f'SET ROLE "{owner_name}"',
        f"ALTER ROLE \"{owner_name}\" PASSWORD 'x'",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute(statement)


async def test_granting_itself_more_changes_nothing(owner, app_conn) -> None:
    """GRANT of what it holds is only a warning in PostgreSQL, so assert the effect:
    after trying, it still cannot truncate or delete history."""
    for statement in (
        "GRANT ALL ON project_log TO chai_app_test",
        "GRANT ALL ON project_version TO chai_app_test",
        "GRANT TRUNCATE ON project_log TO chai_app_test",
    ):
        with contextlib.suppress(asyncpg.PostgresError):  # refused outright is fine
            await app_conn.execute(statement)
    for statement in ("TRUNCATE project_log", "DELETE FROM project_version"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await app_conn.execute(statement)


async def test_the_triggers_still_hold_for_what_it_may_touch(owner, app_conn) -> None:
    """It may UPDATE project_log, and the trigger still refuses a rewrite."""
    await app_conn.execute(
        "INSERT INTO projects (id, doc, created_by, updated_by) "
        "VALUES ('t1', '{}', 'x', 'x')"
    )
    await app_conn.execute(
        "INSERT INTO project_log (project_id, by_id, entry) "
        "VALUES ('t1', 'x', '{\"text\":\"original\"}')"
    )
    with pytest.raises(asyncpg.PostgresError, match=r"append-only|redact|permitted"):
        await app_conn.execute(
            'UPDATE project_log SET entry = \'{"text":"rewritten"}\' '
            "WHERE project_id = 't1'"
        )
    await app_conn.execute("DELETE FROM projects WHERE id = 't1'")


async def test_provisioning_twice_is_safe_and_rotates_the_password(owner) -> None:
    await provision(owner, ROLE, "first-password-0123456789")
    first = await asyncpg.connect(dsn_as(ROLE, "first-password-0123456789"))
    await first.close()

    await provision(owner, ROLE, "second-password-0123456789")
    second = await asyncpg.connect(dsn_as(ROLE, "second-password-0123456789"))
    await second.close()
    with pytest.raises(asyncpg.InvalidPasswordError):
        await asyncpg.connect(dsn_as(ROLE, "first-password-0123456789"))


async def test_provisioning_restores_a_privilege_someone_widened(owner) -> None:
    """A hand-edited grant does not survive a deploy."""
    await provision(owner, ROLE, PASSWORD)
    await owner.execute(f"GRANT DELETE, TRUNCATE ON project_version TO {ROLE}")
    await provision(owner, ROLE, PASSWORD)
    rows = await owner.fetch(
        "SELECT privilege_type FROM information_schema.role_table_grants "
        "WHERE grantee = $1 AND table_name = 'project_version'",
        ROLE,
    )
    assert {r["privilege_type"] for r in rows} == set(GRANTS["project_version"])


async def test_a_hostile_password_is_only_ever_a_password(owner) -> None:
    hostile = "x'; DROP TABLE projects; --"
    await provision(owner, ROLE, hostile)
    conn = await asyncpg.connect(dsn_as(ROLE, hostile))
    await conn.close()
    assert await owner.fetchval(
        "SELECT count(*) FROM pg_tables WHERE tablename = 'projects'"
    )


@pytest.mark.parametrize(
    "name", ["", "Chai", "chai app", "chai;drop", "1chai", "a" * 64, 'chai"']
)
async def test_a_role_name_that_cannot_be_put_in_sql_is_refused(owner, name) -> None:
    with pytest.raises(ValueError):
        await provision(owner, name, "pw-0123456789abcdef")
    with pytest.raises(ValueError):
        grant_statements(name)


def run_migrate(*args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.migrate", *args],
        capture_output=True,
        text=True,
        cwd=SERVER,
        env={
            **{
                k: v
                for k, v in os.environ.items()
                if not k.startswith(("POSTGRES_", "DATABASE_", "APP_POSTGRES"))
            },
            **env,
        },
    )


async def test_the_migrate_job_provisions_the_role(owner) -> None:
    done = run_migrate(
        DATABASE_URL=DB_URL, APP_POSTGRES_USER=ROLE, APP_POSTGRES_PASSWORD=PASSWORD
    )
    assert done.returncode == 0, done.stdout + done.stderr
    conn = await asyncpg.connect(dsn_as(ROLE, PASSWORD))
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("TRUNCATE project_log")
    finally:
        await conn.close()
    # Idempotent: a second run, as on every deploy.
    again = run_migrate(
        DATABASE_URL=DB_URL, APP_POSTGRES_USER=ROLE, APP_POSTGRES_PASSWORD=PASSWORD
    )
    assert again.returncode == 0, again.stdout + again.stderr


async def test_the_migrate_job_without_a_password_says_what_that_means(owner) -> None:
    done = run_migrate(DATABASE_URL=DB_URL, APP_POSTGRES_USER=ROLE)
    assert done.returncode == 0
    assert "will serve as the table owner" in done.stderr
    assert (
        await owner.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", ROLE) is None
    )


def test_the_migrate_job_fails_loudly_with_no_database() -> None:
    assert run_migrate().returncode == 2
    unreachable = run_migrate(
        DATABASE_URL="postgresql://nobody:x@127.0.0.1:1/none",
        MIGRATE_CONNECT_RETRIES="1",
    )
    assert unreachable.returncode != 0
    assert "could not connect" in unreachable.stderr


def test_print_grants_matches_what_provisioning_runs() -> None:
    done = run_migrate("--print-grants", APP_POSTGRES_USER=ROLE)
    assert done.returncode == 0
    assert done.stdout.strip().splitlines() == [s + ";" for s in grant_statements(ROLE)]
