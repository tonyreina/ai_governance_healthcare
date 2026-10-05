"""PostgreSQL access: a connection pool, and migrations applied at boot.

asyncpg rather than SQLAlchemy, for three reasons that all matter here:

* ``jsonb`` round-trips through a type codec straight to ``dict``, so the
  project document never passes through an ORM layer that might reorder or
  coerce it -- the contract says treat it as opaque JSON;
* ``LISTEN``/``NOTIFY`` is first-class (``Connection.add_listener``), which is
  what fans change events out to every replica's SSE stream;
* ``SELECT ... FOR UPDATE`` inside an explicit transaction is plain SQL, and
  that row lock is what makes the deep-merge PATCH atomic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import asyncpg

log = logging.getLogger("chai.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Arbitrary but fixed: two containers booting at once must not race to apply
# the same migration. The first one in holds this lock; the second waits, then
# finds the migration already recorded and does nothing.
MIGRATION_LOCK_ID = 0x4348_4149  # "CHAI"


def normalize_dsn(dsn: str) -> str:
    """Accept the DSN spellings the three clouds hand out.

    ``postgresql+asyncpg://`` (SQLAlchemy style) and ``postgres://`` (Heroku and
    friends) both become ``postgresql://``, which is what asyncpg parses. A
    Cloud SQL unix socket DSN --
    ``postgresql://user:pw@/db?host=/cloudsql/project:region:instance`` -- is
    already valid and passes through untouched.
    """
    dsn = dsn.strip()
    for prefix, replacement in (
        ("postgresql+asyncpg://", "postgresql://"),
        ("postgres+asyncpg://", "postgresql://"),
        ("postgres://", "postgresql://"),
    ):
        if dsn.startswith(prefix):
            return replacement + dsn[len(prefix) :]
    return dsn


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Make ``jsonb`` and ``json`` columns arrive as Python objects."""
    for type_name in ("jsonb", "json"):
        await conn.set_type_codec(
            type_name,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


class Database:
    """A pool plus the handful of operations the API needs from it."""

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        connect_timeout: float = 10.0,
    ) -> None:
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL is not set. The API needs PostgreSQL; there is no "
                "in-memory fallback, because the audit log has to outlive the "
                "container."
            )
        self.dsn = normalize_dsn(dsn)
        self._min_size = min_size
        self._max_size = max_size
        self._connect_timeout = connect_timeout
        self._pool: asyncpg.Pool | None = None

    # --- lifecycle --------------------------------------------------------

    async def connect(self, *, retries: int = 10, delay: float = 1.0) -> None:
        """Open the pool, retrying while the database warms up.

        Managed databases and compose-started containers are routinely not
        listening yet when the app container starts, and a crash loop is a
        worse first impression than a few seconds of retrying.
        """
        last: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                self._pool = await asyncpg.create_pool(
                    self.dsn,
                    min_size=self._min_size,
                    max_size=self._max_size,
                    timeout=self._connect_timeout,
                    command_timeout=30.0,
                    init=_init_connection,
                )
                log.info(
                    "connected to PostgreSQL (pool %d-%d)",
                    self._min_size,
                    self._max_size,
                )
                return
            except (OSError, asyncpg.PostgresError) as exc:
                last = exc
                log.warning(
                    "database not ready (attempt %d/%d): %s", attempt, retries, exc
                )
                await asyncio.sleep(delay * attempt)
        raise RuntimeError(f"could not connect to PostgreSQL: {last}") from last

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("database pool is not open")
        return self._pool

    def acquire(self) -> Any:
        """``async with db.acquire() as conn:``"""
        return self.pool.acquire()

    async def listener_connection(self) -> asyncpg.Connection:
        """A dedicated connection, outside the pool, for ``LISTEN``.

        A listening connection is pinned for the life of the subscription, so
        it must not come from the pool -- it would starve it.
        """
        # asyncpg.connect() has no `init` parameter -- that is create_pool()
        # only, where it runs per pooled connection. Passing it here raised
        # TypeError on every startup, which the SSE subscription then retried
        # forever. Run the codec setup by hand instead.
        conn = await asyncpg.connect(self.dsn, timeout=self._connect_timeout)
        await _init_connection(conn)
        return conn

    # --- migrations -------------------------------------------------------

    async def migrate(self, directory: Path | None = None) -> list[str]:
        """Apply every unapplied ``migrations/*.sql`` in filename order.

        Returns the versions applied by *this* call. Each file runs inside its
        own transaction, so a failing migration leaves nothing half-applied.
        """
        directory = directory or MIGRATIONS_DIR
        files = sorted(p for p in directory.glob("*.sql") if p.is_file())
        if not files:
            log.warning("no migrations found in %s", directory)
            return []

        applied: list[str] = []
        async with self.acquire() as conn:
            await conn.execute(f"SELECT pg_advisory_lock({MIGRATION_LOCK_ID})")
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                      version    text PRIMARY KEY,
                      applied_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                done = {
                    row["version"]
                    for row in await conn.fetch("SELECT version FROM schema_migrations")
                }
                for path in files:
                    version = path.name
                    if version in done:
                        continue
                    log.info("applying migration %s", version)
                    sql = path.read_text(encoding="utf-8")
                    async with conn.transaction():
                        # No parameters, so asyncpg uses the simple query
                        # protocol and a multi-statement file runs as one unit.
                        await conn.execute(sql)
                        await conn.execute(
                            "INSERT INTO schema_migrations (version) VALUES ($1)",
                            version,
                        )
                    applied.append(version)
            finally:
                await conn.execute(f"SELECT pg_advisory_unlock({MIGRATION_LOCK_ID})")

        if applied:
            log.info("applied %d migration(s): %s", len(applied), ", ".join(applied))
        else:
            log.info("schema is up to date")
        return applied

    async def ping(self) -> bool:
        try:
            async with self.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except (OSError, asyncpg.PostgresError, RuntimeError) as exc:
            log.warning("database ping failed: %s", exc)
            return False
