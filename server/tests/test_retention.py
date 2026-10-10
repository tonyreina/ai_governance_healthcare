"""Disposal at the end of the retention period, and litigation holds (#57).

R-54 set the periods and the owner granted the exception to R-10 that applying
them needs. What is tested here is the database's behavior, so it runs against a
real PostgreSQL: which records ``retention_due()`` says are past their period,
what ``dispose_due()`` destroys and what it leaves (a tombstone, R-12), that a
hold stops it, and that the read trail's trigger still refuses any DELETE the
policy does not allow, even from the table's owner.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path

import asyncpg
import pytest
from app.retention import SYSTEM_ACTOR, HoldAction
from httpx import AsyncClient

from .conftest import APP_ROLE_URL, owner_connection, requires_db

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


def retiring_decisions_sql(source: str) -> set[tuple[str, str]]:
    retired = source.split("retired AS (", 1)[1].split("gone AS (", 1)[0]
    where = retired.split("WHERE", 1)[1]
    return {
        (gate.upper(), decision)
        for gate, decision in re.findall(r"g\.(\w) ->> 'decision' = '(\w+)'", where)
    }


def test_retired_means_the_same_in_the_database_and_the_dashboard() -> None:
    definition = chai_definition()
    assert ending_classes(definition) == ENDING
    dashboard = retiring_decisions(definition)
    assert dashboard == {("A", "Stop"), ("B", "Stop"), ("C", "Stop"), ("D", "Retire")}
    assert retiring_decisions_sql(MIGRATION) == dashboard


def gate(definition: dict, gate_id: str) -> dict:
    return next(g for g in definition["gates"] if g["id"] == gate_id)


def test_the_rule_comparison_notices_a_difference() -> None:
    # Mutation: a new way to retire in the dashboard, or one dropped from the SQL.
    definition = chai_definition()
    gate(definition, "C")["options"].append({"value": "Withdraw", "class": "stop"})
    assert ("C", "Withdraw") in retiring_decisions(definition)
    assert retiring_decisions(definition) != retiring_decisions_sql(MIGRATION)
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
    sql = MIGRATION.replace("OR g.d ->> 'decision' = 'Retire'", "")
    assert ("D", "Retire") not in retiring_decisions_sql(sql)


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
