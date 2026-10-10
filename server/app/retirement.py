"""Which decisions end a project, from the build's own framework definition (R-66).

``retention_due()`` starts a project's retention clock when it is retired (R-56),
and what counts as retired is a property of the framework the dashboard was built
with: a checkpoint option whose class is ``stop`` or ``retire``. The build writes
those pairs into ``docs/app/manifest.json`` (``scripts/build_app.py``) from the same
definitions the page embeds, and the migrate job loads them into ``retirement_rule``
here, as the database owner, under the migration lock (D-76).

The sync never changes disposal silently:

* a pair the manifest adds is inserted;
* a pair the manifest no longer has is removed only when ``RETIREMENT_RULES_ACK``
  equals the new rule set's hash. Otherwise the job refuses, names the projects
  whose disposal would change, and exits non-zero, so an older manifest cannot
  quietly undo a newer one;
* a missing or malformed manifest, or a primary with nothing that ends a project,
  fails the job. There is no fallback to CHAI's rules or to the table as it stands.

Every change is a row in the append-only ``retirement_rule_change`` and a security
event.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple

import asyncpg

from .db import MIGRATION_LOCK_ID
from .securitylog import SecurityEvent, emit

MANIFEST_FORMAT = 1
# A record with no meta.framework.id is CHAI's: every record written before records
# were stamped is. 010_retirement_rules.sql's record_framework() says the same.
UNSTAMPED_FRAMEWORK = "chai"
# The definition's id pattern (schema/framework.schema.json), for frameworks and gates.
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_DECISION = 200
MAX_LISTED = 50

log = logging.getLogger("chai.retirement")


class FrameworkRole(StrEnum):
    """A framework's role in a build (schema/framework.schema.json)."""

    PRIMARY = "primary"
    SUPPLEMENT = "supplement"


class ChangeSource(StrEnum):
    """Who wrote a ``retirement_rule_change`` row. The CHECK constraint in 010 lists
    the same values, and ``tests/test_retention.py`` fails if the two drift."""

    SEED = "seed"
    MANIFEST = "manifest"


class SyncOutcome(StrEnum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"


class ManifestError(ValueError):
    """The manifest is missing or is not one this server will act on."""


class RulesRefused(RuntimeError):
    """The manifest removes a rule and the removal was not acknowledged."""


class Rule(NamedTuple):
    framework_id: str
    gate_id: str
    decision: str


@dataclass(frozen=True)
class FrameworkEntry:
    id: str
    role: FrameworkRole
    version: str
    sha256: str
    retire: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class Manifest:
    primary: str
    frameworks: tuple[FrameworkEntry, ...]
    rule_set_hash: str

    @property
    def primary_entry(self) -> FrameworkEntry:
        return next(f for f in self.frameworks if f.id == self.primary)

    def rules(self) -> frozenset[Rule]:
        return frozenset(
            Rule(f.id, gate, decision)
            for f in self.frameworks
            for gate, decision in f.retire
        )


@dataclass(frozen=True)
class SyncResult:
    outcome: SyncOutcome
    added: frozenset[Rule]
    removed: frozenset[Rule]
    rule_set_hash: str


def canonical_json(value: object) -> bytes:
    """Sorted keys, no spaces, UTF-8: what scripts/build_app.py hashes."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def rule_set_hash(framework_id: str, pairs: frozenset[tuple[str, str]] | set) -> str:
    """SHA-256 of a framework's retirement rules, as scripts/build_manifest.py does."""
    rules = sorted([gate, decision] for gate, decision in pairs)
    return hashlib.sha256(
        canonical_json({"framework": framework_id, "retire": rules})
    ).hexdigest()


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise ManifestError(why)


def _keys(obj: dict, required: set[str], where: str) -> None:
    _need(isinstance(obj, dict), f"{where} is not an object")
    extra = set(obj) - required
    missing = required - set(obj)
    _need(not missing, f"{where} lacks {sorted(missing)}")
    _need(not extra, f"{where} has unknown keys {sorted(extra)}")


def _id(value: Any, where: str) -> str:
    _need(
        isinstance(value, str) and bool(_ID.fullmatch(value)), f"{where} is not an id"
    )
    return value


def parse_manifest(text: str) -> Manifest:
    """Read and check a manifest. Strict: an unknown key, a bad id, a pair on a
    supplement, a primary that ends nothing or a hash that does not match its pairs
    is an error, because acting on a manifest misread is changing disposal."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"the manifest is not JSON: {exc}") from exc
    _keys(raw, {"manifest", "primary", "frameworks", "ruleSetHash"}, "the manifest")
    _need(
        raw["manifest"] == MANIFEST_FORMAT and type(raw["manifest"]) is int,
        f"the manifest format is {raw['manifest']!r}, not {MANIFEST_FORMAT}",
    )
    primary = _id(raw["primary"], "primary")
    _need(
        isinstance(raw["frameworks"], list) and bool(raw["frameworks"]),
        "frameworks is not a non-empty list",
    )
    entries: list[FrameworkEntry] = []
    for i, f in enumerate(raw["frameworks"]):
        where = f"frameworks[{i}]"
        _keys(f, {"id", "role", "version", "sha256", "retire"}, where)
        fid = _id(f["id"], f"{where}.id")
        try:
            role = FrameworkRole(f["role"])
        except ValueError as exc:
            raise ManifestError(f"{where}.role is {f['role']!r}") from exc
        _need(
            isinstance(f["version"], str) and bool(f["version"].strip()),
            f"{where}.version is not text",
        )
        _need(
            isinstance(f["sha256"], str) and bool(_SHA256.fullmatch(f["sha256"])),
            f"{where}.sha256 is not a SHA-256",
        )
        _need(isinstance(f["retire"], list), f"{where}.retire is not a list")
        pairs: set[tuple[str, str]] = set()
        for j, pair in enumerate(f["retire"]):
            at = f"{where}.retire[{j}]"
            _keys(pair, {"gate", "decision"}, at)
            gate = _id(pair["gate"], f"{at}.gate")
            decision = pair["decision"]
            _need(
                isinstance(decision, str)
                and bool(decision.strip())
                and len(decision) <= MAX_DECISION
                and not _CONTROL.search(decision),
                f"{at}.decision is not a decision",
            )
            _need((gate, decision) not in pairs, f"{at} is listed twice")
            pairs.add((gate, decision))
        if role is FrameworkRole.SUPPLEMENT:
            _need(not pairs, f"{where} is a supplement and cannot end a project")
        entries.append(
            FrameworkEntry(fid, role, f["version"], f["sha256"], frozenset(pairs))
        )
    ids = [e.id for e in entries]
    _need(len(set(ids)) == len(ids), "a framework is listed twice")
    primaries = [e.id for e in entries if e.role is FrameworkRole.PRIMARY]
    _need(
        primaries == [primary],
        f"primary is {primary!r} but the primaries listed are {primaries}",
    )
    manifest = Manifest(primary, tuple(entries), raw["ruleSetHash"])
    _need(
        bool(manifest.primary_entry.retire),
        f"the primary framework {primary!r} has no decision that ends a project, so "
        "no record of it could ever come due for disposal (R-56)",
    )
    _need(
        raw["ruleSetHash"] == rule_set_hash(primary, manifest.primary_entry.retire),
        "ruleSetHash does not match the primary's retirement pairs",
    )
    return manifest


def load_manifest(path: str | None) -> Manifest:
    """The manifest at ``path``. Unset, missing or unreadable is an error."""
    if not path:
        raise ManifestError(
            "RETIREMENT_MANIFEST is not set. It names the build's manifest.json "
            "(compose mounts ${APP_DIR}/manifest.json), which says which decisions "
            "end a project; without it the server cannot know when disposal is due."
        )
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read the manifest {path}: {exc}") from exc
    return parse_manifest(text)


def _arrays(rules: frozenset[Rule]) -> tuple[list[str], list[str], list[str]]:
    ordered = sorted(rules)
    return (
        [r.framework_id for r in ordered],
        [r.gate_id for r in ordered],
        [r.decision for r in ordered],
    )


def _as_json(rules: frozenset[Rule]) -> list[list[str]]:
    return [list(r) for r in sorted(rules)]


async def affected_projects(
    conn: asyncpg.Connection, before: frozenset[Rule], after: frozenset[Rule]
) -> list[asyncpg.Record]:
    """Every live project whose retirement changes between the two rule sets, and
    whether disposal is due for it now and after, through the same retired_under()
    that retention_due() uses."""
    return await conn.fetch(
        """
        WITH keep AS (
            SELECT make_interval(years => record_years) AS k FROM retention_policy
        ),
        before AS (SELECT * FROM retired_under($1::text[], $2::text[], $3::text[])),
        after AS (SELECT * FROM retired_under($4::text[], $5::text[], $6::text[]))
        SELECT coalesce(b.project_id, a.project_id) AS project_id,
               coalesce(b.clock_start + keep.k <= now(), false) AS due_before,
               coalesce(a.clock_start + keep.k <= now(), false) AS due_after
          FROM before b
          FULL JOIN after a
            ON a.project_id = b.project_id AND a.incarnation = b.incarnation
         CROSS JOIN keep
         WHERE b.clock_start IS DISTINCT FROM a.clock_start
         ORDER BY 1
        """,
        *_arrays(before),
        *_arrays(after),
    )


def _refusal(removed: frozenset[Rule], manifest: Manifest, affected: list) -> str:
    due_changes = [r for r in affected if r["due_before"] != r["due_after"]]
    lines = [
        "the manifest removes retirement rule(s) the database holds:",
        *(
            f"  {r.framework_id}: checkpoint {r.gate_id} decided {r.decision!r}"
            for r in sorted(removed)
        ),
        f"{len(affected)} live project(s) would change when they retire; "
        f"{len(due_changes)} would change whether disposal is due now:",
        *(
            f"  {r['project_id']}: due now {r['due_before']} -> {r['due_after']}"
            for r in due_changes[:MAX_LISTED]
        ),
    ]
    if len(due_changes) > MAX_LISTED:
        lines.append(f"  ... and {len(due_changes) - MAX_LISTED} more")
    lines.append(
        "Nothing was changed. If this build is meant to stop retiring on those "
        "decisions, run the migrate job again with "
        f"RETIREMENT_RULES_ACK={manifest.rule_set_hash}"
    )
    return "\n".join(lines)


async def active_rule_set_hash(conn: asyncpg.Connection) -> str | None:
    """The rule-set hash of the latest change: what the database retires by."""
    return await conn.fetchval(
        "SELECT rule_set_hash FROM retirement_rule_change ORDER BY id DESC LIMIT 1"
    )


async def sync_rules(
    conn: asyncpg.Connection, manifest: Manifest, ack: str = ""
) -> SyncResult:
    """Make ``retirement_rule`` say what the manifest says, additively.

    Runs as the owner in one transaction under the migration lock, so two migrate
    jobs cannot interleave and a refused sync changes nothing.
    """
    acknowledged = bool(ack) and ack == manifest.rule_set_hash
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", MIGRATION_LOCK_ID)
        current = frozenset(
            Rule(*r)
            for r in await conn.fetch(
                "SELECT framework_id, gate_id, decision FROM retirement_rule"
            )
        )
        desired = manifest.rules()
        added, removed = desired - current, current - desired
        if removed and not acknowledged:
            affected = await affected_projects(conn, current, desired)
            message = _refusal(removed, manifest, affected)
            emit(
                SecurityEvent.RETIREMENT_RULES_REFUSED,
                f"retirement rules not changed: {len(removed)} removal(s) "
                "not acknowledged",
                framework=manifest.primary,
                removed=_as_json(removed),
                projects=len(affected),
                rule_set_hash=manifest.rule_set_hash,
            )
            raise RulesRefused(message)
        latest = await active_rule_set_hash(conn)
        if not added and not removed and latest == manifest.rule_set_hash:
            return SyncResult(SyncOutcome.UNCHANGED, added, removed, latest)
        for r in removed:
            await conn.execute(
                "DELETE FROM retirement_rule"
                " WHERE framework_id = $1 AND gate_id = $2 AND decision = $3",
                *r,
            )
        for r in added:
            await conn.execute(
                "INSERT INTO retirement_rule (framework_id, gate_id, decision)"
                " VALUES ($1, $2, $3)",
                *r,
            )
        await conn.execute(
            "INSERT INTO retirement_rule_change (source, framework_id, old_rules,"
            " new_rules, rule_set_hash, definition_hash, acknowledged)"
            " VALUES ($1, $2, $3::text::jsonb, $4::text::jsonb, $5, $6, $7)",
            ChangeSource.MANIFEST.value,
            manifest.primary,
            json.dumps(_as_json(current)),
            json.dumps(_as_json(desired)),
            manifest.rule_set_hash,
            manifest.primary_entry.sha256,
            bool(removed) and acknowledged,
        )
    emit(
        SecurityEvent.RETIREMENT_RULES_CHANGED,
        f"retirement rules changed: {len(added)} added, {len(removed)} removed",
        framework=manifest.primary,
        added=_as_json(added),
        removed=_as_json(removed),
        acknowledged=bool(removed) and acknowledged,
        rule_set_hash=manifest.rule_set_hash,
    )
    return SyncResult(SyncOutcome.CHANGED, added, removed, manifest.rule_set_hash)
