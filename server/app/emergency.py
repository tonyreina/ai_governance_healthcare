"""Emergency ("break-glass") access: a record no living account can reach (#42).

When a project's only owner leaves and their SSO account is disabled, nobody could
read, export, reassign, archive, delete or purge the record, the organization's
Security Officer included. Recovery was a hand-written UPDATE against the `access`
jsonb: the privileged database path the role model exists to avoid needing. 45 CFR
164.312(a)(2)(ii), an emergency access procedure, is *required*.

An identity listed in ``EMERGENCY_ACCESS_IDS`` holds owner rights on every project.
It is a path around the access lists, so the rule that makes it a control and not a
backdoor is that **every use is recorded where the project's owners will see it**:

* each use that matters (any write, archive, delete or purge, and the first read of a
  project in a window) writes a system entry into that project's own audit log, which
  a purge never redacts, with the stable event name ``access.breakglass``;
* every use, throttled or not, is an ``access.breakglass`` security event
  (``securitylog``), which is what an alert should match;
* the identity is only ever the one the proxy asserted, so the list of who holds this
  is configuration, not something a client can claim.

The entry for a *delete* cannot persist (the log is removed with the project, by
design); the warning and the deletion tombstone's ``deleted_by`` record it instead.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from enum import StrEnum

import asyncpg

from .auth import Identity
from .securitylog import SecurityEvent, emit

# A dashboard polls: opening one project as the break-glass identity fetches its
# versions and log again on every change event. Reads of the same project by the same
# person inside this window are one entry, not hundreds. Writes are never throttled.
READ_WINDOW_SECONDS = 600.0

EVENT_NAME = "access.breakglass"


class Use(StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


class EmergencyAudit:
    """Records each use of emergency access."""

    def __init__(self, *, read_window: float = READ_WINDOW_SECONDS) -> None:
        self._window = read_window
        self._last_read: dict[tuple[str, str], float] = {}

    def _read_is_due(self, actor: str, project_id: str) -> bool:
        now = time.monotonic()
        key = (actor, project_id)
        last = self._last_read.get(key)
        if last is not None and now - last < self._window:
            return False
        self._last_read[key] = now
        return True

    async def record(
        self,
        conn: asyncpg.Connection,
        identity: Identity,
        project_id: str,
        action: str,
        use: Use,
    ) -> None:
        """Note that this identity used emergency access on this project."""
        emit(
            SecurityEvent.ACCESS_BREAKGLASS,
            f"access.breakglass actor={identity.id!r} project={project_id!r} "
            f"action={action}",
            actor=identity.id,
            project=project_id,
            action=action,
        )
        if use is Use.DELETE:
            # The project's log goes with it. The warning and the deletion
            # tombstone are what remain.
            return
        if use is Use.READ and not self._read_is_due(identity.id, project_id):
            return
        who = identity.name or identity.id
        now = datetime.now(UTC)
        await conn.execute(
            """
            INSERT INTO project_log (project_id, at, by_id, entry, is_system)
            VALUES ($1, $2, $3, $4, true)
            """,
            project_id,
            now,
            identity.id,
            {
                "at": now.isoformat(timespec="milliseconds"),
                "by": identity.id,
                "event": EVENT_NAME,
                "text": (
                    f"EMERGENCY ACCESS: {who} ({identity.id}) used break-glass access "
                    f"to {action}. This was not granted by this project's access list."
                ),
            },
        )

    def note_listing(self, identity: Identity, count: int) -> None:
        """A list that included projects only emergency access could see."""
        if count:
            emit(
                SecurityEvent.ACCESS_BREAKGLASS,
                f"access.breakglass actor={identity.id!r} action=list count={count}",
                actor=identity.id,
                action="list",
                count=count,
            )
