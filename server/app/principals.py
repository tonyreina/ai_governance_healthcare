"""Who an identity id is: recording sign-ins, and resolving a batch (#39).

The proxy asserts a name and an email on every request, and the API used to keep
only the id, so every identity but the viewer's own rendered as "someone" and an
access list was a column of opaque ids. This keeps what the proxy said, keyed by
the id, and answers a batch lookup.

It builds a staff directory as a side effect, which is why the lookup is not open:
it answers only for people the caller can already see on a project they can read.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

import asyncpg

from .access import access_of, can_read
from .auth import Identity

log = logging.getLogger("chai.principals")

# Identities that are not a person and must not become directory entries.
NOT_PEOPLE = frozenset({"", "anonymous"})

# A write per request would turn every read into a write. An identity is written
# when it is new, when its name or email changed, or at most this often otherwise
# (so last_seen stays roughly true without being a heartbeat).
REFRESH_SECONDS = 3600.0

MAX_LOOKUP = 100
MAX_ID_LENGTH = 256


class PrincipalRecorder:
    """Remembers what it last wrote per id, so a busy user costs one write an hour."""

    def __init__(self, db: Any, *, refresh_seconds: float = REFRESH_SECONDS) -> None:
        self._db = db
        self._refresh = refresh_seconds
        self._written: dict[str, tuple[str, str, float]] = {}

    async def touch(self, identity: Identity) -> None:
        """Record this identity if it needs recording. Never raises.

        Knowing someone's name is a convenience; the request they made is the point,
        so a failure here is logged and swallowed.
        """
        if identity.dev or identity.id in NOT_PEOPLE:
            return
        now = time.monotonic()
        seen = self._written.get(identity.id)
        if (
            seen
            and seen[0] == identity.name
            and seen[1] == identity.email
            and now - seen[2] < self._refresh
        ):
            return
        try:
            await self._write(identity)
        except Exception as exc:
            log.warning("could not record principal %r: %s", identity.id, exc)
            return
        self._written[identity.id] = (identity.name, identity.email, now)

    async def _write(self, identity: Identity) -> None:
        async with self._db.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO principals (id, name, email)
                VALUES ($1, $2, $3)
                ON CONFLICT (id) DO UPDATE
                   SET name = EXCLUDED.name,
                       email = EXCLUDED.email,
                       last_seen = now()
                """,
                identity.id,
                identity.name or "",
                identity.email or "",
            )


def ids_in_doc(doc: dict[str, Any]) -> set[str]:
    """Every person a project document names: its access lists and who signed off."""
    found: set[str] = set()
    access = access_of(doc)
    for role in ("owners", "writers", "readers"):
        found.update(access[role])
    gates = doc.get("gates")
    if isinstance(gates, dict):
        for gate in gates.values():
            if isinstance(gate, dict):
                signer = gate.get("signedBy")
                if isinstance(signer, str) and signer:
                    found.add(signer)
    for key in ("updatedBy", "cardUpdatedBy"):
        value = doc.get(key)
        if isinstance(value, str) and value:
            found.add(value)
    return found


async def visible_ids(
    conn: asyncpg.Connection,
    caller: str | None,
    wanted: Iterable[str],
    *,
    enforced: bool,
) -> set[str]:
    """Which of ``wanted`` the caller may learn the identity of.

    The caller themself, and anyone named on a project the caller can read: its
    access lists, its sign-offs, its log authors and its last editors. Not anyone
    else, however the id was obtained: the table is a staff directory and this is
    what keeps it from being one that any signed-in user can walk.
    """
    wanted = set(wanted)
    visible = {caller} & wanted if caller else set()
    rows = await conn.fetch("SELECT id, doc, created_by, updated_by FROM projects")
    readable: list[str] = []
    for row in rows:
        doc = row["doc"] or {}
        if not can_read(doc, caller, enforced=enforced):
            continue
        readable.append(row["id"])
        visible |= ids_in_doc(doc) & wanted
        for column in ("created_by", "updated_by"):
            if row[column] in wanted:
                visible.add(row[column])
    if readable and wanted - visible:
        authors = await conn.fetch(
            "SELECT DISTINCT by_id FROM project_log "
            "WHERE project_id = ANY($1::text[]) AND by_id = ANY($2::text[])",
            readable,
            list(wanted - visible),
        )
        visible |= {r["by_id"] for r in authors}
    return visible & wanted


async def resolve(
    conn: asyncpg.Connection,
    caller: str | None,
    wanted: Iterable[str],
    *,
    enforced: bool,
) -> list[asyncpg.Record]:
    allowed = await visible_ids(conn, caller, wanted, enforced=enforced)
    if not allowed:
        return []
    return await conn.fetch(
        "SELECT id, name, email FROM principals WHERE id = ANY($1::text[]) ORDER BY id",
        sorted(allowed),
    )
