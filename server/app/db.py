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
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import asyncpg

from .roles import DbRole

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


# sslmode values that permit an unencrypted connection. asyncpg's default is
# "prefer", which tries TLS and SILENTLY ACCEPTS cleartext if the server does
# not offer it -- the failure mode being that nothing looks wrong.
_WEAK_SSLMODES = {"disable", "allow", "prefer"}


def _dsn_is_internal(dsn: str) -> bool:
    """Is this DSN reached over a path that does not cross a network?

    Three shapes count:

    * a unix socket -- Cloud SQL's ``?host=/cloudsql/...``;
    * loopback;
    * a single-label hostname, i.e. one with no dots. ``@db:5432`` is the
      compose service name and resolves only on the internal bridge;
      ``@postgres`` is the same thing on Kubernetes.

    The last one is a judgment call, and it is deliberate. Warning about the
    default local stack on every boot would train operators to ignore the
    warning, and the warning exists for the moment somebody edits that DSN to
    point at a managed instance -- which always has a fully qualified name.
    A warning nobody reads protects nothing.
    """
    parsed = urlsplit(dsn)
    query = parse_qs(parsed.query)
    socket_host = (query.get("host") or [""])[0]
    if socket_host.startswith("/"):
        return True
    host = parsed.hostname or ""
    if host in {"", "localhost", "127.0.0.1", "::1"}:
        return True
    return "." not in host and ":" not in host


def check_dsn_encryption(dsn: str) -> str | None:
    """Return a warning when this DSN may carry PHI in cleartext.

    Transmission security is addressable under 45 CFR 164.312(e)(1), and the
    thing that makes it easy to get wrong here is that the compose DSN -- which
    is fine on an ``internal: true`` bridge -- is also the template an operator
    edits when moving to Cloud SQL, RDS or Azure Database for PostgreSQL. At
    that point the same string crosses a network and ``prefer`` quietly accepts
    an unencrypted connection.
    """
    if _dsn_is_internal(dsn):
        return None
    sslmode = (parse_qs(urlsplit(dsn).query).get("sslmode") or [""])[0].lower()
    if not sslmode:
        return (
            "DATABASE_URL has no sslmode and points at a remote host. asyncpg "
            "defaults to 'prefer', which accepts an UNENCRYPTED connection if "
            "the server does not offer TLS. Add ?sslmode=verify-full with a CA "
            "bundle, or at minimum ?sslmode=require."
        )
    if sslmode in _WEAK_SSLMODES:
        return (
            f"DATABASE_URL has sslmode={sslmode}, which permits an UNENCRYPTED "
            "connection to a remote host. Use verify-full (preferred) or "
            "require."
        )
    if sslmode == "require":
        return (
            "DATABASE_URL has sslmode=require, which encrypts but does NOT "
            "verify the server's certificate, so it does not protect against "
            "an active attacker. Prefer verify-full with a CA bundle."
        )
    return None


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
                "No database credential is set: neither DATABASE_URL / "
                "POSTGRES_PASSWORD (the owner) nor APP_DATABASE_URL / "
                "APP_POSTGRES_PASSWORD (the restricted serving role). The API "
                "needs PostgreSQL; there is no in-memory fallback, because the "
                "audit log has to outlive the container."
            )
        self.dsn = normalize_dsn(dsn)
        warning = check_dsn_encryption(self.dsn)
        if warning:
            log.warning("%s", warning)
        self._min_size = min_size
        self._max_size = max_size
        self._connect_timeout = connect_timeout
        self._pool: asyncpg.Pool | None = None
        self._ping_cache: tuple[float, bool] | None = None
        self._ping_lock = asyncio.Lock()
        self._rules_cache: tuple[float, str | None] | None = None
        self._rules_lock = asyncio.Lock()

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

    async def serving_role(self) -> DbRole:
        """Is this connection the table owner or a superuser, or a restricted role?

        The append-only triggers constrain a role only if it cannot disable or
        drop them, and that is a property of the role, not of the code (#48).
        """
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT r.rolsuper,
                       EXISTS (SELECT 1 FROM pg_tables
                                WHERE schemaname = 'public'
                                  AND tableowner = current_user) AS owns_tables
                  FROM pg_roles r WHERE r.rolname = current_user
                """
            )
        if row["rolsuper"] or row["owns_tables"]:
            return DbRole.OWNER
        return DbRole.RESTRICTED

    async def ping(self) -> bool:
        try:
            async with self.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except (OSError, asyncpg.PostgresError, RuntimeError) as exc:
            log.warning("database ping failed: %s", exc)
            return False

    async def ping_cached(self, ttl: float = 2.0) -> bool:
        """:meth:`ping`, but at most once per ``ttl`` seconds.

        ``GET /api/health`` is deliberately unauthenticated -- every platform
        in docs/deploy.md probes it from inside the load balancer, where no
        identity header exists yet -- and it is exempt from the rate limiter
        for the same reason. An uncached ping therefore let anyone who could
        reach the port take a connection from a pool of ten, as fast as they
        liked, and starve real requests of it.

        A couple of seconds is invisible to a probe that runs every ten or
        thirty, and turns an unbounded amplifier into a fixed, tiny load.
        Failures are cached too, briefly: a database that is down does not
        come back within two seconds, and retrying per request is how a
        struggling database gets hammered by its own health checks.
        """
        now = time.monotonic()
        cached = self._ping_cache
        if cached is not None and now - cached[0] < ttl:
            return cached[1]
        async with self._ping_lock:
            # Re-check: a burst of concurrent probes should produce one query,
            # not one per waiter.
            cached = self._ping_cache
            now = time.monotonic()
            if cached is not None and now - cached[0] < ttl:
                return cached[1]
            alive = await self.ping()
            self._ping_cache = (time.monotonic(), alive)
            return alive

    async def retirement_rules_cached(self, ttl: float = 30.0) -> str | None:
        """The active retirement rule-set hash (D-76), at most once per ``ttl``.

        For ``/api/health``, which is unauthenticated and not rate limited, so it is
        cached for the reason :meth:`ping_cached` is. The rules change only when the
        migrate job runs, which a deploy follows with a restart. ``None`` when it
        cannot be read (no database, or a schema from before 010).
        """
        cached = self._rules_cache
        if cached is not None and time.monotonic() - cached[0] < ttl:
            return cached[1]
        async with self._rules_lock:
            cached = self._rules_cache
            if cached is not None and time.monotonic() - cached[0] < ttl:
                return cached[1]
            try:
                async with self.acquire() as conn:
                    # The latest change's hash, as retirement.active_rule_set_hash.
                    value = await conn.fetchval(
                        "SELECT rule_set_hash FROM retirement_rule_change"
                        " ORDER BY id DESC LIMIT 1"
                    )
            except (OSError, asyncpg.PostgresError, RuntimeError) as exc:
                log.warning("cannot read the retirement rule set: %s", exc)
                value = None
            self._rules_cache = (time.monotonic(), value)
            return value
