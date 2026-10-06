"""API transport hardening middleware."""

from __future__ import annotations

import asyncio
import tracemalloc

from app.db import Database
from app.main import SlidingWindowRateLimiter, create_app
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_HEADERS, make_settings, requires_db


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


class TestRateLimiterMemory:
    """The limiter must not grow a key for every address it ever sees.

    `defaultdict(deque)` created an entry per distinct identity or source
    address and never removed one, so for IP-keyed traffic the dictionary was
    an attacker-controlled leak: 200k addresses meant 200k retained keys, all
    of them empty deques long after their window had passed.
    """

    async def test_stale_keys_are_swept(self) -> None:
        limiter = SlidingWindowRateLimiter(window_seconds=1, max_requests=100)
        for i in range(500):
            await limiter.allow(f"ip:10.0.0.{i}")
        assert limiter.tracked_keys == 500

        # Once every one of those falls outside the window, the next call
        # sweeps them.
        await asyncio.sleep(1.1)
        await limiter.allow("ip:10.0.1.1")
        assert limiter.tracked_keys == 1, (
            f"{limiter.tracked_keys} keys retained after the window passed"
        )

    async def test_an_active_key_survives_a_sweep(self) -> None:
        limiter = SlidingWindowRateLimiter(window_seconds=2, max_requests=100)
        await limiter.allow("ip:busy")
        await asyncio.sleep(0.3)
        for _ in range(5):
            await limiter.allow("ip:busy")
            await asyncio.sleep(0.3)
        assert limiter.tracked_keys == 1
        assert "ip:busy" in limiter._events

    async def test_the_limit_still_holds_across_a_sweep(self) -> None:
        """Sweeping must not hand a client a fresh allowance."""
        limiter = SlidingWindowRateLimiter(window_seconds=2, max_requests=3)
        assert [await limiter.allow("k") for _ in range(4)] == [
            True,
            True,
            True,
            False,
        ]
        await asyncio.sleep(0.1)
        await limiter.allow("other")  # may trigger bookkeeping
        assert await limiter.allow("k") is False, "k must still be over its limit"

    async def test_the_window_really_slides(self) -> None:
        limiter = SlidingWindowRateLimiter(window_seconds=1, max_requests=2)
        assert await limiter.allow("k") is True
        assert await limiter.allow("k") is True
        assert await limiter.allow("k") is False
        await asyncio.sleep(1.1)
        assert await limiter.allow("k") is True, "entries must expire"


class TestBodyLimitDoesNotBuffer:
    """A body with no Content-Length must be rejected mid-stream.

    `await request.body()` read the whole thing into memory and only then
    compared it to the limit, so a 64MB chunked POST against a 1KB limit cost
    64MB and returned 413 -- the limit not preventing the thing it exists to
    prevent.
    """

    @staticmethod
    async def _chunks(total: int, size: int = 64 * 1024):
        sent = 0
        while sent < total:
            n = min(size, total - sent)
            yield b"x" * n
            sent += n

    async def test_an_oversize_chunked_body_is_rejected(self) -> None:
        app = create_app(
            make_settings(request_body_limit_bytes=1024, rate_limit_max_requests=1000)
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://api.test",
            headers=TEST_HEADERS,
        ) as client:
            response = await client.post(
                "/api/projects/p1", content=self._chunks(8 * 1024 * 1024)
            )
        assert response.status_code == 413

    async def test_it_does_not_buffer_the_whole_body_first(self) -> None:
        app = create_app(
            make_settings(request_body_limit_bytes=1024, rate_limit_max_requests=1000)
        )
        payload = 16 * 1024 * 1024
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://api.test",
            headers=TEST_HEADERS,
        ) as client:
            tracemalloc.start()
            tracemalloc.reset_peak()
            response = await client.post(
                "/api/projects/p1", content=self._chunks(payload)
            )
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

        assert response.status_code == 413
        assert peak < payload // 4, (
            f"peaked at {peak:,} bytes for a {payload:,}-byte body: "
            "the body is being buffered before the limit is applied"
        )

    @requires_db
    async def test_a_chunked_body_under_the_limit_still_reaches_the_route(
        self, client: AsyncClient
    ) -> None:
        """The replayed body must arrive intact.

        The middleware consumes request.stream() to measure the body, so the
        route downstream would see nothing unless it is replayed. Run against
        a real database so the assertion is "the write landed", not "some
        status code came back".
        """

        async def small():
            yield b'{"meta":{"sol'
            yield b'ution":"Chunked"}}'

        # Content-Type matters: httpx does not set one for a generator body,
        # and without it FastAPI hands Pydantic the raw bytes instead of
        # parsed JSON. That is unrelated to the replay being tested here.
        response = await client.post(
            "/api/projects/pchunk",
            content=small(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["meta"]["solution"] == "Chunked"

        stored = (await client.get("/api/projects")).json()
        assert any(p["id"] == "pchunk" for p in stored)


class TestHealthIsNotAnAmplifier:
    """/api/health is unauthenticated AND exempt from the rate limiter.

    An uncached database check therefore let anyone who could reach the port
    take a connection from a pool of ten as fast as they liked.
    """

    async def test_repeated_probes_hit_the_database_once(self) -> None:
        calls = 0

        class CountingDb:
            async def ping(self_inner) -> bool:
                nonlocal calls
                calls += 1
                return True

            ping_cached = Database.ping_cached

            def __init__(self_inner) -> None:
                self_inner._ping_cache = None
                self_inner._ping_lock = asyncio.Lock()

        db = CountingDb()
        results = await asyncio.gather(*(db.ping_cached() for _ in range(50)))
        assert all(results)
        assert calls == 1, f"{calls} database round trips for 50 concurrent probes"

    async def test_the_cache_expires(self) -> None:
        calls = 0

        class CountingDb:
            async def ping(self_inner) -> bool:
                nonlocal calls
                calls += 1
                return True

            ping_cached = Database.ping_cached

            def __init__(self_inner) -> None:
                self_inner._ping_cache = None
                self_inner._ping_lock = asyncio.Lock()

        db = CountingDb()
        await db.ping_cached(ttl=0.1)
        await asyncio.sleep(0.2)
        await db.ping_cached(ttl=0.1)
        assert calls == 2

    async def test_a_failure_is_cached_too(self) -> None:
        """A database that is down does not recover within the TTL, and
        retrying per request is how a struggling database gets hammered by
        its own health checks."""
        calls = 0

        class FailingDb:
            async def ping(self_inner) -> bool:
                nonlocal calls
                calls += 1
                return False

            ping_cached = Database.ping_cached

            def __init__(self_inner) -> None:
                self_inner._ping_cache = None
                self_inner._ping_lock = asyncio.Lock()

        db = FailingDb()
        results = [await db.ping_cached() for _ in range(20)]
        assert not any(results)
        assert calls == 1
