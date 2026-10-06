"""Version history: immutable snapshots with a content fingerprint.

The audit log records what someone meant to do. These record what the document
actually WAS, which is the question that matters when a decision is challenged
later and the log is ambiguous.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from .conftest import TEST_EMAIL, requires_db


@requires_db
class TestVersions:
    async def test_create_records_the_first_revision(self, client: AsyncClient):
        await client.post("/api/projects/pv1", json={"meta": {"solution": "One"}})
        versions = (await client.get("/api/projects/pv1/versions")).json()
        assert [v["rev"] for v in versions] == [1]
        assert versions[0]["by"]

    async def test_each_patch_adds_a_revision(self, client: AsyncClient):
        await client.post("/api/projects/pv2", json={"meta": {"solution": "Two"}})
        for org in ("A", "B", "C"):
            await client.patch("/api/projects/pv2", json={"meta": {"org": org}})
        versions = (await client.get("/api/projects/pv2/versions")).json()
        assert [v["rev"] for v in versions] == [4, 3, 2, 1]

    async def test_a_revision_is_the_document_as_it_was(self, client: AsyncClient):
        await client.post("/api/projects/pv3", json={"meta": {"solution": "Three"}})
        await client.patch("/api/projects/pv3", json={"meta": {"org": "Later"}})
        first = (await client.get("/api/projects/pv3/versions/1")).json()
        assert "org" not in first["doc"]["meta"]
        assert first["doc"]["meta"]["solution"] == "Three"

    async def test_fingerprint_is_stable_and_moves_with_content(
        self, client: AsyncClient
    ):
        await client.post("/api/projects/pv4", json={"meta": {"solution": "Four"}})
        # A patch that changes nothing substantive must not move the hash: only
        # updatedAt/updatedBy differ, and those are excluded by design.
        await client.patch(
            "/api/projects/pv4", json={"updatedAt": "2026-01-01T00:00:00Z"}
        )
        await client.patch("/api/projects/pv4", json={"meta": {"org": "Changed"}})
        versions = (await client.get("/api/projects/pv4/versions")).json()
        by_rev = {v["rev"]: v["md5"] for v in versions}
        assert by_rev[1] == by_rev[2], "a volatile-only change moved the fingerprint"
        assert by_rev[3] != by_rev[2], "a real change did not move the fingerprint"

    async def test_history_is_append_only(self, client: AsyncClient):
        """Enforced by a trigger, not by the absence of an endpoint."""
        import asyncpg

        await client.post("/api/projects/pv5", json={"meta": {"solution": "Five"}})
        async with client.app.state.db.acquire() as conn:
            with pytest.raises(asyncpg.RestrictViolationError):
                await conn.execute(
                    "UPDATE project_version SET content_md5 = 'x' WHERE project_id = $1",
                    "pv5",
                )
            with pytest.raises(asyncpg.RestrictViolationError):
                await conn.execute(
                    "DELETE FROM project_version WHERE project_id = $1", "pv5"
                )

    async def test_history_survives_deletion(self, client: AsyncClient):
        """ "It was deleted, and here is what it said" is the audit answer."""
        await client.post("/api/projects/pv6", json={"meta": {"solution": "Six"}})
        await client.patch("/api/projects/pv6", json={"meta": {"org": "Before"}})
        assert (await client.delete("/api/projects/pv6")).status_code == 204
        versions = (await client.get("/api/projects/pv6/versions")).json()
        assert [v["rev"] for v in versions] == [2, 1]
        assert (await client.get("/api/projects/pv6/versions/2")).json()["doc"]["meta"][
            "org"
        ] == "Before"

    async def test_missing_revision_is_404(self, client: AsyncClient):
        await client.post("/api/projects/pv7", json={"meta": {}})
        assert (await client.get("/api/projects/pv7/versions/99")).status_code == 404

    async def test_versions_respect_read_access(self, client: AsyncClient):
        from httpx import ASGITransport

        await client.post(
            "/api/projects/pv8",
            json={
                "meta": {"solution": "Eight"},
                "access": {"owners": ["owner@x"], "writers": [], "readers": []},
            },
        )
        async with AsyncClient(
            transport=ASGITransport(app=client.app),
            base_url="http://api.test",
            headers={"X-Forwarded-Email": "stranger@elsewhere"},
        ) as stranger:
            assert (await stranger.get("/api/projects/pv8/versions")).status_code == 404


@requires_db
class TestDeletedHistoryStaysRestricted:
    """Deleting a project must not widen access to its history.

    Before 003_version_access.sql the access check was skipped whenever there
    was no live project, so deleting a restricted record made every retained
    snapshot readable by anyone who could reach the API.
    """

    async def test_a_stranger_cannot_read_a_deleted_projects_history(
        self, client: AsyncClient
    ):
        from httpx import ASGITransport

        await client.post(
            "/api/projects/pvd1",
            json={
                "meta": {"solution": "Confidential"},
                "access": {"owners": [TEST_EMAIL], "writers": [], "readers": []},
            },
        )
        await client.patch("/api/projects/pvd1", json={"meta": {"org": "St Elsewhere"}})
        assert (await client.delete("/api/projects/pvd1")).status_code == 204

        async with AsyncClient(
            transport=ASGITransport(app=client.app),
            base_url="http://api.test",
            headers={"X-Forwarded-Email": "stranger@elsewhere"},
        ) as stranger:
            assert (
                await stranger.get("/api/projects/pvd1/versions")
            ).status_code == 404
            assert (
                await stranger.get("/api/projects/pvd1/versions/2")
            ).status_code == 404

    async def test_an_owner_can_still_read_a_deleted_projects_history(
        self, client: AsyncClient
    ):
        await client.post(
            "/api/projects/pvd2",
            json={
                "meta": {"solution": "Confidential"},
                "access": {"owners": [TEST_EMAIL], "writers": [], "readers": []},
            },
        )
        await client.patch("/api/projects/pvd2", json={"meta": {"org": "Before"}})
        await client.delete("/api/projects/pvd2")

        versions = (await client.get("/api/projects/pvd2/versions")).json()
        assert [v["rev"] for v in versions] == [2, 1]
        body = (await client.get("/api/projects/pvd2/versions/2")).json()
        assert body["doc"]["meta"]["org"] == "Before"

    async def test_a_reader_keeps_read_access_after_deletion(self, client: AsyncClient):
        from httpx import ASGITransport

        await client.post(
            "/api/projects/pvd3",
            json={
                "meta": {"solution": "Shared"},
                "access": {
                    "owners": [TEST_EMAIL],
                    "writers": [],
                    "readers": ["reader@x"],
                },
            },
        )
        await client.delete("/api/projects/pvd3")
        async with AsyncClient(
            transport=ASGITransport(app=client.app),
            base_url="http://api.test",
            headers={"X-Forwarded-Email": "reader@x"},
        ) as reader:
            assert (await reader.get("/api/projects/pvd3/versions")).status_code == 200

    async def test_history_for_an_unknown_project_is_404(self, client: AsyncClient):
        assert (await client.get("/api/projects/pvnope/versions")).status_code == 404


@requires_db
class TestPurge:
    """The disposal path: content destroyed, the tombstone kept."""

    async def test_an_owner_can_purge_and_the_tombstone_survives(
        self, client: AsyncClient
    ):
        await client.post(
            "/api/projects/pvp1",
            json={"meta": {"solution": "Oops"}, "items": {"s1-1": {"evidence": "MRN"}}},
        )
        await client.patch("/api/projects/pvp1", json={"meta": {"org": "Also oops"}})

        before = (await client.get("/api/projects/pvp1/versions/2")).json()
        original_md5 = before["md5"]
        assert before["purged"] is False

        assert (await client.delete("/api/projects/pvp1/versions")).status_code == 204

        listing = (await client.get("/api/projects/pvp1/versions")).json()
        assert [v["rev"] for v in listing] == [2, 1]
        assert all(v["purged"] for v in listing)
        assert all(v["purgedBy"] == TEST_EMAIL for v in listing)

        after = (await client.get("/api/projects/pvp1/versions/2")).json()
        assert after["doc"] == {}, "content must be gone"
        assert after["purged"] is True
        assert after["by"] == TEST_EMAIL, "author survives"
        assert after["md5"] == original_md5, "the original fingerprint survives"

    async def test_a_writer_cannot_purge(self, client: AsyncClient):
        from httpx import ASGITransport

        await client.post(
            "/api/projects/pvp2",
            json={
                "meta": {"solution": "Guarded"},
                "access": {
                    "owners": [TEST_EMAIL],
                    "writers": ["writer@x"],
                    "readers": [],
                },
            },
        )
        async with AsyncClient(
            transport=ASGITransport(app=client.app),
            base_url="http://api.test",
            headers={"X-Forwarded-Email": "writer@x"},
        ) as writer:
            assert (
                await writer.delete("/api/projects/pvp2/versions")
            ).status_code == 403

    async def test_a_stranger_cannot_purge(self, client: AsyncClient):
        from httpx import ASGITransport

        await client.post(
            "/api/projects/pvp3",
            json={
                "meta": {"solution": "Guarded"},
                "access": {"owners": [TEST_EMAIL], "writers": [], "readers": []},
            },
        )
        async with AsyncClient(
            transport=ASGITransport(app=client.app),
            base_url="http://api.test",
            headers={"X-Forwarded-Email": "stranger@elsewhere"},
        ) as stranger:
            assert (
                await stranger.delete("/api/projects/pvp3/versions")
            ).status_code == 404

    async def test_a_deleted_projects_history_can_still_be_purged(
        self, client: AsyncClient
    ):
        """The record most likely to need purging is the one already deleted."""
        await client.post("/api/projects/pvp4", json={"meta": {"solution": "Gone"}})
        await client.delete("/api/projects/pvp4")
        assert (await client.delete("/api/projects/pvp4/versions")).status_code == 204
        body = (await client.get("/api/projects/pvp4/versions/1")).json()
        assert body["doc"] == {} and body["purged"] is True

    async def test_history_cannot_be_rewritten_by_hand(self, client: AsyncClient):
        """The trigger permits a purge and nothing else."""
        import asyncpg
        import pytest

        await client.post("/api/projects/pvp5", json={"meta": {"solution": "Fixed"}})
        async with client.app.state.db.acquire() as conn:
            with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                await conn.execute(
                    "UPDATE project_version SET doc = '{\"meta\":{}}'::jsonb "
                    "WHERE project_id = 'pvp5'"
                )
            with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                await conn.execute(
                    "DELETE FROM project_version WHERE project_id = 'pvp5'"
                )
            with pytest.raises(asyncpg.exceptions.RestrictViolationError):
                # A purge that keeps the content is not a purge.
                await conn.execute(
                    "UPDATE project_version SET purged_at = now() "
                    "WHERE project_id = 'pvp5'"
                )
