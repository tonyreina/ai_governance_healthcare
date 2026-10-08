"""The read trail: who opened which governance record (#33).

Every read route used to return data and write nothing, and exports never touched
the server, so "account X was compromised; which records did it open, and did it
export any?" had no answer anywhere. 45 CFR 164.312(b), audit controls, is a
*required* standard.

``record_access`` writes one row to ``access_event`` and emits the same fact as a
security event. It is called INSIDE the transaction of the read it describes, so a read
that cannot be recorded is not served (the database error rolls it back, and the request
fails), and there is never a record of a read that did not happen.

What it does NOT cover, so nobody over-reads it: exports are produced in the browser
from data it already fetched, so the export beacon is a record of ordinary use, not a
control; a client can omit it. The reads that fetched the data are recorded, and they
bound what any export could have contained.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

import asyncpg
from fastapi import Request

from .auth import Identity
from .securitylog import SecurityEvent, emit


class AccessAction(StrEnum):
    LIST = "list"  # GET /api/projects: every project the caller could see
    READ_VERSIONS = "read_versions"  # a project's list of revisions
    READ_VERSION = "read_version"  # one full historical snapshot
    READ_LOG = "read_log"  # a project's audit log
    EXPORT = "export"  # the dashboard reports it produced a download
    STREAM_ATTACH = "stream_attach"  # an event stream opened


class ExportFormat(StrEnum):
    """What the dashboard can produce for one project."""

    MARKDOWN = "md"
    HTML = "html"
    PDF = "pdf"
    JSON = "json"
    CSV = "csv"  # the whole portfolio, not one project


def source_of(request: Request) -> str:
    """The client address the PROXY reported, for correlation only.

    Behind the proxy ``request.client`` is the proxy itself. ``X-Real-IP`` is set by it
    (proxy/Caddyfile) and is informational: nothing authorizes on it, and a request that
    reached the API without the proxy is a different finding (``auth.no_identity``).
    """
    reported = (request.headers.get("x-real-ip") or "").strip()
    if reported:
        return reported[:64]
    return request.client.host if request.client else ""


_EVENT_FOR: dict[AccessAction, SecurityEvent] = {
    AccessAction.EXPORT: SecurityEvent.RECORD_EXPORTED,
    AccessAction.STREAM_ATTACH: SecurityEvent.STREAM_ATTACHED,
}


async def record_access(
    conn: asyncpg.Connection,
    identity: Identity,
    action: AccessAction,
    request: Request,
    *,
    project_id: str | None = None,
    revision: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Record one access. Raises if it cannot, which fails the read it belongs to."""
    source = source_of(request)
    detail = detail or {}
    await conn.execute(
        """
        INSERT INTO access_event
               (actor, action, project_id, revision, source_ip, detail)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        identity.id,
        action.value,
        project_id,
        revision,
        source,
        detail,
    )
    fields: dict[str, Any] = {
        "actor": identity.id,
        "action": action.value,
        "project": project_id,
        "revision": revision,
        "source_ip": source,
    }
    fields.update({k: v for k, v in detail.items() if k not in fields})
    emit(
        _EVENT_FOR.get(action, SecurityEvent.RECORD_READ),
        f"{action.value} by {identity.id}"
        + (f" on {project_id}" if project_id else ""),
        level=logging.INFO,
        **fields,
    )
