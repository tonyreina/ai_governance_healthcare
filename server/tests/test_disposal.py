"""Deleting and destroying data (#36).

Three things were wrong, and they compound:

1. `DELETE /api/projects/{id}` removes the live record but every revision's full
   document survives in `project_version`, while the docs said it deleted the
   project and its log. Someone answering an erasure request by calling it would
   believe the data was gone.
2. The purge path emptied `project_version.doc` and left the same values in
   `project_log`. The client writes a log entry's PROSE with the values in it
   ("Changed evidence: “old” → “new”") as well as `change.from` and `change.to`,
   so a patient identifier pasted into an evidence field was readable in two more
   places after a purge reported success.
3. Deletion left no durable record. The only trace was a line on container stdout.

So: a purge now redacts the audit log in the same transaction, by whitelist (the
log accepts arbitrary extra fields from the client, any of which could hold the
value); a deletion writes an append-only tombstone; and neither can be forged,
because "already purged" and "system entry" are columns only the server sets, not
keys a client could put in its own entry.
"""

from __future__ import annotations

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, requires_db

SECRET = "MRN-00123456"
REDACTED = "[content purged]"


def headers_for(email: str) -> dict[str, str]:
    return {"X-Forwarded-Email": email, "X-Forwarded-User": email.split("@")[0]}


def acting_as(client: AsyncClient, email: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers=headers_for(email),
    )


async def make_leaky_project(client: AsyncClient, pid: str) -> None:
    """A project whose evidence field had a patient identifier pasted into it."""
    r = await client.post(
        f"/api/projects/{pid}",
        json={"meta": {"solution": "Triage"}, "items": {"s1-1": {"evidence": SECRET}}},
    )
    assert r.status_code == 201, r.text
    # Exactly what the browser writes for an edit: prose WITH the values, the values
    # again in `change`, a fingerprint, and a field the server does not own.
    r = await client.post(
        f"/api/projects/{pid}/log",
        json={
            "text": f"Changed evidence of criterion 1: “” → “{SECRET}”",
            "change": {"path": "items.s1-1.evidence", "from": None, "to": SECRET},
            "hash": "d41d8cd98f00b204e9800998ecf8427e",
            "scratch": f"client-side note about {SECRET}",
        },
    )
    assert r.status_code == 201, r.text


async def where_the_secret_is(client: AsyncClient) -> dict[str, int]:
    async with client.app.state.db.acquire() as conn:
        return {
            "project_log": await conn.fetchval(
                "SELECT count(*) FROM project_log WHERE entry::text LIKE $1",
                f"%{SECRET}%",
            ),
            "project_version": await conn.fetchval(
                "SELECT count(*) FROM project_version WHERE doc::text LIKE $1",
                f"%{SECRET}%",
            ),
            "projects": await conn.fetchval(
                "SELECT count(*) FROM projects WHERE doc::text LIKE $1", f"%{SECRET}%"
            ),
        }


# --- a purge reaches the audit log ------------------------------------------


@requires_db
class TestAPurgeReachesTheAuditLog:
    async def test_the_value_is_gone_from_the_history_and_the_log(
        self, client: AsyncClient
    ):
        await make_leaky_project(client, "d1")
        before = await where_the_secret_is(client)
        assert before["project_log"] == 1 and before["project_version"] >= 1

        assert (await client.delete("/api/projects/d1/versions")).status_code == 204

        after = await where_the_secret_is(client)
        assert after["project_version"] == 0, "the history still holds it"
        assert after["project_log"] == 0, "the audit log still holds it"

    async def test_the_prose_is_redacted_not_just_the_structured_values(
        self, client: AsyncClient
    ):
        """`text` carries the values too: the issue named only change.from/to."""
        await make_leaky_project(client, "d2")
        await client.delete("/api/projects/d2/versions")
        entries = (await client.get("/api/projects/d2/log")).json()
        redacted = next(e for e in entries if e["text"] == REDACTED)
        assert SECRET not in str(redacted)

    async def test_who_what_and_when_survive(self, client: AsyncClient):
        """A tombstone, not a gap: the entry stays, so an auditor can see that
        something was changed here, by whom, when, and which field."""
        await make_leaky_project(client, "d3")
        original = (await client.get("/api/projects/d3/log")).json()[0]
        await client.delete("/api/projects/d3/versions")
        redacted = next(
            e
            for e in (await client.get("/api/projects/d3/log")).json()
            if e["text"] == REDACTED
        )
        assert redacted["at"] == original["at"]
        assert redacted["by"] == original["by"] == TEST_EMAIL
        assert redacted["change"] == {"path": "items.s1-1.evidence"}
        assert redacted["hash"] == original["hash"]
        assert redacted["purged"] is True, "the reader is told it was redacted"

    async def test_a_field_the_server_does_not_own_is_gone_too(
        self, client: AsyncClient
    ):
        """Redaction is a whitelist. The log keeps arbitrary client fields, any of
        which could hold the value; a blacklist of known ones would miss them."""
        await make_leaky_project(client, "d4")
        await client.delete("/api/projects/d4/versions")
        entries = (await client.get("/api/projects/d4/log")).json()
        assert not any("scratch" in e for e in entries)

    async def test_the_purge_itself_is_recorded_in_the_log(self, client: AsyncClient):
        await make_leaky_project(client, "d5")
        await client.delete("/api/projects/d5/versions")
        entries = (await client.get("/api/projects/d5/log")).json()
        record = next(
            e
            for e in entries
            if "purged" in e["text"].lower() and e["text"] != REDACTED
        )
        assert record["by"] == TEST_EMAIL
        assert SECRET not in str(record)

    async def test_the_record_of_a_purge_survives_the_next_purge(
        self, client: AsyncClient
    ):
        await make_leaky_project(client, "d6")
        await client.delete("/api/projects/d6/versions")
        first = [e["text"] for e in (await client.get("/api/projects/d6/log")).json()]
        await client.delete("/api/projects/d6/versions")
        second = [e["text"] for e in (await client.get("/api/projects/d6/log")).json()]
        record = next(t for t in first if t != REDACTED)
        assert record in second, "the system entry was itself redacted"

    async def test_purging_twice_is_harmless(self, client: AsyncClient):
        await make_leaky_project(client, "d7")
        assert (await client.delete("/api/projects/d7/versions")).status_code == 204
        assert (await client.delete("/api/projects/d7/versions")).status_code == 204

    async def test_a_client_cannot_exempt_its_own_entry_from_redaction(
        self, client: AsyncClient
    ):
        """If "already purged" were a key inside the entry, a client could send it
        and make an entry carrying the value survive every purge."""
        await client.post("/api/projects/d8", json={"meta": {"solution": "Forge"}})
        for forged in (
            {"purged": True},
            {"system": True},
            {"purged": True, "system": "purge"},
        ):
            await client.post(
                "/api/projects/d8/log",
                json={"text": f"note {SECRET}", "change": {"to": SECRET}, **forged},
            )
        await client.delete("/api/projects/d8/versions")
        assert (await where_the_secret_is(client))["project_log"] == 0

    async def test_a_refused_purge_leaves_the_log_alone(self, client: AsyncClient):
        await client.post(
            "/api/projects/d9",
            json={
                "meta": {"solution": "Guarded"},
                "access": {"owners": [TEST_EMAIL], "writers": ["w@x"], "readers": []},
            },
        )
        await client.post("/api/projects/d9/log", json={"text": f"keep {SECRET}"})
        async with acting_as(client, "w@x") as writer:
            assert (await writer.delete("/api/projects/d9/versions")).status_code == 403
        assert (await where_the_secret_is(client))["project_log"] == 1

    async def test_purging_one_project_leaves_another_alone(self, client: AsyncClient):
        await make_leaky_project(client, "d10a")
        await make_leaky_project(client, "d10b")
        await client.delete("/api/projects/d10a/versions")
        entries = (await client.get("/api/projects/d10b/log")).json()
        assert any(SECRET in e["text"] for e in entries), (
            "the other project was redacted"
        )

    async def test_purging_the_history_of_a_deleted_project_is_still_fine(
        self, client: AsyncClient
    ):
        await make_leaky_project(client, "d11")
        await client.delete("/api/projects/d11")
        assert (await client.delete("/api/projects/d11/versions")).status_code == 204
        assert (await where_the_secret_is(client))["project_version"] == 0


@requires_db
class TestTheDatabaseAllowsARedactionAndNothingElse:
    async def _rows(self, client: AsyncClient, pid: str) -> list[asyncpg.Record]:
        async with client.app.state.db.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM project_log WHERE project_id = $1", pid
            )

    async def test_the_redaction_function_keeps_only_what_it_should(
        self, client: AsyncClient
    ):
        async with client.app.state.db.acquire() as conn:
            out = await conn.fetchval(
                """SELECT project_log_redacted('{"text":"x","at":"A","by":"B",
                   "hash":"H","change":{"path":"p","from":1,"to":2},"other":"o"}'::jsonb)::text"""
            )
        import json

        assert json.loads(out) == {
            "text": REDACTED,
            "at": "A",
            "by": "B",
            "hash": "H",
            "change": {"path": "p"},
        }

    async def test_an_arbitrary_update_is_refused(self, client: AsyncClient):
        await make_leaky_project(client, "t1")
        async with client.app.state.db.acquire() as conn:
            with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                await conn.execute(
                    'UPDATE project_log SET entry = \'{"text":"tampered"}\'::jsonb '
                    "WHERE project_id = 't1'"
                )

    async def test_a_partial_redaction_is_refused(self, client: AsyncClient):
        """Redacting the prose but leaving change.to would pass for a purge."""
        await make_leaky_project(client, "t2")
        async with client.app.state.db.acquire() as conn:
            with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                await conn.execute(
                    "UPDATE project_log SET purged_at = now(), "
                    "entry = jsonb_set(entry, '{text}', '\"[content purged]\"') "
                    "WHERE project_id = 't2'"
                )

    async def test_changing_when_or_who_is_refused(self, client: AsyncClient):
        await make_leaky_project(client, "t3")
        async with client.app.state.db.acquire() as conn:
            for change in ("at = at + interval '1 day'", "by_id = 'someone-else'"):
                with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                    await conn.execute(
                        f"UPDATE project_log SET purged_at = now(), {change}, "
                        "entry = project_log_redacted(entry) WHERE project_id = 't3'"
                    )

    async def test_an_exact_redaction_is_permitted_once(self, client: AsyncClient):
        await make_leaky_project(client, "t4")
        async with client.app.state.db.acquire() as conn:
            await conn.execute(
                "UPDATE project_log SET purged_at = now(), "
                "entry = project_log_redacted(entry) WHERE project_id = 't4'"
            )
            with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                await conn.execute(
                    "UPDATE project_log SET purged_at = NULL WHERE project_id = 't4'"
                )

    async def test_a_system_entry_cannot_be_redacted_or_edited(
        self, client: AsyncClient
    ):
        await make_leaky_project(client, "t5")
        await client.delete("/api/projects/t5/versions")
        async with client.app.state.db.acquire() as conn:
            with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                await conn.execute(
                    "UPDATE project_log SET entry = project_log_redacted(entry), "
                    "purged_at = now() WHERE project_id = 't5' AND is_system"
                )


# --- deletion leaves a durable record ----------------------------------------


@requires_db
class TestDeletionLeavesATombstone:
    async def _tombstones(self, client: AsyncClient, pid: str) -> list[asyncpg.Record]:
        async with client.app.state.db.acquire() as conn:
            return await conn.fetch(
                "SELECT * FROM project_deletion WHERE project_id = $1 ORDER BY deleted_at",
                pid,
            )

    async def test_a_delete_records_who_when_and_what_it_hashed_to(
        self, client: AsyncClient
    ):
        await client.post("/api/projects/x1", json={"meta": {"solution": "Gone"}})
        await client.patch("/api/projects/x1", json={"meta": {"org": "Org"}})
        last = (await client.get("/api/projects/x1/versions/2")).json()
        async with client.app.state.db.acquire() as conn:
            incarnation = await conn.fetchval(
                "SELECT incarnation FROM projects WHERE id = 'x1'"
            )

        assert (await client.delete("/api/projects/x1")).status_code == 204

        (row,) = await self._tombstones(client, "x1")
        assert row["deleted_by"] == TEST_EMAIL
        assert row["last_rev"] == 2
        assert row["last_md5"] == last["md5"]
        assert row["incarnation"] == incarnation
        assert row["deleted_at"] is not None

    async def test_it_survives_a_purge_of_the_history(self, client: AsyncClient):
        await client.post("/api/projects/x2", json={"meta": {"solution": "Gone"}})
        await client.delete("/api/projects/x2")
        await client.delete("/api/projects/x2/versions")
        assert len(await self._tombstones(client, "x2")) == 1

    async def test_it_cannot_be_changed_or_removed_by_hand(self, client: AsyncClient):
        await client.post("/api/projects/x3", json={"meta": {"solution": "Gone"}})
        await client.delete("/api/projects/x3")
        async with client.app.state.db.acquire() as conn:
            for statement in (
                "UPDATE project_deletion SET deleted_by = 'someone-else' WHERE project_id = 'x3'",
                "DELETE FROM project_deletion WHERE project_id = 'x3'",
            ):
                with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                    await conn.execute(statement)

    async def test_a_refused_delete_writes_nothing(self, client: AsyncClient):
        await client.post(
            "/api/projects/x4",
            json={
                "meta": {"solution": "Guarded"},
                "access": {"owners": [TEST_EMAIL], "writers": ["w@x"], "readers": []},
            },
        )
        async with acting_as(client, "w@x") as writer:
            assert (await writer.delete("/api/projects/x4")).status_code == 403
        assert await self._tombstones(client, "x4") == []

    async def test_deleting_something_that_is_not_there_writes_nothing(
        self, client: AsyncClient
    ):
        assert (await client.delete("/api/projects/never-existed")).status_code == 404
        assert await self._tombstones(client, "never-existed") == []

    async def test_a_reused_id_gets_a_tombstone_per_incarnation(
        self, client: AsyncClient
    ):
        await client.post("/api/projects/x5", json={"meta": {"solution": "First"}})
        await client.delete("/api/projects/x5")
        await client.post("/api/projects/x5", json={"meta": {"solution": "Second"}})
        await client.delete("/api/projects/x5")
        rows = await self._tombstones(client, "x5")
        assert len(rows) == 2
        assert rows[0]["incarnation"] != rows[1]["incarnation"]

    async def test_the_log_still_goes_with_the_project(self, client: AsyncClient):
        """Deletion removes the live log (by design, D-10). It is the tombstone,
        not the log, that says the project existed."""
        await make_leaky_project(client, "x6")
        await client.delete("/api/projects/x6")
        assert (await client.get("/api/projects/x6/log")).json() == []
        assert len(await self._tombstones(client, "x6")) == 1
