"""Version history: immutable snapshots with a content fingerprint.

The audit log records what someone meant to do. These record what the document
actually WAS, which is the question that matters when a decision is challenged
later and the log is ambiguous.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from .conftest import requires_db


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
