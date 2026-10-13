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

from .conftest import TEST_EMAIL, make_settings, requires_db, reset_database

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

    def test_project_without_owners_is_refused_to_everyone(self):
        """R-75: no owner means no access, not open access."""
        for doc in (doc_with(), doc_with(writers=[WRITER], readers=[READER]), {}):
            assert unclaimed(doc)
            for who in (STRANGER, WRITER, READER, OWNER, None):
                assert not can_read(doc, who), (doc, who)
                assert not can_write(doc, who), (doc, who)
                assert not can_own(doc, who), (doc, who)
                assert role_of(doc, who) == ""

    def test_a_blank_owner_is_not_an_owner(self):
        doc = doc_with(owners=["", "  "])
        assert unclaimed(doc)
        assert not can_read(doc, "")

    def test_emergency_access_still_reaches_an_ownerless_project(self):
        doc = doc_with()
        assert can_read(doc, STRANGER, emergency=True)
        assert can_write(doc, STRANGER, emergency=True)
        assert can_own(doc, STRANGER, emergency=True)

    def test_identity_disabled_is_unchanged(self):
        """Hole 2 of the module docs stays: nobody to check a list against."""
        assert can_own(doc_with(), STRANGER, enforced=False)

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

    async def test_creator_stays_an_owner_when_naming_someone_else(
        self, client: AsyncClient
    ):
        """A create naming only a colleague as owner must not hand the record away (#44).

        The client's ``owners`` used to be kept verbatim, so any authenticated
        user could create a record owned by somebody else and absent from every
        list themselves: a record attributed to a colleague who never made it,
        or, with a mistyped address, one nobody could open.
        """
        r = await client.post(
            "/api/projects/pplant",
            json={"access": {"owners": ["colleague@x"], "writers": [], "readers": []}},
        )
        assert r.status_code == 201
        assert OWNER in r.json()["access"]["owners"]
        assert "colleague@x" in r.json()["access"]["owners"]
        listed = (await client.get("/api/projects")).json()
        assert "pplant" in [p["id"] for p in listed]

    async def test_a_mistyped_owner_cannot_orphan_a_new_project(
        self, client: AsyncClient
    ):
        r = await client.post(
            "/api/projects/ptypo", json={"access": {"owners": ["typo@hospitl.org"]}}
        )
        assert r.status_code == 201
        listed = (await client.get("/api/projects")).json()
        assert "ptypo" in [p["id"] for p in listed]
        # and the creator can still change the access list to fix the typo
        fixed = await client.patch(
            "/api/projects/ptypo",
            json={"access": {"owners": [OWNER, "right@hospital.org"]}},
        )
        assert fixed.status_code == 200

    async def test_create_and_share_still_works(self, client: AsyncClient):
        r = await client.post(
            "/api/projects/pshare",
            json=doc_with(owners=[OWNER, "co@x"], writers=[WRITER], readers=[READER]),
        )
        access = r.json()["access"]
        assert access["owners"] == [OWNER, "co@x"]
        assert access["writers"] == [WRITER]
        assert access["readers"] == [READER]

    async def test_the_creator_is_listed_once(self, client: AsyncClient):
        r = await client.post(
            "/api/projects/ponce", json=doc_with(owners=[OWNER, OWNER])
        )
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

    async def _ownerless(self, client: AsyncClient, pid: str, **lists) -> None:
        """Written straight to the table: the API cannot create one (R-75).

        This is the state of a record from before access control, or of a
        database restored from a dump that had one. Nothing migrates it.
        """
        async with client.app.state.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO projects (id, doc) VALUES ($1, $2)",
                pid,
                {"meta": {"solution": "no owner"}, "access": lists},
            )

    async def test_ownerless_project_is_refused_to_everyone(self, client: AsyncClient):
        """R-75: not open, not claimable. 404 to everyone, the creator included."""
        await self._ownerless(client, "pnoowner", writers=[WRITER])
        for who in (STRANGER, WRITER, OWNER):
            async with await self._as(client, who) as c:
                assert (await c.get("/api/projects")).json() == []
                r = await c.patch("/api/projects/pnoowner", json={"meta": {"org": "x"}})
                assert r.status_code == 404, who
                assert (
                    await c.patch(
                        "/api/projects/pnoowner",
                        json={"access": {"owners": [who]}},
                    )
                ).status_code == 404, "no one can claim it"
                assert (await c.delete("/api/projects/pnoowner")).status_code == 404
                assert (
                    await c.get("/api/projects/pnoowner/versions")
                ).status_code == 404

    async def test_an_owner_cannot_blank_the_owner_list(self, client: AsyncClient):
        await self._make(client, "pblank")
        for owners in ([""], ["  "], [], "ann@x", None):
            r = await client.patch(
                "/api/projects/pblank", json={"access": {"owners": owners}}
            )
            assert r.status_code == 400, owners
        r = await client.patch("/api/projects/pblank", json={"access": None})
        assert r.status_code == 400

    async def test_creating_never_leaves_a_project_ownerless(self, client: AsyncClient):
        for n, access in enumerate(
            ({"owners": []}, {"owners": [""]}, None, "x", {"writers": [WRITER]})
        ):
            r = await client.post(
                f"/api/projects/pcreate{n}",
                json={"meta": {"solution": "x"}, "access": access},
            )
            assert r.status_code == 201, access
            assert OWNER in r.json()["access"]["owners"], access


@requires_db
class TestEnforcementDisabled:
    """With identity off there is nobody to check, and the API must not pretend."""

    @pytest.fixture
    async def open_client(self):
        settings = make_settings(require_identity=False)
        from app.main import create_app

        app = create_app(settings)
        async with app.router.lifespan_context(app):
            await reset_database()
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


@requires_db
class TestArchiveIsOwnerOnly:
    """The browser says owner-only; the server must agree.

    15-access.js gates archive on canOwn(), but the server saw
    `{"archived": true}` as an ordinary field in a deep-merge patch and
    accepted it from any writer. A rule enforced only in the browser is a
    label, not a control.
    """

    async def _project(self, client: AsyncClient, pid: str) -> None:
        response = await client.post(
            f"/api/projects/{pid}",
            json={
                "meta": {"solution": "Guarded"},
                "archived": False,
                "access": {
                    "owners": [TEST_EMAIL],
                    "writers": ["writer@x"],
                    "readers": ["reader@x"],
                },
            },
        )
        assert response.status_code == 201

    def _as(self, client: AsyncClient, email: str) -> AsyncClient:
        from httpx import ASGITransport

        return AsyncClient(
            transport=ASGITransport(app=client.app),
            base_url="http://api.test",
            headers={"X-Forwarded-Email": email},
        )

    async def test_a_writer_cannot_archive(self, client: AsyncClient):
        await self._project(client, "pa1")
        async with self._as(client, "writer@x") as writer:
            response = await writer.patch("/api/projects/pa1", json={"archived": True})
        assert response.status_code == 403
        assert "owner" in response.json()["detail"].lower()
        live = (await client.get("/api/projects")).json()
        assert next(p for p in live if p["id"] == "pa1")["archived"] is False

    async def test_a_writer_cannot_restore(self, client: AsyncClient):
        await self._project(client, "pa2")
        assert (
            await client.patch("/api/projects/pa2", json={"archived": True})
        ).status_code == 200
        async with self._as(client, "writer@x") as writer:
            response = await writer.patch("/api/projects/pa2", json={"archived": False})
        assert response.status_code == 403

    async def test_an_owner_can_archive(self, client: AsyncClient):
        await self._project(client, "pa3")
        response = await client.patch("/api/projects/pa3", json={"archived": True})
        assert response.status_code == 200
        assert response.json()["archived"] is True

    async def test_a_writer_can_still_edit_everything_else(self, client: AsyncClient):
        await self._project(client, "pa4")
        async with self._as(client, "writer@x") as writer:
            response = await writer.patch(
                "/api/projects/pa4",
                json={"items": {"s4-1": {"status": "met"}}},
            )
        assert response.status_code == 200

    async def test_a_no_op_archived_field_is_not_a_403(self, client: AsyncClient):
        """The browser re-sends unchanged fields alongside real edits.

        Failing those would turn an ordinary save into a permission error.
        """
        await self._project(client, "pa5")
        async with self._as(client, "writer@x") as writer:
            response = await writer.patch(
                "/api/projects/pa5",
                json={"archived": False, "meta": {"org": "St Elsewhere"}},
            )
        assert response.status_code == 200
        assert response.json()["meta"]["org"] == "St Elsewhere"
