"""Build manifests for the retirement-rule tests, with the build's own code.

The manifests are written by ``scripts/build_manifest.py``, the module
``scripts/build_app.py`` writes ``docs/app/manifest.json`` with, so a test of the
server's side also shows the two sides compute the same hashes. Two definitions:
CHAI's, as the default build embeds it, and a stand-in primary whose checkpoints and
words share nothing with CHAI's.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import UTC
from pathlib import Path
from typing import NamedTuple

import asyncpg

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
DEFAULT_MANIFEST = ROOT / "docs" / "app" / "manifest.json"
FRAMEWORKS = ROOT / "app" / "frameworks"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build_manifest = _load("build_manifest", ROOT / "scripts" / "build_manifest.py")
framework_enums = sys.modules["framework_enums"]
GateClass = framework_enums.GateClass
ENDING_CLASSES = framework_enums.ENDING_CLASSES


def definition(fid: str) -> dict:
    return json.loads((FRAMEWORKS / fid / "framework.json").read_text(encoding="utf-8"))


# A primary that is not CHAI: other checkpoint ids, other words, and an ending option
# at a checkpoint that is not the last. Only what the manifest reads is needed.
STAND_IN = {
    "id": "acme",
    "version": "3",
    "role": "primary",
    "gates": [
        {
            "id": "intake",
            "options": [
                {"value": "Approve", "class": "go"},
                {"value": "Approve with limits", "class": "conditional"},
                {"value": "Rework", "class": "revise"},
                {"value": "Reject", "class": "stop"},
            ],
        },
        {
            "id": "go-live",
            "options": [
                {"value": "Launch", "class": "go"},
                {"value": "Hold back", "class": "revise"},
                {"value": "Abandon", "class": "stop"},
            ],
        },
        {
            "id": "annual",
            "options": [
                {"value": "Keep", "class": "go"},
                {"value": "Keep, retrain", "class": "conditional"},
                {"value": "Decommission", "class": "retire"},
            ],
        },
    ],
}


def default_build() -> dict[str, dict]:
    return {"chai": definition("chai"), "optica": definition("optica")}


def chai_with(gate: str, value: str, cls: str) -> dict[str, dict]:
    """The default build with one more option on one of CHAI's checkpoints."""
    defs = default_build()
    chai = copy.deepcopy(defs["chai"])
    next(g for g in chai["gates"] if g["id"] == gate)["options"].append(
        {"value": value, "class": cls}
    )
    defs["chai"] = chai
    return defs


def write(path: Path, defs: dict[str, dict], primary: str) -> Path:
    path.write_text(build_manifest.manifest_json(defs, primary), encoding="utf-8")
    return path


def manifest_of(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pairs(defs: dict[str, dict]) -> set[tuple[str, str, str]]:
    """Every (framework, gate, decision) the definitions end a project on."""
    return {
        (fid, gate["id"], option["value"])
        for fid, d in defs.items()
        for gate in d.get("gates", [])
        for option in gate["options"]
        if GateClass(option["class"]) in ENDING_CLASSES
    }


def run_migrate(db_url: str, **env: str) -> subprocess.CompletedProcess:
    """``python -m app.migrate`` for real, as the owner, with only ``env`` set."""
    return subprocess.run(
        [sys.executable, "-m", "app.migrate"],
        capture_output=True,
        text=True,
        cwd=SERVER,
        env={
            **{
                k: v
                for k, v in os.environ.items()
                if not k.startswith(
                    ("POSTGRES_", "DATABASE_", "APP_POSTGRES", "RETIREMENT_", "LOG_")
                )
            },
            "DATABASE_URL": db_url,
            "MIGRATE_CONNECT_RETRIES": "2",
            **env,
        },
    )


# The rule-set hash 010 records for its seed: CHAI's four rows, which is also the
# default build's (test_retirement_rules.py holds the two equal).
SEED_HASH = re.search(
    r"'([0-9a-f]{64})'",
    (SERVER / "migrations" / "010_retirement_rules.sql").read_text(encoding="utf-8"),
).group(1)  # type: ignore[union-attr]


Rules = set[tuple[str, str, str]]


class Follows(NamedTuple):
    """Where a change starts: the database's identity (012) and the id and time of
    the latest history row."""

    database: dict
    change_id: int
    at: str


async def identity(conn: asyncpg.Connection) -> dict:
    """The database's identity as the acknowledgment states it, read straight from
    the catalogs rather than through 012's function: the cluster's system
    identifier, the database's OID and the OID of retirement_rule_change."""
    row = await conn.fetchrow(
        "SELECT (SELECT system_identifier FROM pg_control_system()) AS cluster,"
        " (SELECT oid FROM pg_database WHERE datname = current_database()) AS database,"
        " (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        "   WHERE c.relname = 'retirement_rule_change'"
        "     AND n.nspname = current_schema()) AS history"
    )
    return {
        "cluster": str(row["cluster"]),
        "database": int(row["database"]),
        "history": int(row["history"]),
    }


async def follows(db_url: str, change_id: int) -> Follows:
    """The point in this database's history a change made now follows, read
    straight from the tables. `change_id` is the history row the test expects to
    be the latest, checked, so a test still says which point it means."""
    conn = await asyncpg.connect(db_url)
    try:
        database = await identity(conn)
        row = await conn.fetchrow(
            "SELECT id, at FROM retirement_rule_change ORDER BY id DESC LIMIT 1"
        )
    finally:
        await conn.close()
    assert row["id"] == change_id, (row["id"], change_id)
    at = row["at"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return Follows(database, change_id, at)


def transition(
    follows: Follows,
    before: tuple[str, Rules],
    after: tuple[str, Rules],
) -> str:
    """The acknowledgment a change of retirement rules needs (D-76): SHA-256 of the
    canonical JSON {"database": {"cluster": <system identifier, text>, "database":
    <the database's OID>, "history": <retirement_rule_change's OID>}, "follows":
    <the latest history row's id>, "at": <its time, UTC, microseconds, "Z">, "before":
    {"primary", "rules"}, "after": {"primary", "rules"}}, each rule list every row of
    retirement_rule, sorted. ``before`` and ``after`` are (primary, rules). Written
    here independently of app.retirement, so the format is pinned by the test rather
    than echoed from the code under test."""

    def state(primary: str, rules: Rules) -> dict:
        return {"primary": primary, "rules": sorted(list(r) for r in rules)}

    text = json.dumps(
        {
            "database": follows.database,
            "follows": follows.change_id,
            "at": follows.at,
            "before": state(*before),
            "after": state(*after),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rules_of(path: Path) -> Rules:
    """Every (framework, gate, decision) a manifest lists."""
    return {
        (f["id"], p["gate"], p["decision"])
        for f in manifest_of(path)["frameworks"]
        for p in f["retire"]
    }


# 010's seed: CHAI's four rules, which are the default build's.
CHAI_RULES: Rules = {("chai", "A", "Stop"), ("chai", "B", "Stop"),
                     ("chai", "C", "Stop"), ("chai", "D", "Retire")}  # fmt: skip


def events(done: subprocess.CompletedProcess, name: str) -> list[dict]:
    """The security events the job wrote, one JSON object per line."""
    found = []
    for line in done.stdout.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == name:
            found.append(record)
    return found
