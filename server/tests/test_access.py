"""Access control, tested by trying to get past it.

The browser's copy of these rules in ``app/js/00-core/15-access.js`` is an
affordance: it decides what to show. These tests exercise the copy that
decides what the server accepts, which is the one that matters, because a
caller with the API URL never runs the browser's.

Every test here asks the same question in a different way: can a request that
should be refused get through anyway?
"""

from __future__ import annotations

import pytest
from app.access import can_own, can_read, can_write, role_of, unclaimed
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, make_settings, requires_db

OWNER = TEST_EMAIL
WRITER = "writer@hospital.example"
READER = "reader@hospital.example"
STRANGER = "stranger@elsewhere.example"


def headers_for(email: str) -> dict[str, str]:
    return {"X-Forwarded-Email": email, "X-Forwarded-User": email.split("@")[0]}


def doc_with(owners=(), writers=(), readers=()) -> dict:
    return {
        "meta": {"solution": "Access test"},
        "access": {
            "owners": list(owners),
            "writers": list(writers),
            "readers": list(readers),
        },
    }


# --- the rules, without a database -----------------------------------------


class TestRules:
    def test_strongest_role_wins(self):
        doc = doc_with(owners=[OWNER], writers=[OWNER], readers=[OWNER])
        assert role_of(doc, OWNER) == "owner"

    def test_roles_are_distinct(self):
        doc = doc_with(owners=[OWNER], writers=[WRITER], readers=[READER])
        assert (role_of(doc, OWNER), role_of(doc, WRITER), role_of(doc, READER)) == (
            "owner",
            "writer",
            "reader",
        )
        assert role_of(doc, STRANGER) == ""

    def test_writer_cannot_own(self):
        doc = doc_with(owners=[OWNER], writers=[WRITER])
        assert can_write(doc, WRITER) and not can_own(doc, WRITER)

    def test_reader_cannot_write(self):
        doc = doc_with(owners=[OWNER], readers=[READER])
        assert can_read(doc, READER) and not can_write(doc, READER)

    def test_stranger_cannot_read(self):
        assert not can_read(doc_with(owners=[OWNER]), STRANGER)

    def test_project_without_owners_is_open(self):
        """Records predating access control must not lock their teams out."""
        doc = doc_with()
        assert unclaimed(doc)
        assert can_own(doc, STRANGER)

    def test_nothing_enforced_without_identity(self):
        """No identity means nothing to check against; say so, do not pretend."""
        doc = doc_with(owners=[OWNER])
        assert can_write(doc, STRANGER, enforced=False)


# --- the rules, against the real API ---------------------------------------


@requires_db
class TestEnforcement:
    async def _as(self, client: AsyncClient, email: str) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=client.app),
            base_url="http://api.test",
            headers=headers_for(email),
        )

    async def _make(self, client: AsyncClient, pid: str) -> None:
        r = await client.post(
            f"/api/projects/{pid}",
            json=doc_with(owners=[OWNER], writers=[WRITER], readers=[READER]),
        )
        assert r.status_code == 201

    async def test_creator_becomes_owner(self, client: AsyncClient):
        r = await client.post("/api/projects/pown", json={"meta": {"solution": "x"}})
        assert r.status_code == 201
        assert r.json()["access"]["owners"] == [OWNER]

    async def test_writer_may_patch(self, client: AsyncClient):
        await self._make(client, "pw")
        async with await self._as(client, WRITER) as w:
            r = await w.patch("/api/projects/pw", json={"meta": {"org": "Set"}})
        assert r.status_code == 200

    async def test_reader_may_not_patch(self, client: AsyncClient):
        await self._make(client, "pr")
        async with await self._as(client, READER) as r_:
            r = await r_.patch("/api/projects/pr", json={"meta": {"org": "No"}})
        assert r.status_code == 403

    async def test_stranger_gets_404_not_403(self, client: AsyncClient):
        """404 rather than 403: a 403 confirms the id exists."""
        await self._make(client, "ps")
        async with await self._as(client, STRANGER) as s:
            assert (
                await s.patch("/api/projects/ps", json={"meta": {}})
            ).status_code == 404

    async def test_writer_may_not_delete(self, client: AsyncClient):
        await self._make(client, "pd")
        async with await self._as(client, WRITER) as w:
            assert (await w.delete("/api/projects/pd")).status_code == 403
        assert (await client.delete("/api/projects/pd")).status_code == 204

    async def test_writer_may_not_grant_themselves_ownership(self, client: AsyncClient):
        """The escalation this whole file exists to prevent."""
        await self._make(client, "pesc")
        async with await self._as(client, WRITER) as w:
            r = await w.patch(
                "/api/projects/pesc",
                json={"access": {"owners": [WRITER], "writers": [], "readers": []}},
            )
        assert r.status_code == 403
        current = (await client.get("/api/projects")).json()
        doc = next(p for p in current if p["id"] == "pesc")
        assert doc["access"]["owners"] == [OWNER]

    async def test_last_owner_cannot_be_removed(self, client: AsyncClient):
        await self._make(client, "plast")
        r = await client.patch(
            "/api/projects/plast",
            json={"access": {"owners": [], "writers": [WRITER], "readers": []}},
        )
        assert r.status_code == 400
        assert "at least one owner" in r.json()["detail"]

    async def test_list_hides_projects_you_cannot_read(self, client: AsyncClient):
        await self._make(client, "phidden")
        async with await self._as(client, STRANGER) as s:
            assert (await s.get("/api/projects")).json() == []

    async def test_reader_may_not_append_to_the_log(self, client: AsyncClient):
        await self._make(client, "plog")
        async with await self._as(client, READER) as r_:
            r = await r_.post("/api/projects/plog/log", json={"text": "sneaking in"})
        assert r.status_code == 403

    async def test_stranger_may_not_read_the_log(self, client: AsyncClient):
        await self._make(client, "plog2")
        await client.post("/api/projects/plog2/log", json={"text": "private"})
        async with await self._as(client, STRANGER) as s:
            assert (await s.get("/api/projects/plog2/log")).status_code == 404

    async def test_unclaimed_project_stays_open(self, client: AsyncClient):
        """A record from before access control existed is editable by anyone.

        Written directly to the table on purpose. The API cannot create one:
        a new project gets its creator as owner, and the last owner cannot be
        removed. That is correct, and it means the only way to reach this state
        is to have been here before the feature -- which is exactly the
        situation this rule protects.
        """
        async with client.app.state.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO projects (id, doc) VALUES ($1, $2)",
                "plegacy",
                {"meta": {"solution": "created before access control"}},
            )
        async with await self._as(client, STRANGER) as s:
            assert (
                await s.patch("/api/projects/plegacy", json={"meta": {"org": "anyone"}})
            ).status_code == 200


@requires_db
class TestEnforcementDisabled:
    """With identity off there is nobody to check, and the API must not pretend."""

    @pytest.fixture
    async def open_client(self):
        settings = make_settings(require_identity=False)
        from app.main import create_app

        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with app.state.db.acquire() as conn:
                await conn.execute(
                    "TRUNCATE project_log, projects RESTART IDENTITY CASCADE"
                )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://api.test"
            ) as http:
                yield http

    async def test_anyone_may_write(self, open_client: AsyncClient):
        await open_client.post(
            "/api/projects/popen", json=doc_with(owners=["someone@else"])
        )
        r = await open_client.patch("/api/projects/popen", json={"meta": {"org": "x"}})
        assert r.status_code == 200
