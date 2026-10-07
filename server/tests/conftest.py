"""Shared fixtures.

Two kinds of test live here. The pure ones -- deep-merge semantics, identity
header parsing -- need nothing but Python and always run. The rest need a real
PostgreSQL, because what they are testing *is* the database's behavior: a row
lock serializing two concurrent PATCHes, a unique constraint producing one 409,
a trigger refusing an UPDATE. A fake would test the fake.

Run everything with::

    docker run -d --name chai-test-db -p 55432:5432 \
      -e POSTGRES_PASSWORD=test -e POSTGRES_DB=chai_test postgres:16-alpine
    TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/chai_test \
      pytest

Without ``TEST_DATABASE_URL`` the database tests skip and say why.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from app.config import Settings
from app.main import create_app
from httpx import ASGITransport, AsyncClient

DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or ""

# CI sets REQUIRE_TESTS=1. A test that cannot run then FAILS instead of skipping,
# because a skip reports as a pass: that is how CI once ran none of these (#32).
REQUIRE_TESTS = bool(os.getenv("REQUIRE_TESTS"))

requires_db = pytest.mark.skipif(
    not DB_URL and not REQUIRE_TESTS,
    reason="set TEST_DATABASE_URL to a PostgreSQL this test may TRUNCATE",
)

TEST_EMAIL = "tester@hospital.example"
TEST_HEADERS = {"X-Forwarded-Email": TEST_EMAIL, "X-Forwarded-User": "Test Er"}


def make_settings(**overrides: object) -> Settings:
    """Settings for a test, with the environment deliberately ignored.

    Reading the real environment here would make a developer's local
    ``IDENTITY_MODE`` change what the tests assert.
    """
    base: dict[str, object] = {
        "database_url": DB_URL,
        "db_pool_min": 2,
        "db_pool_max": 12,
        "identity_mode": "proxy",
        "identity_header": "X-Forwarded-Email",
        "identity_name_header": "X-Forwarded-User",
        "run_migrations": True,
        "sse_keepalive_seconds": 1.0,
        "version": "test",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired straight to the ASGI app, with lifespan run.

    ``httpx.ASGITransport`` does not run startup or shutdown on its own, so the
    lifespan context is entered by hand. Without it there is no pool, no
    migration and no event broker.
    """
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        # Every test starts from an empty database. TRUNCATE rather than DELETE
        # so the bigserial in project_log restarts and assertions about order
        # are not affected by earlier tests.
        async with app.state.db.acquire() as conn:
            # project_version is listed explicitly: it has no foreign key to
            # projects, on purpose (002_versions.sql), so CASCADE does not
            # reach it and its rows survived between tests. A snapshot left
            # behind by an earlier test collides with the new rev 1 of a
            # project reusing the same id, and the ON CONFLICT swallows it --
            # so the leak showed up as a test that passed or failed depending
            # on what ran before it.
            #
            # TRUNCATE rather than DELETE so the bigserial in project_log
            # restarts and assertions about order are not affected by earlier
            # tests. It also does not fire the row-level triggers that
            # (correctly) refuse DELETE on project_version.
            await conn.execute(
                "TRUNCATE project_version, project_log, projects "
                "RESTART IDENTITY CASCADE"
            )
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://api.test", headers=TEST_HEADERS
        ) as http:
            http.app = app  # type: ignore[attr-defined]
            yield http


@pytest.fixture
async def project(client: AsyncClient) -> str:
    """One project with a small nested document, ready to patch."""
    pid = "ptest001"
    response = await client.post(
        f"/api/projects/{pid}",
        json={
            "meta": {"solution": "Sepsis alert", "org": "St Elsewhere"},
            "items": {
                "s4-1": {"status": "met", "evidence": "validation report"},
                "s4-2": {"status": "partial", "owner": "A. Reviewer"},
            },
            "metrics": [
                {"cat": "Fairness & equity", "name": "TPR gap", "value": "0.04"}
            ],
            "archived": False,
        },
    )
    assert response.status_code == 201
    return pid
