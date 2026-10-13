"""Cross-site writes must be refused.

Identity here is a header the proxy adds based on ITS session -- a cookie in
three of the four documented deployment modes. A browser attaches that session
to a cross-site request as readily as to a same-site one, so without a check,
a page a signed-in user visits can delete their projects.
"""

from __future__ import annotations

import pytest
from app.main import create_app
from httpx import AsyncClient

from .conftest import bare_client, make_settings, requires_db

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

    async def test_reads_without_the_header_are_not_blocked(
        self, client: AsyncClient, project: str
    ):
        """Health probes and every GET carry no Sec-Fetch-Site and no Origin."""
        for path in (f"/api/projects/{project}/log", "/api/projects", "/api/health"):
            assert (await client.get(path)).status_code == 200, path

    async def test_reads_are_never_blocked(self, client: AsyncClient, project: str):
        for path in (f"/api/projects/{project}/log", "/api/projects", "/api/health"):
            response = await client.get(path, headers={"Sec-Fetch-Site": "cross-site"})
            assert response.status_code == 200, path


@pytest.fixture
def curl(client: AsyncClient) -> AsyncClient:
    """The same app, reached the way curl does: no Origin, no Sec-Fetch-Site."""
    return bare_client(client.app)  # type: ignore[attr-defined]


@requires_db
class TestWritesWithoutSecFetchSite:
    """D-102: an absent ``Sec-Fetch-Site`` is no longer a pass.

    A browser that does not send it (an old one, or one behind something that
    strips it) is exactly the client the header cannot protect, so the request
    must show a same-site ``Origin`` instead. A bearer token on an agent path is
    the other way in: a page cannot attach one, and it is not a cookie.
    """

    async def test_a_write_with_no_header_and_no_origin_is_refused(
        self, curl: AsyncClient, project: str
    ):
        response = await curl.patch(
            f"/api/projects/{project}", json={"meta": {"org": "CLI"}}
        )
        assert response.status_code == 403
        assert "origin" in response.json()["detail"].lower()

    @pytest.mark.parametrize("method", WRITE_METHODS)
    async def test_every_write_method_is_covered(
        self, curl: AsyncClient, project: str, method: str
    ):
        response = await curl.request(
            method,
            f"/api/projects/{project}",
            json={"meta": {"org": "x"}} if method != "DELETE" else None,
        )
        assert response.status_code == 403
        assert (await curl.get(f"/api/projects/{project}/log")).status_code == 200

    async def test_a_matching_origin_is_allowed(self, curl: AsyncClient, project: str):
        response = await curl.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "Same"}},
            headers={"Origin": "http://api.test"},
        )
        assert response.status_code == 200

    async def test_the_origin_match_ignores_case_and_scheme_default_port(
        self, curl: AsyncClient, project: str
    ):
        response = await curl.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "Same"}},
            headers={"Origin": "HTTP://API.TEST:80"},
        )
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.example",
            "http://api.test.evil.example",
            "http://evil.example/api.test",
            "http://api.test:8080",
            "null",
            "",
            "not a url",
            "http://api.test@evil.example",
        ],
    )
    async def test_any_other_origin_is_refused(
        self, curl: AsyncClient, project: str, origin: str
    ):
        response = await curl.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "x"}},
            headers={"Origin": origin},
        )
        assert response.status_code == 403

    async def test_a_forwarded_host_is_not_believed(
        self, curl: AsyncClient, project: str
    ):
        """The client chooses X-Forwarded-Host; this repository never trusts it."""
        response = await curl.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "x"}},
            headers={
                "Origin": "https://evil.example",
                "X-Forwarded-Host": "evil.example",
                "X-Forwarded-Proto": "https",
            },
        )
        assert response.status_code == 403

    async def test_the_header_still_decides_when_it_is_present(
        self, curl: AsyncClient, project: str
    ):
        """A browser that sends it is judged by it, whatever Origin says."""
        response = await curl.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "x"}},
            headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://api.test"},
        )
        assert response.status_code == 403

    async def test_a_configured_cors_origin_counts_as_ours(self):
        app = create_app(make_settings(cors_origins=["https://app.example"]))
        async with app.router.lifespan_context(app):
            async with bare_client(app) as http:
                response = await http.post(
                    "/api/projects/p-cors",
                    json={"meta": {"org": "x"}},
                    headers={"Origin": "https://app.example"},
                )
                other = await http.post(
                    "/api/projects/p-cors2",
                    json={"meta": {"org": "x"}},
                    headers={"Origin": "https://other.example"},
                )
        assert response.status_code in (200, 201)
        assert other.status_code == 403

    async def test_a_session_cannot_mint_a_token_without_an_origin(
        self, curl: AsyncClient
    ):
        """Token management answers to a session, so a bearer header is no pass."""
        response = await curl.post(
            "/api/agent-tokens",
            json={"label": "x"},
            headers={"Authorization": f"Bearer agt_{'a' * 16}.{'A' * 43}"},
        )
        assert response.status_code == 403

    async def test_a_bearer_token_on_a_session_route_is_not_a_pass(
        self, curl: AsyncClient, project: str
    ):
        response = await curl.patch(
            f"/api/projects/{project}",
            json={"meta": {"org": "x"}},
            headers={"Authorization": f"Bearer agt_{'a' * 16}.{'A' * 43}"},
        )
        assert response.status_code == 403

    async def test_a_bearer_request_on_an_agent_path_reaches_the_route(
        self, curl: AsyncClient
    ):
        """The middleware lets it through; the route then refuses a bad token with
        its own 401, not the 403 of this check."""
        response = await curl.post(
            "/api/agent/projects",
            headers={"Authorization": f"Bearer agt_{'a' * 16}.{'A' * 43}"},
        )
        assert response.status_code != 403

    async def test_a_malformed_bearer_on_an_agent_path_is_refused(
        self, curl: AsyncClient
    ):
        for header in ("Bearer", "Bearer nonsense", "Basic abc", ""):
            response = await curl.post(
                "/api/agent/projects", headers={"Authorization": header}
            )
            assert response.status_code == 403, header
