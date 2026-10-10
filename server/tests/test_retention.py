"""Disposal at the end of the retention period, and litigation holds (#57).

R-54 set the periods and the owner granted the exception to R-10 that applying
them needs. What is tested here is the database's behavior, so it runs against a
real PostgreSQL: which records ``retention_due()`` says are past their period,
what ``dispose_due()`` destroys and what it leaves (a tombstone, R-12), that a
hold stops it, and that the read trail's trigger still refuses any DELETE the
policy does not allow, even from the table's owner.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import subprocess
from collections.abc import AsyncIterator, Callable
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from app.retention import SYSTEM_ACTOR, HoldAction
from httpx import AsyncClient

from . import manifests
from .conftest import APP_ROLE_URL, DB_URL, owner_connection, requires_db

pytestmark = requires_db

MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "008_retention.sql"
).read_text(encoding="utf-8")


async def make(client: AsyncClient, pid: str, gates: dict | None = None) -> None:
    response = await client.post(
        f"/api/projects/{pid}",
        json={"meta": {"solution": pid}, "gates": gates or {}},
    )
    assert response.status_code == 201, response.text


async def age(pid: str, years: float) -> None:
    """Make the live record's last change `years` ago."""
    async with owner_connection() as conn:
        await conn.execute(
            "UPDATE projects SET updated_at = now() - make_interval(days => $2)"
            " WHERE id = $1",
            pid,
            int(years * 365.25),
        )


def years_ago(years: float) -> str:
    return f"(now() - make_interval(days => {int(years * 365.25)}))::date"


async def gate_dated(years: float) -> str:
    async with owner_connection() as conn:
        return str(await conn.fetchval(f"SELECT {years_ago(years)}"))


async def due() -> dict[str, asyncpg.Record]:
    async with owner_connection() as conn:
        rows = await conn.fetch("SELECT * FROM retention_due()")
    return {r["project_id"]: r for r in rows}


async def dispose() -> asyncpg.Record:
    async with owner_connection() as conn:
        return await conn.fetchrow("SELECT * FROM dispose_due('ops@hospital.example')")


async def hold(pid: str, action: HoldAction, reason: str = "Smith v. Hospital") -> None:
    async with owner_connection() as conn:
        await conn.execute(
            "INSERT INTO retention_hold (project_id, by_id, action, reason)"
            " VALUES ($1, 'counsel@hospital.example', $2, $3)",
            pid,
            action,
            reason,
        )


# --- what is due ------------------------------------------------------------


async def test_a_project_still_in_use_is_never_due(client: AsyncClient) -> None:
    await make(client, "inuse", {"D": {"decision": "Continue", "date": "2015-01-01"}})
    await age("inuse", 10)
    assert "inuse" not in await due()


async def test_retired_and_past_the_period_is_due(client: AsyncClient) -> None:
    date = await gate_dated(7)
    await make(client, "old", {"D": {"decision": "Retire", "date": date}})
    await age("old", 7)
    found = await due()
    assert found["old"]["kind"] == "retired"
    assert not found["old"]["held"]


async def test_stopped_at_an_early_checkpoint_counts_as_retired(
    client: AsyncClient,
) -> None:
    date = await gate_dated(7)
    await make(client, "stopped", {"B": {"decision": "Stop", "date": date}})
    await age("stopped", 7)
    assert (await due())["stopped"]["kind"] == "retired"


async def test_retired_within_the_period_is_not_due(client: AsyncClient) -> None:
    date = await gate_dated(5)
    await make(client, "recent", {"D": {"decision": "Retire", "date": date}})
    await age("recent", 5)
    assert "recent" not in await due()


async def test_a_later_edit_restarts_the_clock(client: AsyncClient) -> None:
    date = await gate_dated(7)
    await make(client, "edited", {"D": {"decision": "Retire", "date": date}})
    await age("edited", 1)  # retired seven years ago, but changed last year
    assert "edited" not in await due()


async def test_a_retirement_dated_in_the_future_is_not_due(
    client: AsyncClient,
) -> None:
    await make(client, "planned", {"D": {"decision": "Retire", "date": "2099-01-01"}})
    await age("planned", 7)
    assert "planned" not in await due()


async def test_a_date_that_is_not_a_date_falls_back_to_the_last_change(
    client: AsyncClient,
) -> None:
    await make(client, "typo", {"D": {"decision": "Retire", "date": "2019-02-30"}})
    await age("typo", 7)
    assert "typo" in await due()


async def test_the_organizations_longer_period_wins(client: AsyncClient) -> None:
    date = await gate_dated(7)
    await make(client, "longer", {"D": {"decision": "Retire", "date": date}})
    await age("longer", 7)
    async with owner_connection() as conn:
        await conn.execute("UPDATE retention_policy SET record_years = 10")
    assert "longer" not in await due()


# --- disposal ---------------------------------------------------------------


async def test_disposal_leaves_a_tombstone_not_a_gap(client: AsyncClient) -> None:
    date = await gate_dated(7)
    await make(client, "gone", {"D": {"decision": "Retire", "date": date}})
    await client.patch("/api/projects/gone", json={"meta": {"owner": "A. Person"}})
    await age("gone", 7)

    run = await dispose()
    assert (run["projects"], run["revisions"]) == (1, 2)
    assert run["run_by"] == "ops@hospital.example"
    assert json.loads(run["disposed"])[0]["project"] == "gone"

    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT count(*) FROM projects") == 0
        versions = await conn.fetch(
            "SELECT doc, content_md5, purged_by FROM project_version"
            " WHERE project_id = 'gone'"
        )
        tomb = await conn.fetchrow(
            "SELECT deleted_by, last_rev, last_md5 FROM project_deletion"
            " WHERE project_id = 'gone'"
        )
    # The content is gone; that it existed, and what it hashed to, is not.
    assert len(versions) == 2
    assert all(json.loads(v["doc"]) == {} for v in versions)
    assert all(v["content_md5"] and v["purged_by"] == SYSTEM_ACTOR for v in versions)
    assert tomb["deleted_by"] == SYSTEM_ACTOR
    assert tomb["last_rev"] == 2 and tomb["last_md5"]


async def test_disposal_runs_once(client: AsyncClient) -> None:
    date = await gate_dated(7)
    await make(client, "once", {"D": {"decision": "Retire", "date": date}})
    await age("once", 7)
    assert (await dispose())["projects"] == 1
    again = await dispose()
    assert (again["projects"], again["revisions"]) == (0, 0)
    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT count(*) FROM disposal_run") == 2


async def test_a_deleted_projects_history_is_disposed_of_from_its_deletion(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        for pid, deleted in [("del-old", 7), ("del-new", 1)]:
            await conn.execute(
                "INSERT INTO project_version (project_id, incarnation, rev, doc,"
                " content_md5, changed_at) VALUES ($1, gen_random_uuid(), 1,"
                " '{\"meta\": {}}', 'abc', now() - interval '9 years')",
                pid,
            )
            await conn.execute(
                "INSERT INTO project_deletion (project_id, incarnation, deleted_at)"
                " SELECT project_id, incarnation, now() - make_interval(years => $2)"
                " FROM project_version WHERE project_id = $1",
                pid,
                deleted,
            )
    found = await due()
    assert found["del-old"]["kind"] == "deleted"
    assert "del-new" not in found
    assert (await dispose())["revisions"] == 1


async def test_a_held_project_is_reported_and_kept_until_the_hold_is_lifted(
    client: AsyncClient,
) -> None:
    date = await gate_dated(7)
    await make(client, "held", {"D": {"decision": "Retire", "date": date}})
    await age("held", 7)
    await hold("held", HoldAction.PLACE)
    assert (await due())["held"]["held"]
    assert (await dispose())["projects"] == 0
    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT count(*) FROM projects") == 1

    await hold("held", HoldAction.LIFT, "Case settled")
    assert (await dispose())["projects"] == 1


# --- the read trail ---------------------------------------------------------


async def add_reads(conn: asyncpg.Connection, project: str | None, years: int) -> None:
    await conn.execute(
        "INSERT INTO access_event (at, actor, action, project_id)"
        " VALUES (now() - make_interval(years => $2), 'reader', 'read_log', $1)",
        project,
        years,
    )


async def test_the_read_trail_loses_only_rows_past_the_period_and_not_held(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        await add_reads(conn, "p1", 7)
        await add_reads(conn, None, 7)
        await add_reads(conn, "p1", 2)
        await add_reads(conn, "kept", 7)
        await conn.execute(
            "INSERT INTO retention_hold (project_id, by_id, action, reason)"
            " VALUES ('kept', 'counsel', 'place', 'Discovery request')"
        )
        report = await conn.fetchrow("SELECT * FROM read_trail_due()")
        assert (report["events"], report["held"]) == (2, 1)

    assert (await dispose())["read_events"] == 2
    async with owner_connection() as conn:
        left = await conn.fetch("SELECT project_id FROM access_event ORDER BY id")
    assert [r["project_id"] for r in left] == ["p1", "kept"]


async def test_the_trigger_refuses_what_the_policy_does_not_allow(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        await add_reads(conn, "p", 2)
        await add_reads(conn, "held", 9)
        await conn.execute(
            "INSERT INTO retention_hold (project_id, by_id, action, reason)"
            " VALUES ('held', 'counsel', 'place', 'Litigation')"
        )
        # Even the owner, going around dispose_due(): too recent, held, or an edit.
        for sql in [
            "DELETE FROM access_event WHERE project_id = 'p'",
            "DELETE FROM access_event WHERE project_id = 'held'",
            "UPDATE access_event SET actor = 'someone else'",
        ]:
            with pytest.raises(asyncpg.RestrictViolationError, match="append-only"):
                await conn.execute(sql)
        # The organization's shorter policy (R-54) is the one thing that moves it.
        await conn.execute("UPDATE retention_policy SET read_trail_years = 1")
        assert await conn.execute(
            "DELETE FROM access_event WHERE project_id = 'p'"
        ) == ("DELETE 1")


# --- the policy and the holds are themselves records ---------------------------


async def test_the_policy_is_stamped_and_cannot_be_removed_or_zeroed(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        await conn.execute("UPDATE retention_policy SET record_years = 7")
        row = await conn.fetchrow("SELECT * FROM retention_policy")
        assert row["changed_by"] == await conn.fetchval("SELECT current_user")
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("UPDATE retention_policy SET read_trail_years = 0")
        with pytest.raises(asyncpg.RestrictViolationError):
            await conn.execute("DELETE FROM retention_policy")
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute("INSERT INTO retention_policy DEFAULT VALUES")


async def test_holds_are_append_only_and_need_a_reason(client: AsyncClient) -> None:
    await hold("p", HoldAction.PLACE)
    async with owner_connection() as conn:
        for sql in [
            "UPDATE retention_hold SET reason = 'x'",
            "DELETE FROM retention_hold",
        ]:
            with pytest.raises(asyncpg.RestrictViolationError, match="append-only"):
                await conn.execute(sql)
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO retention_hold (project_id, by_id, action, reason)"
                " VALUES ('p', 'x', 'place', '  ')"
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO retention_hold (project_id, by_id, action, reason)"
                " VALUES ('p', 'x', 'suspend', 'r')"
            )
        await conn.fetchrow("SELECT * FROM dispose_due('ops')")  # a row to refuse
        for sql in ["UPDATE disposal_run SET run_by = 'x'", "DELETE FROM disposal_run"]:
            with pytest.raises(asyncpg.RestrictViolationError, match="append-only"):
                await conn.execute(sql)


def test_the_hold_actions_match_the_check_constraint() -> None:
    check = re.search(r"action IN \(([^)]*)\)", MIGRATION)
    assert check is not None
    assert set(re.findall(r"'(\w+)'", check.group(1))) == {a.value for a in HoldAction}


def test_the_system_actor_is_the_one_the_sql_writes() -> None:
    assert f"'{SYSTEM_ACTOR}'" in MIGRATION


# --- only an operator disposes -----------------------------------------------


async def test_the_api_role_cannot_dispose_or_delete_the_read_trail(
    client: AsyncClient,
) -> None:
    conn = await asyncpg.connect(APP_ROLE_URL)
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetchrow("SELECT * FROM dispose_due('api')")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM access_event")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("UPDATE retention_policy SET record_years = 1")
    finally:
        await conn.close()


async def test_dispose_names_who_ran_it(client: AsyncClient) -> None:
    async with owner_connection() as conn:
        with pytest.raises(asyncpg.RaiseError, match="name of whoever"):
            await conn.fetchrow("SELECT * FROM dispose_due('  ')")


async def test_an_empty_read_trail_reports_nothing_due(client: AsyncClient) -> None:
    # read_trail_due() joins the cutoff to the rows; with none past it, the join's
    # empty row must not be counted as one (it was, as a read with no project).
    async with owner_connection() as conn:
        await add_reads(conn, None, 1)
        report = await conn.fetchrow("SELECT * FROM read_trail_due()")
    assert (report["events"], report["held"]) == (0, 0)


CHAI_DEFINITION = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "frameworks"
    / "chai"
    / "framework.json"
)


class GateClass(StrEnum):
    """A checkpoint decision's class, as a framework definition spells it (the
    dashboard's GateClass, D-74)."""

    GO = "go"
    CONDITIONAL = "conditional"
    REVISE = "revise"
    STOP = "stop"
    RETIRE = "retire"


# The classes that end a project (#168: decisions carry a class; the engine's
# rule reads the class, never the wording). Any STOP-class decision ends a
# project as Stopped and any RETIRE-class one as Retired, at whichever gate.
ENDING = frozenset({GateClass.STOP, GateClass.RETIRE})


def chai_definition() -> dict:
    """A fresh in-memory copy of CHAI's definition, so a mutation stays local."""
    return json.loads(CHAI_DEFINITION.read_text(encoding="utf-8"))


def ending_classes(definition: dict) -> set[GateClass]:
    """The ending classes the definition's checkpoints offer. Every class is
    parsed as a GateClass, so a misspelled one fails here instead of quietly
    never ending a project."""
    return {
        cls
        for gate in definition["gates"]
        for option in gate["options"]
        if (cls := GateClass(option["class"])) in ENDING
    }


def retiring_decisions(definition: dict) -> set[tuple[str, str]]:
    """(checkpoint, decision) pairs that end a project: every option of every
    gate whose class is an ending one."""
    return {
        (gate["id"], option["value"])
        for gate in definition["gates"]
        for option in gate["options"]
        if GateClass(option["class"]) in ENDING
    }


# 008's rule was CHAI's words written into retention_due(); 010 moved it into the
# retirement_rule table, seeded with the same four rows, and the migrate job keeps the
# table equal to the build's manifest (the sync tests below).
RULES_MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "010_retirement_rules.sql"
).read_text(encoding="utf-8")


def retiring_decisions_sql(source: str) -> set[tuple[str, str]]:
    """CHAI's (checkpoint, decision) rows in 010's seed of retirement_rule."""
    seed = source.split("INSERT INTO retirement_rule (", 1)[1].split(";", 1)[0]
    return set(re.findall(r"\('chai', '(\w+)', '([^']+)'\)", seed))


def test_retired_means_the_same_in_the_database_and_the_dashboard() -> None:
    definition = chai_definition()
    assert ending_classes(definition) == ENDING
    dashboard = retiring_decisions(definition)
    assert dashboard == {("A", "Stop"), ("B", "Stop"), ("C", "Stop"), ("D", "Retire")}
    assert retiring_decisions_sql(RULES_MIGRATION) == dashboard


async def test_the_database_retires_by_the_table_not_by_literals(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        body = await conn.fetchval(
            "SELECT pg_get_functiondef('retention_due()'::regprocedure)"
        )
        rows = await conn.fetch("SELECT gate_id, decision FROM retirement_rule")
    assert "retirement_rule" in body
    assert "'Stop'" not in body and "'Retire'" not in body
    assert {(r["gate_id"], r["decision"]) for r in rows} == retiring_decisions(
        chai_definition()
    )


def gate(definition: dict, gate_id: str) -> dict:
    return next(g for g in definition["gates"] if g["id"] == gate_id)


def test_the_rule_comparison_notices_a_difference() -> None:
    # Mutation: a new way to retire in the dashboard, or one dropped from the SQL.
    definition = chai_definition()
    gate(definition, "C")["options"].append({"value": "Withdraw", "class": "stop"})
    assert ("C", "Withdraw") in retiring_decisions(definition)
    assert retiring_decisions(definition) != retiring_decisions_sql(RULES_MIGRATION)
    # Or a decision that stops being of an ending class.
    weaker = chai_definition()
    retire = next(o for o in gate(weaker, "D")["options"] if o["value"] == "Retire")
    retire["class"] = "revise"
    assert ending_classes(weaker) == {GateClass.STOP}
    assert ("D", "Retire") not in retiring_decisions(weaker)
    # Or a class nobody defined, which must fail rather than never end a project.
    typo = chai_definition()
    gate(typo, "D")["options"][-1]["class"] = "retired"
    with pytest.raises(ValueError):
        retiring_decisions(typo)
    sql = RULES_MIGRATION.replace("('chai', 'D', 'Retire')", "('chai', 'D', 'Keep')")
    assert ("D", "Retire") not in retiring_decisions_sql(sql)
    assert retiring_decisions_sql(sql) != retiring_decisions(chai_definition())


# --- staff names and emails (principals) --------------------------------------
# R-54: kept while the person is active, then as long as a retained record refers to
# them. Disposal deletes a principal not seen for the read-trail period whom nothing
# retained mentions, by id or by email.


async def add_principal(conn: asyncpg.Connection, pid: str, seen_years: int) -> None:
    await conn.execute(
        "INSERT INTO principals (id, name, email, first_seen, last_seen)"
        " VALUES ($1, 'Someone', $1, now() - make_interval(years => $2 + 1),"
        " now() - make_interval(years => $2))",
        pid,
        seen_years,
    )


async def principals_left() -> set[str]:
    async with owner_connection() as conn:
        return {r["id"] for r in await conn.fetch("SELECT id FROM principals")}


async def test_a_long_gone_unreferenced_person_is_disposed_of(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        await add_principal(conn, "gone@x.org", 7)
        await add_principal(conn, "recent@x.org", 1)
        due = {r["id"] for r in await conn.fetch("SELECT id FROM principals_due()")}
    assert due == {"gone@x.org"}
    run = await dispose()
    assert run["principals"] == 1
    assert "gone@x.org" not in await principals_left()
    assert "recent@x.org" in await principals_left()


async def test_anyone_a_retained_record_names_is_kept(client: AsyncClient) -> None:
    await make(client, "named", {"D": {"decision": "Continue"}})
    async with owner_connection() as conn:
        # An author of a revision: purging keeps the author (R-12), so they stay.
        await conn.execute(
            "INSERT INTO project_version (project_id, incarnation, rev, doc,"
            " content_md5, changed_by) SELECT id, incarnation, 99, '{}', 'x',"
            " 'author@x.org' FROM projects WHERE id = 'named'"
        )
        await conn.execute(
            "UPDATE project_version SET doc = '{}'::jsonb, purged_at = now(),"
            " purged_by = 'dpo@x.org' WHERE project_id = 'named'"
        )
        # Named only inside a document, by email (an access list, a sign-off).
        await conn.execute(
            "UPDATE projects SET doc = jsonb_set(doc, '{access}',"
            " '{\"owners\": [\"Listed@X.org\"]}') WHERE id = 'named'"
        )
        for pid in ("author@x.org", "dpo@x.org", "listed@x.org"):
            await add_principal(conn, pid, 9)
    await dispose()
    assert {"author@x.org", "dpo@x.org", "listed@x.org"} <= await principals_left()


async def test_a_person_known_only_from_old_reads_goes_with_them(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        await add_principal(conn, "reader@x.org", 7)
        await conn.execute(
            "INSERT INTO access_event (at, actor, action)"
            " VALUES (now() - interval '7 years', 'reader@x.org', 'list')"
        )
    run = await dispose()
    # The same run deletes the reads, then finds nothing left that names them.
    assert (run["read_events"], run["principals"]) == (1, 1)


async def test_every_column_that_names_a_person_is_checked() -> None:
    async with owner_connection() as conn:
        columns = [
            r[0]
            for r in await conn.fetch(
                "SELECT table_name || '.' || column_name FROM information_schema.columns"
                " WHERE table_schema = 'public' AND (column_name LIKE '%\\_by'"
                " OR column_name IN ('by_id', 'actor'))"
            )
        ]
        body = await conn.fetchval(
            "SELECT pg_get_functiondef('principal_referenced(text)'::regprocedure)"
        )

    # Each EXISTS clause reads one table; the column must be in that table's clause.
    def clauses(sql: str) -> dict[str, str]:
        out = {}
        for part in sql.split("EXISTS (")[1:]:
            m = re.search(r"FROM (\w+) \w+, w", part)
            if m:
                out[m.group(1)] = part
        return out

    found = clauses(body)
    missing = [
        c for c in columns
        if not re.search(rf"\.{c.split('.')[1]}\b", found.get(c.split(".")[0], ""))
    ]  # fmt: skip
    assert columns and not missing, missing
    # Mutation: a clause that stopped reading purged_by is noticed.
    weaker = clauses(body.replace(" OR lower(l.purged_by) = w.v", ""))
    assert ".purged_by" not in weaker["project_log"]


# --- retirement from the build's definition (#168 PR C; R-66, D-76) ----------------
# The real migrate job, run with a manifest the build's own code writes, decides what
# retention_due() treats as retired. For every checkpoint option of a definition, a
# project that took it more than six years ago is due exactly when the option's class
# ends a project, for CHAI and for a stand-in primary that shares none of its words.


async def decided(
    client: AsyncClient, pid: str, stamp: str | None, gate_id: str, value: str
) -> None:
    """A project created through the API, decided seven years ago. A stamp is what
    the API accepts: exactly {"id": <the active primary>}."""
    meta: dict = {"solution": pid}
    if stamp is not None:
        meta["framework"] = {"id": stamp}
    date = await gate_dated(7)
    response = await client.post(
        f"/api/projects/{pid}",
        json={"meta": meta, "gates": {gate_id: {"decision": value, "date": date}}},
    )
    assert response.status_code == 201, response.text
    await age(pid, 7)


async def stored(pid: str, doc: dict, years: float = 7) -> None:
    """A record written straight into the table, as the owner, last changed `years`
    ago. For stamps the API refuses (a record of another framework, a blank stamp):
    what the SQL does with them is the point, however they got there."""
    async with owner_connection() as conn:
        await conn.execute(
            "INSERT INTO projects (id, doc, created_by, updated_by, updated_at)"
            " VALUES ($1, $2::text::jsonb, 'a@x', 'a@x',"
            " now() - make_interval(days => $3))",
            pid,
            json.dumps(doc),
            int(years * 365.25),
        )


def stamped(stamp: str | None, gates: dict) -> dict:
    meta: dict = {"solution": "x"}
    if stamp is not None:
        meta["framework"] = {"id": stamp}
    return {"meta": meta, "gates": gates}


async def due_when(
    function: str, mutate: Callable[[str], str] | None = None
) -> set[str]:
    """What retention_due() returns, with `function` (a regprocedure) replaced by
    `mutate(its definition)` inside a transaction that is rolled back. The mutation
    tests below use it to show that each guard in 010 is load-bearing: break it and
    the same records come out differently."""
    async with owner_connection() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            if mutate is not None:
                body = await conn.fetchval(
                    "SELECT pg_get_functiondef($1::regprocedure)", function
                )
                broken = mutate(body)
                assert broken != body, "the mutation did not apply"
                await conn.execute(broken)
            rows = await conn.fetch("SELECT project_id FROM retention_due()")
            return {r["project_id"] for r in rows}
        finally:
            await tr.rollback()


RETIRED_UNDER = "retired_under(text[], text[], text[])"
RECORD_FRAMEWORK = "record_framework(jsonb)"


def without_the_framework_join(body: str) -> str:
    return body.replace("r.f = record_framework(p.doc)", "true")


async def every_option(
    client: AsyncClient, definition: dict, prefix: str, stamp: str | None
) -> set[str]:
    """A project per (gate, option), each decided seven years ago; the ids of those
    whose option ends a project."""
    ending = set()
    for i, g in enumerate(definition["gates"]):
        for j, option in enumerate(g["options"]):
            pid = f"{prefix}{i}-{j}"
            await decided(client, pid, stamp, g["id"], option["value"])
            if manifests.GateClass(option["class"]) in manifests.ENDING_CLASSES:
                ending.add(pid)
    return ending


async def rules_now() -> set[tuple[str, str, str]]:
    async with owner_connection() as conn:
        rows = await conn.fetch(
            "SELECT framework_id, gate_id, decision FROM retirement_rule"
        )
    return {tuple(r) for r in rows}


async def latest_change() -> asyncpg.Record:
    async with owner_connection() as conn:
        return await conn.fetchrow(
            "SELECT *, (SELECT count(*) FROM retirement_rule_change) AS n,"
            " current_user AS me FROM retirement_rule_change ORDER BY id DESC LIMIT 1"
        )


def manifest_rules(path: Path) -> set[tuple[str, str, str]]:
    return {
        (f["id"], p["gate"], p["decision"])
        for f in manifests.manifest_of(path)["frameworks"]
        for p in f["retire"]
    }


def chai_rules() -> set[tuple[str, str, str]]:
    return manifests.pairs(manifests.default_build())


def migrate(path: Path, ack: str = "") -> subprocess.CompletedProcess:
    env = {"RETIREMENT_MANIFEST": str(path)}
    if ack:
        env["RETIREMENT_RULES_ACK"] = ack
    return manifests.run_migrate(DB_URL, **env)


async def acme_synced(tmp_path: Path) -> Path:
    """The stand-in primary's manifest, synced with the acknowledgment it needs."""
    path = manifests.write(tmp_path / "acme.json", {"acme": manifests.STAND_IN}, "acme")
    ack = manifests.transition(
        await manifests.follows(DB_URL, 1),
        ("chai", chai_rules()),
        ("acme", chai_rules() | manifest_rules(path)),
    )
    done = migrate(path, ack)
    assert done.returncode == 0, done.stdout + done.stderr
    return path


async def test_every_chai_decision_retires_exactly_when_its_class_ends_a_project(
    client: AsyncClient, tmp_path: Path
) -> None:
    path = manifests.write(tmp_path / "m.json", manifests.default_build(), "chai")
    done = migrate(path)
    assert done.returncode == 0, done.stdout + done.stderr
    # The seed is the default build's rule set: no change, and so no acknowledgment,
    # only the record that a manifest confirmed it.
    assert "retirement rules confirmed" in done.stdout
    assert await rules_now() == manifest_rules(path) == chai_rules()
    change = await latest_change()
    assert change["n"] == 2 and change["source"] == "manifest"
    assert not change["acknowledged"]
    assert change["old_rules"] == change["new_rules"]

    chai = manifests.definition("chai")
    ending = await every_option(client, chai, "u", None)  # unstamped: CHAI's
    ending |= await every_option(client, chai, "s", "chai")
    found = await due()
    assert set(found) == ending and len(ending) == 8
    assert {r["kind"] for r in found.values()} == {"retired"}

    # And a second run has nothing to record.
    again = migrate(path)
    assert again.returncode == 0 and "retirement rules unchanged" in again.stdout
    assert (await latest_change())["n"] == 2


# --- whose rules a record follows (the framework join, record_framework) ------------


async def test_a_record_follows_only_its_own_frameworks_rules(
    client: AsyncClient,
) -> None:
    # CHAI's rules are the ones loaded (the seed). D decided "Retire" seven years
    # ago is CHAI's ending decision: a record of another framework holding the same
    # words has not ended, and an unstamped one (CHAI's) has.
    retire = {"D": {"decision": "Retire", "date": await gate_dated(7)}}
    await stored("other", stamped("acme", retire))
    await stored("unstamped", stamped(None, retire))
    await stored("chai", stamped("chai", retire))
    found = await due_when(RETIRED_UNDER)
    assert found == {"unstamped", "chai"}

    # Mutation: without the join on the record's framework, CHAI's words would
    # retire the other framework's record too.
    assert "other" in await due_when(RETIRED_UNDER, without_the_framework_join)


async def test_the_mirror_a_chai_record_never_retires_by_anothers_words(
    client: AsyncClient, tmp_path: Path
) -> None:
    await acme_synced(tmp_path)
    decommission = {"annual": {"decision": "Decommission", "date": await gate_dated(7)}}
    await stored("acme-rec", stamped("acme", decommission))
    await stored("unstamped", stamped(None, decommission))
    await stored("chai-rec", stamped("chai", decommission))
    assert await due_when(RETIRED_UNDER) == {"acme-rec"}
    broken = await due_when(RETIRED_UNDER, without_the_framework_join)
    assert {"unstamped", "chai-rec"} <= broken


async def test_a_blank_stamp_is_chai(client: AsyncClient) -> None:
    retire = {"D": {"decision": "Retire", "date": await gate_dated(7)}}
    await stored("blank", stamped("", retire))
    assert "blank" in await due_when(RETIRED_UNDER)

    # Mutation: without nullif, "" is a framework of its own, with no rules.
    def without_nullif(body: str) -> str:
        return body.replace("nullif(doc #>> '{meta,framework,id}', '')",
                            "doc #>> '{meta,framework,id}'")  # fmt: skip

    assert "blank" not in await due_when(RECORD_FRAMEWORK, without_nullif)


async def test_the_clock_starts_at_the_latest_ending_decision(
    client: AsyncClient,
) -> None:
    # Stopped at A ten years ago, and D decided "Retire" last year: the project's
    # clock starts last year, so it is not due (R-56: a later decision only ever
    # makes a record live longer).
    await stored(
        "twice",
        stamped(None, {
            "A": {"decision": "Stop", "date": await gate_dated(10)},
            "D": {"decision": "Retire", "date": await gate_dated(1)},
        }),
    )  # fmt: skip
    assert "twice" not in await due_when(RETIRED_UNDER)

    # Mutation: the earliest ending decision instead of the latest would make it due.
    def earliest(body: str) -> str:
        return body.replace("max(retention_gate_date", "min(retention_gate_date")

    assert "twice" in await due_when(RETIRED_UNDER, earliest)


# --- changing the rules needs an acknowledgment of that transition -----------------


async def test_a_stand_in_primary_retires_by_its_own_words_once_acknowledged(
    client: AsyncClient, tmp_path: Path
) -> None:
    # A record of the CHAI build, due for disposal under CHAI's rules.
    await decided(client, "legacy", None, "D", "Retire")
    assert "legacy" in await due()

    path = manifests.write(tmp_path / "m.json", {"acme": manifests.STAND_IN}, "acme")
    wanted = manifests.manifest_of(path)
    ack = manifests.transition(
        await manifests.follows(DB_URL, 1),
        ("chai", chai_rules()),
        ("acme", chai_rules() | manifest_rules(path)),
    )
    # Without the acknowledgment, with the new rule set's own hash, or with the
    # value of the transition between the two primary rule-set hashes (what earlier
    # versions took), it is refused: adding rules changes disposal too.
    old_form = hashlib.sha256(
        json.dumps(
            {"from": manifests.SEED_HASH, "to": wanted["ruleSetHash"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    for given in ("", wanted["ruleSetHash"], old_form):
        refused = migrate(path, given)
        assert refused.returncode == 3, refused.stdout + refused.stderr
        assert (
            "acme: checkpoint annual decided 'Decommission' (added)" in refused.stderr
        )
        assert f"RETIREMENT_RULES_ACK={ack}" in refused.stderr
        assert manifests.events(refused, "retirement.rules_refused")
        assert await rules_now() == chai_rules()
        assert (await latest_change())["n"] == 1

    done = migrate(path, ack)
    assert done.returncode == 0, done.stdout + done.stderr
    # A manifest governs only the frameworks it lists. CHAI's rows stay, so CHAI's
    # records keep retiring by them, and the job says so.
    assert await rules_now() == manifest_rules(path) | chai_rules()
    assert "not listed by this manifest, left as they are: chai (4 rule(s))" in (
        done.stdout
    )
    change = await latest_change()
    assert change["n"] == 2 and change["acknowledged"]
    assert change["source"] == "manifest" and change["framework_id"] == "acme"
    assert change["changed_by"] == change["me"]
    assert change["rule_set_hash"] == wanted["ruleSetHash"]
    assert change["definition_hash"] == wanted["frameworks"][0]["sha256"]
    assert {tuple(r) for r in json.loads(change["old_rules"])} == chai_rules()
    assert {tuple(r) for r in json.loads(change["new_rules"])} == (
        manifest_rules(path) | chai_rules()
    )
    (event,) = manifests.events(done, "retirement.rules_changed")
    assert event["acknowledged"] is True and len(event["added"]) == 3
    assert event["removed"] == [] and event["unlisted"] == ["chai"]

    ending = await every_option(client, manifests.STAND_IN, "a", "acme")
    # CHAI's words in an acme record end nothing: the words are the definition's.
    await decided(client, "acme-chai-words", "acme", "intake", "Stop")
    found = await due()
    assert set(found) == ending | {"legacy"} and len(ending) == 3


async def test_a_new_ending_decision_is_refused_until_acknowledged(
    client: AsyncClient, tmp_path: Path
) -> None:
    path = manifests.write(
        tmp_path / "m.json", manifests.chai_with("C", "Withdraw", "stop"), "chai"
    )
    ack = manifests.transition(
        await manifests.follows(DB_URL, 1),
        ("chai", chai_rules()),
        ("chai", manifest_rules(path)),
    )
    await decided(client, "withdrawn", None, "C", "Withdraw")
    assert "withdrawn" not in await due()

    refused = migrate(path)
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert "chai: checkpoint C decided 'Withdraw' (added)" in refused.stderr
    assert "withdrawn: becomes due" in refused.stderr
    assert f"RETIREMENT_RULES_ACK={ack}" in refused.stderr
    assert await rules_now() == chai_rules()
    assert "withdrawn" not in await due()

    done = migrate(path, ack)
    assert done.returncode == 0, done.stdout + done.stderr
    assert ("chai", "C", "Withdraw") in await rules_now() == manifest_rules(path)
    assert "withdrawn" in await due()
    change = await latest_change()
    assert change["n"] == 2 and change["acknowledged"]
    (event,) = manifests.events(done, "retirement.rules_changed")
    assert event["added"] == [["chai", "C", "Withdraw"]] and event["removed"] == []

    # Run again, with or without the acknowledgment: nothing to do, nothing recorded.
    for given in ("", ack):
        again = migrate(path, given)
        assert again.returncode == 0 and "retirement rules unchanged" in again.stdout
        assert (await latest_change())["n"] == 2
        assert not manifests.events(again, "retirement.rules_changed")


async def test_a_leftover_acknowledgment_never_matches_another_transition(
    client: AsyncClient, tmp_path: Path
) -> None:
    withdraw = manifests.write(
        tmp_path / "w.json", manifests.chai_with("C", "Withdraw", "stop"), "chai"
    )
    first = manifests.transition(
        await manifests.follows(DB_URL, 1),
        ("chai", chai_rules()),
        ("chai", manifest_rules(withdraw)),
    )
    assert migrate(withdraw, first).returncode == 0

    # The next build adds something else. The acknowledgment left set from the
    # last deploy is for another transition, and is refused.
    pause = manifests.chai_with("C", "Withdraw", "stop")
    pause["chai"]["gates"][1]["options"].append({"value": "Shelve", "class": "stop"})
    later = manifests.write(tmp_path / "p.json", pause, "chai")
    refused = migrate(later, first)
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert "(added)" in refused.stderr
    assert await rules_now() == manifest_rules(withdraw)


async def test_a_stale_manifest_cannot_undo_a_newer_one(
    client: AsyncClient, tmp_path: Path
) -> None:
    newer = manifests.write(
        tmp_path / "new.json", manifests.chai_with("C", "Withdraw", "stop"), "chai"
    )
    newer_hash = manifests.manifest_of(newer)["ruleSetHash"]
    added = manifests.transition(
        await manifests.follows(DB_URL, 1),
        ("chai", chai_rules()),
        ("chai", manifest_rules(newer)),
    )
    assert migrate(newer, added).returncode == 0
    await decided(client, "withdrawn", None, "C", "Withdraw")
    assert "withdrawn" in await due()
    before = await rules_now()

    # The default build's manifest, deployed again over the newer one. No
    # acknowledgment, the one left from adding, either rule set's own hash, or any
    # other hash is not the acknowledgment of this transition.
    for ack in ("", added, newer_hash, manifests.SEED_HASH, "f" * 64):
        stale = migrate(manifests.DEFAULT_MANIFEST, ack)
        assert stale.returncode == 3, (ack, stale.stdout + stale.stderr)
        assert "chai: checkpoint C decided 'Withdraw' (removed)" in stale.stderr
        assert "withdrawn: stops being due" in stale.stderr
        assert await rules_now() == before
        assert (await latest_change())["n"] == 2
    assert "withdrawn" in await due()

    # Acknowledged, the removal goes through.
    removed = manifests.transition(
        await manifests.follows(DB_URL, 2),
        ("chai", manifest_rules(newer)),
        ("chai", chai_rules()),
    )
    done = migrate(manifests.DEFAULT_MANIFEST, removed)
    assert done.returncode == 0, done.stdout + done.stderr
    assert await rules_now() == chai_rules()
    assert "withdrawn" not in await due()

    # And the newer manifest, deployed again by mistake with that acknowledgment
    # still set, cannot quietly put the rule back.
    again = migrate(newer, removed)
    assert again.returncode == 3, again.stdout + again.stderr
    assert "withdrawn: becomes due" in again.stderr
    assert await rules_now() == chai_rules()


async def test_a_manifest_leaves_the_rules_of_frameworks_it_does_not_list(
    client: AsyncClient, tmp_path: Path
) -> None:
    acme = await acme_synced(tmp_path)
    await decided(client, "acme-old", "acme", "annual", "Decommission")
    assert "acme-old" in await due()

    # Back to the default build, which lists chai and optica but not acme. No row
    # changes (CHAI's four rows are still there), but the primary does, so it is
    # acknowledged like any change; acme's rows are left: acme's records keep
    # retiring by them.
    both = chai_rules() | manifest_rules(acme)
    assert migrate(manifests.DEFAULT_MANIFEST).returncode == 3
    done = migrate(
        manifests.DEFAULT_MANIFEST,
        manifests.transition(
            await manifests.follows(DB_URL, 2), ("acme", both), ("chai", both)
        ),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "not listed by this manifest, left as they are: acme (3 rule(s))" in (
        done.stdout
    )
    assert await rules_now() == chai_rules() | manifest_rules(acme)
    assert "acme-old" in await due()
    change = await latest_change()
    assert change["framework_id"] == "chai" and change["acknowledged"]
    assert change["rule_set_hash"] == manifests.SEED_HASH


# --- the acknowledgment binds the whole change it was printed for ---------------------
# Each of these sequences was shown, against a real PostgreSQL, to let an
# acknowledgment printed for one change accept another while it named only the
# primary's rule-set hashes (#168 PR C review).


def printed_ack(done: subprocess.CompletedProcess) -> str:
    """The acknowledgment a refused job printed: what an operator copies."""
    assert done.returncode == 3, done.stdout + done.stderr
    found = re.search(r"RETIREMENT_RULES_ACK=([0-9a-f]{64})", done.stderr)
    assert found, done.stderr
    return found.group(1)


def with_unlisted_as_supplement(path: Path, fid: str, out: Path) -> Path:
    """The manifest at `path`, also listing `fid` as a supplement that ends nothing:
    what a build that keeps an earlier primary as a supplement writes. It does not
    change the primary's rule-set hash, and it removes every rule `fid` has."""
    raw = manifests.manifest_of(path)
    raw["frameworks"].append(
        {"id": fid, "role": "supplement", "version": "1", "sha256": "0" * 64,
         "retire": []}
    )  # fmt: skip
    out.write_text(json.dumps(raw), encoding="utf-8")
    return out


async def test_an_ack_for_a_harmless_addition_never_accepts_a_removal(
    client: AsyncClient, tmp_path: Path
) -> None:
    # The operator is shown acme's three rules added and no project affected.
    acme = manifests.write(tmp_path / "acme.json", {"acme": manifests.STAND_IN}, "acme")
    shown = migrate(acme)
    assert "0 live project(s) would change" in shown.stderr, shown.stderr
    ack = printed_ack(shown)
    await decided(client, "legacy", None, "D", "Retire")
    assert "legacy" in await due()

    # A different build is deployed with that value: the same primary and the same
    # primary rule set, but it lists chai as a supplement, so CHAI's four rules would
    # go and CHAI's records would stop coming due. That is not what was shown.
    other = with_unlisted_as_supplement(acme, "chai", tmp_path / "other.json")
    assert (
        manifests.manifest_of(other)["ruleSetHash"]
        == (manifests.manifest_of(acme)["ruleSetHash"])
    )
    refused = migrate(other, ack)
    assert refused.returncode == 3, refused.stdout + refused.stderr
    assert "chai: checkpoint D decided 'Retire' (removed)" in refused.stderr
    assert "legacy: stops being due" in refused.stderr
    assert await rules_now() == chai_rules()
    assert (await latest_change())["n"] == 1
    assert "legacy" in await due()


async def test_a_rollback_is_acknowledged_and_does_not_revive_an_old_ack(
    client: AsyncClient, tmp_path: Path
) -> None:
    await decided(client, "legacy", None, "D", "Retire")
    acme = manifests.write(tmp_path / "acme.json", {"acme": manifests.STAND_IN}, "acme")
    first = printed_ack(migrate(acme))
    assert migrate(acme, first).returncode == 0

    # Rolling back to the default build changes no row (chai's rules are still
    # there) but changes the primary, and so the stamp the API accepts: it is a
    # change, and is refused without its own acknowledgment.
    rollback = migrate(manifests.DEFAULT_MANIFEST)
    assert "the primary changes: acme -> chai" in rollback.stderr, rollback.stderr
    back = printed_ack(rollback)
    for given in ("", first):
        refused = migrate(manifests.DEFAULT_MANIFEST, given)
        assert refused.returncode == 3, (given, refused.stdout + refused.stderr)
        assert (await latest_change())["framework_id"] == "acme"
    done = migrate(manifests.DEFAULT_MANIFEST, back)
    assert done.returncode == 0, done.stdout + done.stderr
    change = await latest_change()
    assert change["framework_id"] == "chai" and change["acknowledged"]
    assert change["n"] == 3

    # The first value, still set, now meets a state whose primary rule set and
    # primary are the ones it was printed from. It must not accept a removal of
    # CHAI's rules (acme, listing chai as a supplement), nor anything else.
    other = with_unlisted_as_supplement(acme, "chai", tmp_path / "other.json")
    for given in (first, back):
        refused = migrate(other, given)
        assert refused.returncode == 3, (given, refused.stdout + refused.stderr)
        assert "legacy: stops being due" in refused.stderr
    assert await rules_now() == chai_rules() | manifest_rules(acme)
    assert "legacy" in await due()


async def test_a_leftover_ack_never_accepts_a_later_change(
    client: AsyncClient, tmp_path: Path
) -> None:
    # Every value used so far stays set by mistake, one after another, through a
    # change, its reversal, the same change again, and other changes. None of them
    # is ever accepted for a later change, even one identical to the change it was
    # printed for: each acknowledges one change from one point in the history.
    withdraw = manifests.write(
        tmp_path / "w.json", manifests.chai_with("C", "Withdraw", "stop"), "chai"
    )
    acme = manifests.write(tmp_path / "acme.json", {"acme": manifests.STAND_IN}, "acme")
    other = with_unlisted_as_supplement(acme, "chai", tmp_path / "other.json")
    steps = [
        withdraw,
        manifests.DEFAULT_MANIFEST,
        withdraw,  # the first change again, from the same rules as the first time
        acme,
        manifests.DEFAULT_MANIFEST,
        other,
    ]
    used: list[str] = []
    for step in steps:
        before = (await rules_now(), (await latest_change())["n"])
        for old in used:
            stale = migrate(step, old)
            assert stale.returncode == 3, (step, old, stale.stdout + stale.stderr)
            assert (await rules_now(), (await latest_change())["n"]) == before
        ack = printed_ack(migrate(step))
        done = migrate(step, ack)
        assert done.returncode == 0, done.stdout + done.stderr
        # Spent: the same value, the same manifest, again, has nothing to do.
        assert "retirement rules unchanged" in migrate(step, ack).stdout
        used.append(ack)
    assert len(set(used)) == len(used)


async def test_a_primary_switch_over_the_same_rules_needs_an_ack(
    client: AsyncClient, tmp_path: Path
) -> None:
    # The database already holds acme's rules beside CHAI's (written by the owner,
    # as an earlier build could have left them). A build making acme the primary
    # adds and removes no row, but it changes the stamp the API accepts and so whose
    # rules new records follow: that is a change, shown and acknowledged.
    acme = manifests.write(tmp_path / "acme.json", {"acme": manifests.STAND_IN}, "acme")
    async with owner_connection() as conn:
        await conn.executemany(
            "INSERT INTO retirement_rule (framework_id, gate_id, decision)"
            " VALUES ($1, $2, $3)",
            sorted(manifest_rules(acme)),
        )
    both = chai_rules() | manifest_rules(acme)
    refused = migrate(acme)
    assert "the primary changes: chai -> acme" in refused.stderr, refused.stderr
    ack = printed_ack(refused)
    assert ack == manifests.transition(
        await manifests.follows(DB_URL, 1), ("chai", both), ("acme", both)
    )
    assert (await latest_change())["framework_id"] == "chai"
    done = migrate(acme, ack)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "primary chai -> acme, acknowledged" in done.stdout
    change = await latest_change()
    assert change["framework_id"] == "acme" and change["acknowledged"]
    (event,) = manifests.events(done, "retirement.rules_changed")
    assert event["active_primary"] == "chai" and event["framework"] == "acme"
    assert await rules_now() == both


# --- the acknowledgment belongs to one database ------------------------------------
# It named only the history row it follows, a bigserial id, so a value printed for
# one database was accepted by any other at the same point in the same history: a
# staging value on production, or a fresh database built the same way (shown against
# PostgreSQL 17 in review). It now also binds a random nonce each database is created
# with (012) and the time of the change it follows.

OTHER_DB = "chai_test_other_database"


def url_of(database: str) -> str:
    parts = urlsplit(DB_URL)
    return urlunsplit(parts._replace(path=f"/{database}"))


@contextlib.asynccontextmanager
async def another_database() -> AsyncIterator[str]:
    """A second database, migrated by the real job with the default build: the same
    schema and the same rules as the one under test, made separately."""
    async with owner_connection() as conn:
        await conn.execute(f"DROP DATABASE IF EXISTS {OTHER_DB} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {OTHER_DB}")
    try:
        done = manifests.run_migrate(
            url_of(OTHER_DB), RETIREMENT_MANIFEST=str(manifests.DEFAULT_MANIFEST)
        )
        assert done.returncode == 0, done.stdout + done.stderr
        yield url_of(OTHER_DB)
    finally:
        async with owner_connection() as conn:
            await conn.execute(f"DROP DATABASE IF EXISTS {OTHER_DB} WITH (FORCE)")


SAME_MOMENT = "2026-01-01 00:00:00+00"


async def give_the_same_history(url: str) -> None:
    """Make a database's rules and their history exactly 010's seed, recorded at one
    fixed moment, so two databases differ in nothing the history holds."""
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "TRUNCATE retirement_rule, retirement_rule_change RESTART IDENTITY"
        )
        await conn.executemany(
            "INSERT INTO retirement_rule (framework_id, gate_id, decision)"
            " VALUES ($1, $2, $3)",
            sorted(manifests.CHAI_RULES),
        )
        await conn.execute(
            "INSERT INTO retirement_rule_change (at, changed_by, source, framework_id,"
            " old_rules, new_rules, rule_set_hash)"
            " VALUES ($1::text::timestamptz, 'owner', 'seed', 'chai', '[]'::jsonb,"
            " $2::text::jsonb, $3)",
            SAME_MOMENT,
            json.dumps(sorted(list(r) for r in manifests.CHAI_RULES)),
            manifests.SEED_HASH,
        )
    finally:
        await conn.close()


async def history_of(url: str) -> list[tuple]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "SELECT id, at, changed_by, source, framework_id, old_rules::text,"
            " new_rules::text, rule_set_hash FROM retirement_rule_change ORDER BY id"
        )
        rules = await conn.fetch(
            "SELECT * FROM retirement_rule ORDER BY framework_id, gate_id, decision"
        )
    finally:
        await conn.close()
    return [tuple(r) for r in rows] + [tuple(r) for r in rules]


async def test_a_value_printed_for_one_database_is_refused_by_another(
    client: AsyncClient, tmp_path: Path
) -> None:
    acme = manifests.write(tmp_path / "acme.json", {"acme": manifests.STAND_IN}, "acme")
    async with another_database() as other:
        for url in (DB_URL, other):
            await give_the_same_history(url)
        assert await history_of(DB_URL) == await history_of(other)

        value = printed_ack(migrate(acme))
        unchanged = await history_of(other)
        elsewhere = manifests.run_migrate(
            other, RETIREMENT_MANIFEST=str(acme), RETIREMENT_RULES_ACK=value
        )
        # Refused there, printing that database's own value, and nothing changed.
        assert elsewhere.returncode == 3, elsewhere.stdout + elsewhere.stderr
        assert printed_ack(elsewhere) != value
        assert await history_of(other) == unchanged
        # The database it was printed for accepts it.
        done = migrate(acme, value)
        assert done.returncode == 0, done.stdout + done.stderr


async def test_the_database_test_fails_without_the_nonce(
    client: AsyncClient, tmp_path: Path, monkeypatch
) -> None:
    # Mutation: the acknowledgment without the database's nonce. The two databases'
    # histories are identical, so a value printed for one is accepted by the other.
    from app import retirement

    async def no_nonce(conn) -> str:
        return ""

    monkeypatch.setattr(retirement, "database_nonce", no_nonce)
    acme = manifests.write(tmp_path / "acme.json", {"acme": manifests.STAND_IN}, "acme")
    manifest = retirement.load_manifest(str(acme))
    async with another_database() as other:
        for url in (DB_URL, other):
            await give_the_same_history(url)
        here = await asyncpg.connect(DB_URL)
        there = await asyncpg.connect(other)
        try:
            with pytest.raises(retirement.RulesRefused) as refused:
                await retirement.sync_rules(here, manifest, "")
            value = re.search(
                r"RETIREMENT_RULES_ACK=([0-9a-f]{64})", str(refused.value)
            ).group(1)  # type: ignore[union-attr]
            synced = await retirement.sync_rules(there, manifest, value)
        finally:
            await here.close()
            await there.close()
        assert synced.outcome is retirement.SyncOutcome.CHANGED


@pytest.mark.parametrize("part", ["database", "follows", "at", "before", "after"])
def test_every_part_of_the_acknowledgment_changes_it(part: str) -> None:
    from app.retirement import Follows, RuleState, transition_ack

    rules = frozenset(manifests.CHAI_RULES)
    base = {
        "follows": Follows("d1", 1, "2026-01-01T00:00:00.000000Z"),
        "before": RuleState("chai", rules),
        "after": RuleState("acme", rules),
    }
    changed = dict(base)
    follows = base["follows"]
    match part:
        case "database":
            changed["follows"] = follows._replace(database="d2")
        case "follows":
            changed["follows"] = follows._replace(change_id=2)
        case "at":
            changed["follows"] = follows._replace(at="2026-01-01T00:00:00.000001Z")
        case "before":
            changed["before"] = RuleState("other", rules)
        case "after":
            changed["after"] = RuleState("chai", rules)
    assert transition_ack(**base) != transition_ack(**changed)
