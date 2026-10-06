"""Cross-site writes must be refused.

Identity here is a header the proxy adds based on ITS session -- a cookie in
three of the four documented deployment modes. A browser attaches that session
to a cross-site request as readily as to a same-site one, so without a check,
a page a signed-in user visits can delete their projects.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from .conftest import requires_db

WRITE_METHODS = ["POST", "PATCH", "DELETE"]


@requires_db
class TestCrossSiteWrites:
    async def test_a_cross_site_delete_is_refused(
        self, client: AsyncClient, project: str
    ):
        response = await client.delete(
            f"/api/projects/{project}", headers={"Sec-Fetch-Site": "cross-site"}
        )
        assert response.status_code == 403
        assert "cross-site" in response.json()["detail"].lower()
        # and the project is still there
        assert (await client.get(f"/api/projects/{project}/log")).status_code == 200

    @pytest.mark.parametrize("method", WRITE_METHODS)
    async def test_every_write_method_is_covered(
        self, client: AsyncClient, project: str, method: str
    ):
        response = await client.request(
            method,
            f"/api/projects/{project}",
            json={"meta": {"org": "x"}} if method != "DELETE" else None,
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 403

    async def test_the_log_endpoint_is_covered(self, client: AsyncClient, project: str):
        response = await client.post(
            f"/api/projects/{project}/log",
            json={"text": "forged"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 403

    async def test_purge_is_covered(self, client: AsyncClient, project: str):
        response = await client.delete(
            f"/api/projects/{project}/versions",
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert response.status_code == 403

    @pytest.mark.parametrize("site", ["same-origin", "none"])
    async def test_same_origin_and_direct_navigation_are_allowed(
        self, client: AsyncClient, project: str, site: str
    ):
        response = await client.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "Allowed"}},
            headers={"Sec-Fetch-Site": site},
        )
        assert response.status_code == 200

    async def test_same_site_is_refused_by_default(
        self, client: AsyncClient, project: str
    ):
        """A sibling subdomain is a different trust boundary."""
        response = await client.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "x"}},
            headers={"Sec-Fetch-Site": "same-site"},
        )
        assert response.status_code == 403

    async def test_a_request_without_the_header_is_allowed(
        self, client: AsyncClient, project: str
    ):
        """curl, health probes and integrations do not send it.

        Every browser that ships Sec-Fetch-Site sends it on every request, so
        an absent header is not what a cross-site attack looks like. Blocking
        it would break real callers to defend against nothing.
        """
        response = await client.patch(
            f"/api/projects/{project}", json={"meta": {"org": "CLI"}}
        )
        assert response.status_code == 200

    async def test_reads_are_never_blocked(self, client: AsyncClient, project: str):
        for path in (f"/api/projects/{project}/log", "/api/projects", "/api/health"):
            response = await client.get(path, headers={"Sec-Fetch-Site": "cross-site"})
            assert response.status_code == 200, path
