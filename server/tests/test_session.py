"""Session limits: the event stream must not outlive a revoked session (#49).

The application has no session of its own: identity arrives on every request from the
proxy. That makes disabling an account take effect on the next request, everywhere
except one place. `GET /api/events` authenticated once, when it attached, and then
delivered change notifications for as long as the connection stayed up, so a stream
opened before an account was deprovisioned kept working after it.

The API cannot ask the identity provider whether a session is still valid. What it
can do is bound how long a stream lives, so the browser has to reconnect, and the
reconnect goes back through the front door and is authenticated again. These tests
cover that, and the two settings the browser reads from /api/health.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from app.config import Settings
from httpx import AsyncClient

# The uvicorn fixture lives in test_events; importing it makes it available here.
from .conftest import TEST_HEADERS, make_settings, requires_db
from .test_events import base_url  # noqa: F401

pytestmark = [requires_db, pytest.mark.db]


@pytest.fixture
def settings() -> Settings:
    """A short lifetime and a LONG heartbeat.

    The heartbeat is long on purpose. The first version only checked the lifetime when
    the loop woke for a heartbeat, so a stream lived for the lifetime PLUS up to one
    heartbeat interval: 15 seconds over a 5 second limit, found against the real stack
    and missed by a test whose heartbeat was 0.2 seconds.
    """
    return make_settings(sse_max_lifetime_seconds=1.0, sse_keepalive_seconds=30.0)


async def open_and_wait_for_close(url: str, give_up: float = 8.0) -> tuple[float, int]:
    """Hold a stream until the SERVER ends it. Returns (seconds open, lines read)."""
    started = time.monotonic()
    lines = 0

    async def pump() -> None:
        nonlocal lines
        async with AsyncClient(base_url=url, headers=TEST_HEADERS) as http:
            async with http.stream("GET", "/api/events") as response:
                assert response.status_code == 200
                async for _ in response.aiter_lines():
                    lines += 1

    await asyncio.wait_for(pump(), timeout=give_up)
    return time.monotonic() - started, lines


async def test_a_stream_is_closed_by_the_server_after_its_lifetime(
    base_url: str,  # noqa: F811
) -> None:
    elapsed, lines = await open_and_wait_for_close(base_url)
    assert lines > 0, "it delivered something before it closed"
    assert 0.8 <= elapsed < 6.0, f"closed after {elapsed:.1f}s, expected about 1s"


async def test_reconnecting_works_and_is_authenticated_again(
    base_url: str,  # noqa: F811
) -> None:
    """The reconnect is the re-check: it is a new request through the front door."""
    await open_and_wait_for_close(base_url)
    elapsed, lines = await open_and_wait_for_close(base_url)
    assert lines > 0 and elapsed >= 0.8

    async with AsyncClient(base_url=base_url, headers={}) as anonymous:
        assert (await anonymous.get("/api/events")).status_code == 401, (
            "a connection with no identity is refused, so a revoked session cannot "
            "reconnect"
        )


class TestUnlimited:
    """0 is a legitimate choice: a deployment whose front door already bounds it."""

    @pytest.fixture
    def settings(self) -> Settings:
        return make_settings(sse_max_lifetime_seconds=0.0, sse_keepalive_seconds=0.2)

    async def test_a_lifetime_of_zero_never_closes_the_stream(
        self,
        base_url: str,  # noqa: F811
    ) -> None:
        # The module's other tests see a stream close after about a second. Here
        # it must still be open well past that, so the wait times out.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(open_and_wait_for_close(base_url), timeout=2.5)


def test_the_default_lifetime_is_bounded() -> None:
    assert Settings().sse_max_lifetime_seconds > 0, "the default must not be forever"
    assert Settings().sse_max_lifetime_seconds <= 3600


async def test_health_tells_the_browser_the_session_settings(
    client: AsyncClient,
) -> None:
    body = (await client.get("/api/health")).json()
    assert body["idle_lock_minutes"] == 0 and body["sign_out_url"] == ""


async def test_health_carries_what_is_configured() -> None:
    from app.main import create_app
    from httpx import ASGITransport

    app = create_app(
        make_settings(idle_lock_minutes=15, sign_out_url="/.auth/logout"),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://api.test"
        ) as http:
            body = (await http.get("/api/health")).json()
    assert body["idle_lock_minutes"] == 15
    assert body["sign_out_url"] == "/.auth/logout"


@pytest.mark.parametrize(
    "url",
    [
        "https://idp.example/logout",
        "/.auth/logout",
        "/?gcp-iap-mode=CLEAR_LOGIN_COOKIE",
        "/oauth2/sign_out?rd=https%3A%2F%2Fidp.example%2Flogout",
    ],
)
def test_a_safe_sign_out_url_is_accepted(url: str, monkeypatch) -> None:
    monkeypatch.setenv("SIGN_OUT_URL", url)
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    assert Settings.from_env().sign_out_url == url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "//evil.example/logout",
        "http://plain.example/logout",
        " https://idp.example/logout",
        "https://idp.example/logout\r\nSet-Cookie: x=1",
        "https://idp.example/a b",
        "ftp://idp.example/",
        "logout",
    ],
)
def test_an_unsafe_sign_out_url_is_refused_at_startup(url: str, monkeypatch) -> None:
    """It becomes a link in the page, so it is an allowlist: https, or a path."""
    monkeypatch.setenv("SIGN_OUT_URL", url)
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="SIGN_OUT_URL"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["-1", "abc", "1.5", "99999"])
def test_a_bad_idle_lock_is_refused(value: str, monkeypatch) -> None:
    monkeypatch.setenv("IDLE_LOCK_MINUTES", value)
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="IDLE_LOCK_MINUTES"):
        Settings.from_env()


def test_idle_lock_is_off_by_default_and_accepts_minutes(monkeypatch) -> None:
    monkeypatch.delenv("IDLE_LOCK_MINUTES", raising=False)
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    assert Settings.from_env().idle_lock_minutes == 0
    monkeypatch.setenv("IDLE_LOCK_MINUTES", "20")
    assert Settings.from_env().idle_lock_minutes == 20
