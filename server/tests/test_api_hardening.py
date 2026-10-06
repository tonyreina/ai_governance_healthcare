"""API transport hardening middleware."""

from __future__ import annotations

from app.main import create_app
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_HEADERS, make_settings


async def test_api_responses_get_security_headers() -> None:
    app = create_app(make_settings(rate_limit_max_requests=1000))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://api.test"
    ) as client:
        response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in response.headers


async def test_hsts_is_set_when_forwarded_proto_is_https() -> None:
    app = create_app(make_settings(rate_limit_max_requests=1000))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://api.test"
    ) as client:
        response = await client.get(
            "/api/does-not-exist", headers={"X-Forwarded-Proto": "https"}
        )

    assert response.status_code == 404
    assert "max-age=" in response.headers["strict-transport-security"]


async def test_rate_limit_blocks_burst_requests() -> None:
    app = create_app(
        make_settings(rate_limit_window_seconds=60, rate_limit_max_requests=1)
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://api.test",
        headers=TEST_HEADERS,
    ) as client:
        first = await client.get("/api/does-not-exist")
        second = await client.get("/api/does-not-exist")

    assert first.status_code == 404
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


async def test_body_limit_rejects_large_payloads() -> None:
    app = create_app(
        make_settings(
            request_body_limit_bytes=10,
            rate_limit_window_seconds=60,
            rate_limit_max_requests=1000,
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://api.test",
        headers=TEST_HEADERS,
    ) as client:
        response = await client.post("/api/projects/p1", content="12345678901")

    assert response.status_code == 413
    assert "10-byte" in response.json()["detail"]
