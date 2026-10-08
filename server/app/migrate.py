"""``python -m app.migrate``: apply migrations and provision the serving role.

This is the ONE process that holds the database owner's credential. The API does
not: it connects as the restricted serving role (``app.roles``), so a compromised
API cannot disable the append-only triggers the history's value rests on (#48).

Run it as a job before the API starts (compose does: the ``migrate`` service; on a
cloud, a one-off task or job). It is idempotent, so running it on every deploy is
right: it applies any new migration, re-asserts the grants, and re-syncs the role's
password from ``APP_POSTGRES_PASSWORD``.

    python -m app.migrate                  migrate, then provision the role
    python -m app.migrate --print-grants   print the GRANTs and exit (no database)

Environment: the owner's ``DATABASE_URL`` (or ``POSTGRES_*``), and for the role
``APP_POSTGRES_USER`` (default ``chai_app``) and ``APP_POSTGRES_PASSWORD``. With no
``APP_POSTGRES_PASSWORD`` it only migrates, which is the single-role setup this
replaces and is reported as such.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from .config import build_database_url
from .db import Database
from .roles import DEFAULT_APP_ROLE, check_role_name, grant_statements, provision

log = logging.getLogger("chai.migrate")


async def run(env: dict[str, str]) -> int:
    dsn = build_database_url(env)
    if not dsn:
        print(
            "migrate: no owner credential. Set DATABASE_URL, or POSTGRES_PASSWORD "
            "with POSTGRES_USER, POSTGRES_HOST and POSTGRES_DB.",
            file=sys.stderr,
        )
        return 2

    role = check_role_name(env.get("APP_POSTGRES_USER") or DEFAULT_APP_ROLE)
    password = env.get("APP_POSTGRES_PASSWORD") or ""

    db = Database(dsn, min_size=1, max_size=1)
    # A database that is still starting is the normal case in compose, so wait for
    # it; MIGRATE_CONNECT_RETRIES shortens that where waiting is not wanted.
    await db.connect(retries=int(env.get("MIGRATE_CONNECT_RETRIES") or 10))
    try:
        applied = await db.migrate()
        print(
            f"migrate: applied {len(applied)} migration(s)"
            if applied
            else "migrate: schema is up to date"
        )
        if not password:
            print(
                "migrate: APP_POSTGRES_PASSWORD is not set, so no restricted serving "
                "role was provisioned. The API will serve as the table owner, and "
                "the append-only triggers will not constrain it (#48).",
                file=sys.stderr,
            )
            return 0
        async with db.acquire() as conn:
            await provision(conn, role, password)
        print(
            f"migrate: role {role!r} provisioned (login, no superuser, table "
            "privileges only)"
        )
        return 0
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    if "--print-grants" in args:
        role = os.environ.get("APP_POSTGRES_USER") or DEFAULT_APP_ROLE
        print("\n".join(s + ";" for s in grant_statements(role)))
        return 0
    try:
        return asyncio.run(run(dict(os.environ)))
    except (RuntimeError, ValueError) as exc:
        print(f"migrate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
