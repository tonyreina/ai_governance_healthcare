"""Pydantic models for the API surface.

The project document itself is deliberately *not* modeled field by field. The
store contract says to treat it as opaque JSON, and the browser owns its schema
(``schema/project.schema.json``). Validating it here would mean a server
deploy every time the checklist grows a field.

What is modeled is the envelope: that a body is a JSON object, that a patch is
not empty, and that a log entry carries text.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from .retention import HoldAction
from .roles import DbRole


class HealthStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


class EventDelivery(StrEnum):
    LIVE = "live"
    LOCAL_ONLY = "local-only"


class RetirementRulesOut(BaseModel):
    """What ``/api/health`` says about the retirement rules (D-76, R-66)."""

    hash: str = Field(
        description=(
            "SHA-256 of the active rule set: the primary framework's decisions that "
            "end a project, as the build's manifest.json states them "
            "(ruleSetHash). The page built with the same definition carries the "
            "same hash."
        )
    )
    primary: str = Field(
        description=(
            "The primary framework the latest sync recorded: the only framework id "
            "a record may be stamped with (meta.framework)."
        )
    )
    synced: bool = Field(
        description=(
            "True once a build's manifest set or confirmed the rules. False while "
            "the database holds only 010's seed (CHAI's rules), which is what an "
            "API that migrates itself with no RETIREMENT_MANIFEST leaves."
        )
    )


class HealthOut(BaseModel):
    """``GET /api/health`` -- unauthenticated, for load balancer probes."""

    status: HealthStatus = HealthStatus.OK
    events: EventDelivery = Field(
        default=EventDelivery.LIVE,
        description=(
            "'local-only' when LISTEN is not established, so changes written by "
            "another replica do not reach this one's streams. Degraded, not down."
        ),
    )
    version: str
    database: str = Field(description="'up' or 'down'")
    db_role: DbRole = Field(
        default=DbRole.OWNER,
        description=(
            "'restricted' when the API connects as a role that cannot disable the "
            "append-only triggers; 'owner' when it owns the tables or is a "
            "superuser, so those guarantees bind its bugs and not the application."
        ),
    )
    idle_lock_minutes: int = Field(
        default=0,
        description="Minutes of inactivity before the dashboard locks. 0 is off.",
    )
    sign_out_url: str = Field(
        default="",
        description="Where the front door ends a session; empty means no link.",
    )
    auth_mode: str = Field(
        description="'proxy-header' in a real deployment, 'DEV-INSECURE' otherwise"
    )
    retirement_rules: RetirementRulesOut | None = Field(
        default=None,
        description=(
            "The retirement rules the database decides disposal by (D-76). Null "
            "when they cannot be read."
        ),
    )


class MeOut(BaseModel):
    """``GET /api/me`` -- who the proxy says this request is from."""

    id: str
    name: str
    email: str
    dev: bool = Field(
        default=False,
        description="True when DEV_INSECURE_AUTH is on and this identity is fake.",
    )


class ProjectOut(BaseModel):
    """One project: its id, with the stored document spread alongside.

    Matches what ``subscribeAll`` hands the app: ``{id, ...project}``.
    """

    model_config = ConfigDict(extra="allow")

    id: str

    @classmethod
    def from_row(cls, project_id: str, doc: dict[str, Any]) -> ProjectOut:
        fields = {k: v for k, v in doc.items() if k != "id"}
        return cls(id=project_id, **fields)


class JsonObject(RootModel[dict[str, Any]]):
    """A request body that must be a JSON object."""

    root: dict[str, Any]


class ProjectCreate(JsonObject):
    """``POST /api/projects/{id}`` body: the whole initial document."""


class ProjectPatch(JsonObject):
    """``PATCH /api/projects/{id}`` body: a nested partial, deep-merged in."""

    @field_validator("root")
    @classmethod
    def not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("patch body is empty; nothing to merge")
        return value


class LogEntryIn(BaseModel):
    """``POST /api/projects/{id}/log`` body.

    ``at`` and ``by`` are accepted because the browser sends them, but both are
    **overwritten** on write: ``at`` with the server clock and ``by`` with the
    proxy identity. An audit log whose author and timestamp come from the
    client is not an audit log.
    """

    model_config = ConfigDict(extra="allow")

    text: str = Field(min_length=1, max_length=4000)
    at: str | None = None
    by: str | None = None


class LogEntryOut(BaseModel):
    """One stored audit entry, newest first in ``GET .../log``."""

    model_config = ConfigDict(extra="allow")

    at: str
    by: str | None = None
    text: str


class PrincipalOut(BaseModel):
    """A person an identity id stands for, as the proxy last asserted them."""

    id: str
    name: str = ""
    email: str = ""


class ErrorOut(BaseModel):
    detail: str


class HoldIn(BaseModel):
    """``POST /api/projects/{id}/hold``: place or lift a litigation hold (#57).

    The reason is required, because a hold that nobody can explain later is one
    nobody dares lift. It stays with the hold; the project's log says only that a
    hold changed.
    """

    model_config = ConfigDict(extra="forbid")

    action: HoldAction
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _reason_has_words(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a hold needs a reason")
        return value


class HoldEntryOut(BaseModel):
    at: str
    by: str
    action: HoldAction
    reason: str


class HoldOut(BaseModel):
    """Whether the project is held now, and every placing and lifting, newest first."""

    held: bool
    history: list[HoldEntryOut]
