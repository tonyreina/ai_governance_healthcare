"""The retirement rules: the manifest the server reads, who may change the rules, and
what /api/health reports (#168 PR C; R-66, D-76).

What disposal does with the rules is in ``test_retention.py``. This covers the edges:
that a manifest the server would misread is refused, never half-read; that the
migrate job fails closed without one; that the API's role can read the rules and not
change them; that their history cannot be edited even by the owner; and that
``/api/health`` reports the rule set the database is using.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import asyncpg
import pytest
from app.retirement import (
    ChangeSource,
    ManifestError,
    load_manifest,
    parse_manifest,
    rule_set_hash,
)
from httpx import AsyncClient

from . import manifests
from .conftest import APP_ROLE_URL, DB_URL, owner_connection, requires_db

MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "010_retirement_rules.sql"
).read_text(encoding="utf-8")
CHAI_SEED = {("A", "Stop"), ("B", "Stop"), ("C", "Stop"), ("D", "Retire")}


def seed_hash() -> str:
    found = re.search(r"'([0-9a-f]{64})'", MIGRATION)
    assert found is not None
    return found.group(1)


# --- the manifest, without a database ------------------------------------------


def test_the_default_manifest_is_what_the_build_writes_and_what_010_seeds() -> None:
    text = manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8")
    assert text == manifests.build_manifest.manifest_json(
        manifests.default_build(), "chai"
    )
    parsed = parse_manifest(text)
    assert parsed.primary == "chai"
    assert parsed.primary_entry.retire == CHAI_SEED
    # The build's hash, the server's hash and the seed's hash are one hash.
    assert parsed.rule_set_hash == rule_set_hash("chai", CHAI_SEED) == seed_hash()


def test_the_server_and_the_build_hash_a_stand_in_alike(tmp_path: Path) -> None:
    path = manifests.write(tmp_path / "m.json", {"acme": manifests.STAND_IN}, "acme")
    parsed = load_manifest(str(path))
    assert parsed.rules() == {
        (f, g, d) for f, g, d in manifests.pairs({"acme": manifests.STAND_IN})
    }
    assert parsed.rule_set_hash == rule_set_hash("acme", parsed.primary_entry.retire)


def mutated(change) -> str:
    raw = json.loads(manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    change(raw)
    return json.dumps(raw)


def chai_entry(raw: dict) -> dict:
    return raw["frameworks"][0]


def rehash(raw: dict) -> None:
    """Recompute the hash, so a mutation is refused for itself, not for the hash."""
    retire = {(p["gate"], p["decision"]) for p in chai_entry(raw)["retire"]}
    raw["ruleSetHash"] = rule_set_hash(raw["primary"], retire)


MALFORMED = {
    "not JSON": lambda: "{",
    "a list": lambda: "[]",
    "an unknown key": lambda: mutated(lambda r: r.update(extra=1)),
    "a missing key": lambda: mutated(lambda r: r.pop("ruleSetHash")),
    "another format": lambda: mutated(lambda r: r.update(manifest=2)),
    "the format as text": lambda: mutated(lambda r: r.update(manifest="1")),
    "a primary not listed": lambda: mutated(lambda r: r.update(primary="other")),
    "two primaries": lambda: mutated(
        lambda r: r["frameworks"][1].update(role="primary")
    ),
    "an unknown role": lambda: mutated(lambda r: chai_entry(r).update(role="main")),
    "a framework listed twice": lambda: mutated(
        lambda r: r["frameworks"].append(dict(r["frameworks"][1]))
    ),
    "a supplement that ends a project": lambda: mutated(
        lambda r: r["frameworks"][1]["retire"].append({"gate": "X", "decision": "Y"})
    ),
    "a primary that ends nothing": lambda: mutated(
        lambda r: (chai_entry(r).update(retire=[]), rehash(r))
    ),
    "a gate id with a dot": lambda: mutated(
        lambda r: (chai_entry(r)["retire"][0].update(gate="A.b"), rehash(r))
    ),
    "a gate id with a space": lambda: mutated(
        lambda r: (chai_entry(r)["retire"][0].update(gate="A b"), rehash(r))
    ),
    "a blank decision": lambda: mutated(
        lambda r: (chai_entry(r)["retire"][0].update(decision="  "), rehash(r))
    ),
    "a decision with a control character": lambda: mutated(
        lambda r: (chai_entry(r)["retire"][0].update(decision="Stop\n"), rehash(r))
    ),
    "a decision that is not text": lambda: mutated(
        lambda r: chai_entry(r)["retire"][0].update(decision=1)
    ),
    "a pair listed twice": lambda: mutated(
        lambda r: chai_entry(r)["retire"].append(dict(chai_entry(r)["retire"][0]))
    ),
    "a definition hash that is not one": lambda: mutated(
        lambda r: chai_entry(r).update(sha256="abc")
    ),
    "a rule-set hash that does not match its pairs": lambda: mutated(
        lambda r: chai_entry(r)["retire"].pop()
    ),
    "a rule-set hash for another framework": lambda: mutated(
        lambda r: r.update(
            ruleSetHash=rule_set_hash(
                "optica", {(p["gate"], p["decision"]) for p in chai_entry(r)["retire"]}
            )
        )
    ),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_a_manifest_the_server_would_misread_is_refused(case: str) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(MALFORMED[case]())


def test_the_mutations_start_from_a_manifest_that_parses() -> None:
    # Without this, every case above could pass by refusing everything.
    parse_manifest(mutated(lambda r: None))
    parse_manifest(mutated(rehash))


def test_no_manifest_is_an_error_not_a_fallback(tmp_path: Path) -> None:
    for path in (None, "", str(tmp_path / "absent.json"), str(tmp_path)):
        with pytest.raises(ManifestError):
            load_manifest(path)


def test_the_change_sources_match_the_check_constraint() -> None:
    check = re.search(r"source IN \(([^)]*)\)", MIGRATION)
    assert check is not None
    assert set(re.findall(r"'(\w+)'", check.group(1))) == {
        s.value for s in ChangeSource
    }


# --- the migrate job fails closed ------------------------------------------------


async def rules_now() -> set[tuple[str, str, str]]:
    async with owner_connection() as conn:
        return {
            tuple(r)
            for r in await conn.fetch(
                "SELECT framework_id, gate_id, decision FROM retirement_rule"
            )
        }


async def changes() -> int:
    async with owner_connection() as conn:
        return await conn.fetchval("SELECT count(*) FROM retirement_rule_change")


WHY = {
    "unset": "RETIREMENT_MANIFEST is not set",
    "absent": "cannot read the manifest",
    "malformed": "not JSON",
    "ends nothing": "no decision that ends a project",
    "a supplement only": "the primaries listed are []",
}


@requires_db
@pytest.mark.parametrize("case", sorted(WHY))
async def test_the_migrate_job_fails_closed_without_a_usable_manifest(
    client: AsyncClient, tmp_path: Path, case: str
) -> None:
    path = tmp_path / "manifest.json"
    if case == "malformed":
        path.write_text('{"manifest": 1, "primary": "chai"', encoding="utf-8")
    elif case == "ends nothing":
        # The build never writes one (test below), so it is written by hand.
        raw = manifests.build_manifest.manifest({"acme": manifests.STAND_IN}, "acme")
        raw["frameworks"][0]["retire"] = []
        path.write_text(json.dumps(raw), encoding="utf-8")
    elif case == "a supplement only":
        raw = manifests.build_manifest.manifest(manifests.default_build(), "chai")
        raw["frameworks"] = raw["frameworks"][1:]
        path.write_text(json.dumps(raw), encoding="utf-8")
    env = {} if case == "unset" else {"RETIREMENT_MANIFEST": str(path)}
    before = await rules_now()
    done = manifests.run_migrate(DB_URL, **env)
    assert done.returncode == 1, done.stdout + done.stderr
    assert WHY[case] in done.stderr, done.stderr
    assert await rules_now() == before
    assert await changes() == 1  # the seed's, and nothing more


def test_the_build_refuses_a_primary_that_ends_nothing() -> None:
    # The same guard on the build's side: such a manifest is never written.
    stopped = manifests.STAND_IN | {
        "gates": [{"id": "intake", "options": [{"value": "Approve", "class": "go"}]}]
    }
    with pytest.raises(SystemExit, match="no stop or retire"):
        manifests.build_manifest.manifest({"acme": stopped}, "acme")


# --- who may change them ---------------------------------------------------------


@requires_db
async def test_the_api_role_can_read_the_rules_and_not_change_them(
    client: AsyncClient,
) -> None:
    conn = await asyncpg.connect(APP_ROLE_URL)
    try:
        assert len(await conn.fetch("SELECT * FROM retirement_rule")) == 4
        assert await conn.fetchval("SELECT count(*) FROM retirement_rule_change") == 1
        for sql in [
            "INSERT INTO retirement_rule VALUES ('chai', 'A', 'Proceed')",
            "UPDATE retirement_rule SET decision = 'Proceed'",
            "DELETE FROM retirement_rule",
            "TRUNCATE retirement_rule",
            "INSERT INTO retirement_rule_change (source, framework_id, old_rules,"
            " new_rules, rule_set_hash) VALUES ('manifest', 'x', '[]', '[]',"
            f" '{'0' * 64}')",
            "UPDATE retirement_rule_change SET rule_set_hash = 'x'",
            "DELETE FROM retirement_rule_change",
            "TRUNCATE retirement_rule_change",
        ]:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(sql)
    finally:
        await conn.close()
    assert await rules_now() == {("chai", g, d) for g, d in CHAI_SEED}


@requires_db
async def test_the_rules_history_is_append_only_even_for_the_owner(
    client: AsyncClient,
) -> None:
    async with owner_connection() as conn:
        for sql in [
            "UPDATE retirement_rule_change SET changed_by = 'someone else'",
            "DELETE FROM retirement_rule_change",
        ]:
            with pytest.raises(asyncpg.RestrictViolationError, match="append-only"):
                await conn.execute(sql)
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO retirement_rule VALUES ('chai', 'A b', 'Stop')"
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO retirement_rule_change (source, framework_id, old_rules,"
                " new_rules, rule_set_hash) VALUES ('hand', 'x', '[]', '[]',"
                f" '{'0' * 64}')"
            )


# --- /api/health -------------------------------------------------------------------


@requires_db
async def test_health_reports_the_rule_set_the_database_uses(
    client: AsyncClient, tmp_path: Path
) -> None:
    body = (await client.get("/api/health")).json()
    assert body["retirement_rules"] == seed_hash()
    # Everything it reported before is still there.
    assert {"status", "events", "version", "database", "db_role",
            "idle_lock_minutes", "sign_out_url", "auth_mode"} <= set(body)  # fmt: skip

    path = manifests.write(tmp_path / "m.json", {"acme": manifests.STAND_IN}, "acme")
    wanted = manifests.manifest_of(path)["ruleSetHash"]
    done = manifests.run_migrate(
        DB_URL, RETIREMENT_MANIFEST=str(path), RETIREMENT_RULES_ACK=wanted
    )
    assert done.returncode == 0, done.stdout + done.stderr
    client.app.state.db._rules_cache = None  # type: ignore[attr-defined]
    body = (await client.get("/api/health")).json()
    assert body["retirement_rules"] == wanted != seed_hash()
