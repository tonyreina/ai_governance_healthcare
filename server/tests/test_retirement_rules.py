"""The retirement rules: the manifest the server reads, who may change the rules, and
what /api/health reports (#168 PR C; R-66, D-76).

What disposal does with the rules is in ``test_retention.py``. This covers the edges:
that a manifest the server would misread is refused, never half-read; that the
migrate job fails closed without one; that the API's role can read the rules and not
change them; that their history cannot be edited even by the owner; and that
``/api/health`` reports the rule set the database is using.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

import asyncpg
import pytest
from app.config import Settings
from app.db import MIGRATION_LOCK_ID
from app.main import create_app
from app.retirement import (
    ChangeSource,
    ManifestError,
    RulesRefused,
    SyncOutcome,
    load_manifest,
    parse_manifest,
    record_framework,
    rule_set_hash,
    sync_rules,
)
from httpx import ASGITransport, AsyncClient

from . import manifests
from .conftest import (
    APP_ROLE_URL,
    DB_URL,
    make_settings,
    owner_connection,
    requires_db,
)

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


async def health_rules(client: AsyncClient) -> dict:
    client.app.state.db._rules_cache = None  # type: ignore[attr-defined]
    return (await client.get("/api/health")).json()["retirement_rules"]


@requires_db
async def test_health_reports_the_rule_set_the_database_uses(
    client: AsyncClient, tmp_path: Path
) -> None:
    body = (await client.get("/api/health")).json()
    # 010's seed alone: CHAI's rules, which no manifest has confirmed yet.
    assert body["retirement_rules"] == {
        "hash": seed_hash(), "primary": "chai", "synced": False,
    }  # fmt: skip
    # Everything it reported before is still there.
    assert {"status", "events", "version", "database", "db_role",
            "idle_lock_minutes", "sign_out_url", "auth_mode"} <= set(body)  # fmt: skip

    # The default build's manifest confirms the seed: same hash, now synced.
    done = manifests.run_migrate(
        DB_URL, RETIREMENT_MANIFEST=str(manifests.DEFAULT_MANIFEST)
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert await health_rules(client) == {
        "hash": seed_hash(), "primary": "chai", "synced": True,
    }  # fmt: skip

    path = manifests.write(tmp_path / "m.json", {"acme": manifests.STAND_IN}, "acme")
    wanted = manifests.manifest_of(path)["ruleSetHash"]
    done = manifests.run_migrate(
        DB_URL,
        RETIREMENT_MANIFEST=str(path),
        RETIREMENT_RULES_ACK=manifests.transition(
            2,
            ("chai", manifests.CHAI_RULES),
            ("acme", manifests.CHAI_RULES | manifests.rules_of(path)),
        ),
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert await health_rules(client) == {
        "hash": wanted, "primary": "acme", "synced": True,
    }  # fmt: skip
    assert wanted != seed_hash()


# --- the stamp: only the active primary's (R-66) -------------------------------------

BAD_STAMPS = {
    "wrong case": {"id": "CHAI"},
    "a supplement's id": {"id": "optica"},
    "an unknown id": {"id": "no-such-framework"},
    "not an object": "chai",
    "null": None,
    "an id that is not text": {"id": 1},
    "an empty id": {"id": ""},
    "another key besides the id": {"id": "chai", "version": "1"},
}


@requires_db
@pytest.mark.parametrize("case", sorted(BAD_STAMPS))
async def test_the_api_refuses_a_stamp_that_is_not_the_active_primary(
    client: AsyncClient, case: str
) -> None:
    stamp = BAD_STAMPS[case]
    created = await client.post(
        "/api/projects/bad", json={"meta": {"solution": "x", "framework": stamp}}
    )
    assert created.status_code == 422, created.text
    assert 'exactly {"id": "chai"}' in created.json()["detail"]
    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT count(*) FROM projects") == 0

    assert (await client.post("/api/projects/p", json={"meta": {}})).status_code == 201
    patched = await client.patch("/api/projects/p", json={"meta": {"framework": stamp}})
    assert patched.status_code == 422, patched.text
    assert "framework" not in (await stored_doc("p")).get("meta", {})


async def stored_doc(pid: str) -> dict:
    async with owner_connection() as conn:
        text = await conn.fetchval("SELECT doc::text FROM projects WHERE id = $1", pid)
    return json.loads(text)


@requires_db
async def test_the_api_accepts_no_stamp_or_exactly_the_active_primarys(
    client: AsyncClient,
) -> None:
    assert (
        await client.post("/api/projects/none", json={"meta": {}})
    ).status_code == 201
    created = await client.post(
        "/api/projects/ok", json={"meta": {"framework": {"id": "chai"}}}
    )
    assert created.status_code == 201, created.text
    patched = await client.patch(
        "/api/projects/none", json={"meta": {"framework": {"id": "chai"}}}
    )
    assert patched.status_code == 200, patched.text
    # A patch that does not touch the stamp is not checked against it.
    assert (
        await client.patch("/api/projects/ok", json={"meta": {"solution": "y"}})
    ).status_code == 200


@requires_db
async def test_a_stamp_follows_the_primary_the_latest_sync_recorded(
    client: AsyncClient, tmp_path: Path
) -> None:
    created = await client.post(
        "/api/projects/old", json={"meta": {"framework": {"id": "chai"}}}
    )
    assert created.status_code == 201
    path = manifests.write(tmp_path / "m.json", {"acme": manifests.STAND_IN}, "acme")
    done = manifests.run_migrate(
        DB_URL,
        RETIREMENT_MANIFEST=str(path),
        RETIREMENT_RULES_ACK=manifests.transition(
            1,
            ("chai", manifests.CHAI_RULES),
            ("acme", manifests.CHAI_RULES | manifests.rules_of(path)),
        ),
    )
    assert done.returncode == 0, done.stdout + done.stderr

    chai = await client.post(
        "/api/projects/c", json={"meta": {"framework": {"id": "chai"}}}
    )
    assert chai.status_code == 422
    assert 'exactly {"id": "acme"}' in chai.json()["detail"]
    acme = await client.post(
        "/api/projects/a", json={"meta": {"framework": {"id": "acme"}}}
    )
    assert acme.status_code == 201, acme.text
    # A record stamped before keeps its stamp through an unrelated patch...
    assert (
        await client.patch("/api/projects/old", json={"meta": {"solution": "z"}})
    ).status_code == 200
    # ...but a patch that drops the active primary's stamp, by replacing meta,
    # would move the record to CHAI's rules, and is refused.
    dropped = await client.patch("/api/projects/a", json={"meta": None})
    assert dropped.status_code == 422, dropped.text
    assert (await stored_doc("a"))["meta"]["framework"] == {"id": "acme"}


async def acme_is_primary(tmp_path: Path) -> None:
    path = manifests.write(tmp_path / "m.json", {"acme": manifests.STAND_IN}, "acme")
    done = manifests.run_migrate(
        DB_URL,
        RETIREMENT_MANIFEST=str(path),
        RETIREMENT_RULES_ACK=manifests.transition(
            1,
            ("chai", manifests.CHAI_RULES),
            ("acme", manifests.CHAI_RULES | manifests.rules_of(path)),
        ),
    )
    assert done.returncode == 0, done.stdout + done.stderr


@requires_db
async def test_under_another_primary_a_record_must_carry_its_stamp(
    client: AsyncClient, tmp_path: Path
) -> None:
    # A record of the CHAI build, from before the switch: CHAI's, unstamped.
    assert (
        await client.post("/api/projects/legacy", json={"meta": {"solution": "x"}})
    ).status_code == 201
    await acme_is_primary(tmp_path)

    # Leaving the stamp out would make the record CHAI's, and so let the writer
    # choose CHAI's rules over the primary's. Refused, in every shape of "no stamp".
    for body in ({"meta": {"solution": "x"}}, {}, {"meta": None},
                 {"meta": {"framework": None}}):  # fmt: skip
        created = await client.post("/api/projects/nostamp", json=body)
        missing = "framework" not in (body.get("meta") or {})
        assert ("must carry meta.framework" in created.text) is missing, created.text
        assert created.status_code == 422, (body, created.text)
        assert '{"id": "acme"}' in created.json()["detail"]
    async with owner_connection() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM projects WHERE id = 'nostamp'"
        ) == 0  # fmt: skip

    stamped = await client.post(
        "/api/projects/new", json={"meta": {"framework": {"id": "acme"}}}
    )
    assert stamped.status_code == 201, stamped.text
    # A patch that would leave a stamped record unstamped is refused...
    for patch in ({"meta": None}, {"meta": {"framework": None}}):
        dropped = await client.patch("/api/projects/new", json=patch)
        assert dropped.status_code == 422, (patch, dropped.text)
    assert (await stored_doc("new"))["meta"]["framework"] == {"id": "acme"}
    # ...while the record written before the switch stays CHAI's and editable: a
    # patch that leaves its framework as it was moves it to no other rules.
    assert (
        await client.patch("/api/projects/legacy", json={"meta": {"solution": "y"}})
    ).status_code == 200
    assert "framework" not in (await stored_doc("legacy"))["meta"]


@requires_db
async def test_a_correctly_stamped_record_retires(client: AsyncClient) -> None:
    async with owner_connection() as conn:
        date = str(await conn.fetchval("SELECT (now() - interval '7 years')::date"))
    created = await client.post(
        "/api/projects/stamped",
        json={
            "meta": {"framework": {"id": "chai"}},
            "gates": {"D": {"decision": "Retire", "date": date}},
        },
    )
    assert created.status_code == 201, created.text
    async with owner_connection() as conn:
        await conn.execute(
            "UPDATE projects SET updated_at = now() - interval '7 years'"
            " WHERE id = 'stamped'"
        )
        due = {r[0] for r in await conn.fetch("SELECT project_id FROM retention_due()")}
    assert "stamped" in due


STAMP_SHAPES = [
    ({}, "chai"),
    ({"meta": {"framework": {"id": "acme"}}}, "acme"),
    ({"meta": {"framework": {"id": ""}}}, "chai"),
    ({"meta": {"framework": None}}, "chai"),
    ({"meta": None}, "chai"),
    ({"meta": "text"}, "chai"),
    ({"meta": {"framework": {"version": "1"}}}, "chai"),
]


def test_the_api_reads_a_stamp_as_010_does() -> None:
    for doc, expected in STAMP_SHAPES:
        assert record_framework(doc) == expected, doc


@requires_db
async def test_the_sql_reads_a_stamp_as_the_api_does(client: AsyncClient) -> None:
    # The API compares stamps with app.retirement.record_framework(); 010 decides
    # retirement with its own record_framework(). They must agree.
    async with owner_connection() as conn:
        for doc, expected in STAMP_SHAPES:
            sql = await conn.fetchval(
                "SELECT record_framework($1::text::jsonb)", json.dumps(doc)
            )
            assert sql == record_framework(doc) == expected, doc


# --- the API's own migration path (RUN_MIGRATIONS=true) ------------------------------


def fallback_settings(**overrides: object) -> Settings:
    """The single-role setup: the API holds the owner's credential and migrates."""
    return make_settings(
        database_url=DB_URL, app_database_url="", run_migrations=True, **overrides
    )


async def health_of(app) -> dict:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://api.test"
    ) as http:
        return (await http.get("/api/health")).json()


@requires_db
async def test_the_api_migrating_itself_syncs_from_its_manifest(
    client: AsyncClient, tmp_path: Path
) -> None:
    path = manifests.write(
        tmp_path / "m.json", manifests.chai_with("C", "Withdraw", "stop"), "chai"
    )
    wanted = manifests.manifest_of(path)["ruleSetHash"]
    ack = manifests.transition(
        1, ("chai", manifests.CHAI_RULES), ("chai", manifests.rules_of(path))
    )

    # The same refusal as the migrate job: the API does not start.
    app = create_app(fallback_settings(retirement_manifest=str(path)))
    with pytest.raises(RuntimeError, match=f"RETIREMENT_RULES_ACK={ack}"):
        async with app.router.lifespan_context(app):
            pass
    assert ("chai", "C", "Withdraw") not in await rules_now()
    # A malformed manifest stops it too.
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    app = create_app(fallback_settings(retirement_manifest=str(broken)))
    with pytest.raises(RuntimeError, match="not JSON"):
        async with app.router.lifespan_context(app):
            pass
    assert await changes() == 1

    app = create_app(
        fallback_settings(retirement_manifest=str(path), retirement_rules_ack=ack)
    )
    async with app.router.lifespan_context(app):
        body = await health_of(app)
    assert body["retirement_rules"] == {
        "hash": wanted, "primary": "chai", "synced": True,
    }  # fmt: skip
    assert ("chai", "C", "Withdraw") in await rules_now()
    assert await changes() == 2


@requires_db
async def test_the_api_migrating_itself_without_a_manifest_says_so(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    app = create_app(fallback_settings())
    async with app.router.lifespan_context(app):
        body = await health_of(app)
    assert body["retirement_rules"]["synced"] is False
    assert any(
        "RETIREMENT_MANIFEST is not set" in r.getMessage()
        and "synced=false" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
    assert await changes() == 1


def test_the_manifest_settings_are_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MIGRATIONS", "true")
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
    monkeypatch.setenv("RETIREMENT_MANIFEST", " /app/manifest.json ")
    monkeypatch.setenv("RETIREMENT_RULES_ACK", "ab" * 32)
    settings = Settings.from_env()
    assert settings.retirement_manifest == "/app/manifest.json"
    assert settings.retirement_rules_ack == "ab" * 32


# --- the migration lock ----------------------------------------------------------------


class LockTakenLate:
    """A connection that runs ``pg_advisory_xact_lock`` only before the sync's first
    write, not where the sync asks for it: the mutation of taking the lock after the
    reads. Everything else goes straight to the real connection."""

    LOCK = "pg_advisory_xact_lock"

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self._lock_args: tuple | None = None

    def transaction(self):
        return self._conn.transaction()

    async def execute(self, query: str, *args):
        if self.LOCK in query:
            self._lock_args = (query, *args)
            return None
        if self._lock_args is not None:
            pending, self._lock_args = self._lock_args, None
            await self._conn.execute(*pending)
        return await self._conn.execute(query, *args)

    async def fetch(self, query: str, *args):
        return await self._conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args):
        return await self._conn.fetchrow(query, *args)


SHELVE = ("chai", "B", "Shelve")


async def race_a_rule_change(path: Path, wrap=None) -> object:
    """Another migrate job holds the lock and commits a rule change (CHAI's B decided
    "Shelve" ends a project) while a sync acknowledged for the state before it
    waits. Returns the waiting sync's result, or the exception it raised."""
    manifest = load_manifest(str(path))
    ack = manifests.transition(
        1, ("chai", manifests.CHAI_RULES), ("chai", manifests.rules_of(path))
    )
    holder = await asyncpg.connect(DB_URL)
    syncer = await asyncpg.connect(DB_URL)
    try:
        await holder.execute("BEGIN")
        await holder.execute("SELECT pg_advisory_xact_lock($1)", MIGRATION_LOCK_ID)
        conn = wrap(syncer) if wrap else syncer
        task = asyncio.create_task(sync_rules(conn, manifest, ack))
        pid = syncer.get_server_pid()
        waiting = False
        for _ in range(100):
            waiting = await holder.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = $1"
                " AND locktype = 'advisory' AND NOT granted)",
                pid,
            )
            if waiting or task.done():
                break
            await asyncio.sleep(0.05)
        # The sync waits for the lock and has changed nothing. Without the lock it
        # would have run straight through, and this fails.
        assert waiting and not task.done()
        assert await changes() == 1
        # The holder changes the rules and records it, as a sync does, then commits.
        after = sorted([*manifests.CHAI_RULES, SHELVE])
        await holder.execute(
            "INSERT INTO retirement_rule (framework_id, gate_id, decision)"
            " VALUES ($1, $2, $3)",
            *SHELVE,
        )
        await holder.execute(
            "INSERT INTO retirement_rule_change (source, framework_id, old_rules,"
            " new_rules, rule_set_hash, acknowledged)"
            " VALUES ('manifest', 'chai', $1::text::jsonb, $2::text::jsonb, $3, true)",
            json.dumps(sorted(manifests.CHAI_RULES)),
            json.dumps(after),
            rule_set_hash("chai", {(g, d) for f, g, d in after if f == "chai"}),
        )
        await holder.execute("COMMIT")
        try:
            return await asyncio.wait_for(task, 10)
        except RulesRefused as exc:
            return exc
    finally:
        await holder.close()
        await syncer.close()


@requires_db
async def test_two_syncs_serialize_on_the_migration_lock(
    client: AsyncClient, tmp_path: Path
) -> None:
    path = manifests.write(
        tmp_path / "m.json", manifests.chai_with("C", "Withdraw", "stop"), "chai"
    )
    # The waiting sync reads the rules only once it holds the lock, so it sees the
    # holder's change: its acknowledgment was for the state before, and it refuses,
    # naming the rule it would now remove. The holder's change stands.
    result = await race_a_rule_change(path)
    assert isinstance(result, RulesRefused), result
    assert "chai: checkpoint B decided 'Shelve' (removed)" in str(result)
    assert await rules_now() == {*manifests.CHAI_RULES, SHELVE}
    assert await changes() == 2


@requires_db
async def test_the_lock_test_fails_when_the_lock_is_taken_after_the_reads(
    client: AsyncClient, tmp_path: Path
) -> None:
    # Mutation: the same race with the lock taken only before the first write. The
    # sync has read the state before the holder's change, so the acknowledgment for
    # that state matches; it then writes on top of the holder's change and records
    # a history row that does not describe the table. The assertions above fail.
    path = manifests.write(
        tmp_path / "m.json", manifests.chai_with("C", "Withdraw", "stop"), "chai"
    )
    result = await race_a_rule_change(path, LockTakenLate)
    assert not isinstance(result, RulesRefused), result
    assert result.outcome is SyncOutcome.CHANGED  # type: ignore[attr-defined]
    async with owner_connection() as conn:
        recorded = await conn.fetchval(
            "SELECT new_rules::text FROM retirement_rule_change ORDER BY id DESC LIMIT 1"
        )
    assert {tuple(r) for r in json.loads(recorded)} != await rules_now()
