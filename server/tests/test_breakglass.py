"""Emergency access: a record no living account can reach must still be reachable (#42).

When a project's only owner leaves and their SSO account is disabled, nobody could
read, export, reassign, archive, delete or purge the record, the organization's
Security Officer included. Recovery was a hand-written UPDATE against the `access`
jsonb: the privileged database path the role model exists to avoid needing. 45 CFR
164.312(a)(2)(ii) makes an emergency access procedure *required*, not addressable.

So an identity configured as break-glass holds owner rights on every project, and
EVERY use is recorded loudly in that project's own audit log, in an entry that is a
system entry (never redacted by a purge) and names the event `access.breakglass`. A
break-glass path that is not loudly recorded is just a backdoor.
"""

from __future__ import annotations

import json
import logging

import pytest
from app.config import Settings
from app.main import create_app
from httpx import ASGITransport, AsyncClient

from .conftest import (
    TEST_EMAIL,
    TEST_HEADERS,
    make_settings,
    owner_connection,
    requires_db,
)

pytestmark = [requires_db, pytest.mark.db]

OFFICER = "security.officer@hospital.example"
LEAVER = "departed@hospital.example"
STRANGER = "stranger@hospital.example"


@pytest.fixture
def breakglass_settings() -> Settings:
    return make_settings(emergency_access_ids=frozenset({OFFICER}))


@pytest.fixture
async def bg(breakglass_settings: Settings):
    """An app with a configured break-glass identity, and a client per person."""
    from .conftest import reset_database

    app = create_app(breakglass_settings)
    async with app.router.lifespan_context(app):
        await reset_database()

        def user(email: str) -> AsyncClient:
            return AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://api.test",
                headers={**TEST_HEADERS, "X-Forwarded-Email": email},
            )

        app.state.user = user  # type: ignore[attr-defined]
        yield app


async def orphan(bg, pid: str = "orphaned") -> None:
    """A project whose only owner has been deprovisioned: nobody on it can sign in."""
    async with bg.state.user(TEST_EMAIL) as owner:
        r = await owner.post(
            f"/api/projects/{pid}",
            json={
                "meta": {"solution": "Orphan"},
                "access": {"owners": [LEAVER], "writers": [], "readers": []},
            },
        )
        assert r.status_code == 201
    # created_by is the test user, but the access list names only the leaver.


async def breakglass_entries(bg, pid: str) -> list[dict]:
    async with owner_connection() as conn:
        rows = await conn.fetch(
            "SELECT entry, is_system, by_id FROM project_log "
            "WHERE project_id = $1 AND entry->>'event' = 'access.breakglass' "
            "ORDER BY seq",
            pid,
        )
    return [
        {**json.loads(r["entry"]), "is_system": r["is_system"], "by_id": r["by_id"]}
        for r in rows
    ]


async def test_nobody_else_can_reach_an_orphaned_project(bg) -> None:
    await orphan(bg)
    async with bg.state.user(STRANGER) as other:
        assert (await other.get("/api/projects/orphaned/versions")).status_code == 404
        assert "orphaned" not in [
            p["id"] for p in (await other.get("/api/projects")).json()
        ]


async def test_the_configured_identity_can_read_and_list_it(bg) -> None:
    await orphan(bg)
    async with bg.state.user(OFFICER) as officer:
        assert "orphaned" in [
            p["id"] for p in (await officer.get("/api/projects")).json()
        ]
        assert (await officer.get("/api/projects/orphaned/versions")).status_code == 200
        assert (await officer.get("/api/projects/orphaned/log")).status_code == 200


async def test_it_can_reassign_ownership_which_is_the_point(bg) -> None:
    await orphan(bg)
    async with bg.state.user(OFFICER) as officer:
        r = await officer.patch(
            "/api/projects/orphaned",
            json={
                "access": {
                    "owners": ["new.owner@hospital.example"],
                    "writers": [],
                    "readers": [],
                }
            },
        )
    assert r.status_code == 200
    assert r.json()["access"]["owners"] == ["new.owner@hospital.example"]
    async with bg.state.user("new.owner@hospital.example") as new_owner:
        assert "orphaned" in [
            p["id"] for p in (await new_owner.get("/api/projects")).json()
        ]


async def test_it_can_archive_and_delete(bg) -> None:
    await orphan(bg, "a1")
    await orphan(bg, "a2")
    async with bg.state.user(OFFICER) as officer:
        assert (
            await officer.patch("/api/projects/a1", json={"archived": True})
        ).status_code == 200
        assert (await officer.delete("/api/projects/a2")).status_code == 204


async def test_every_use_on_a_project_is_recorded_in_its_own_log(bg) -> None:
    await orphan(bg)
    async with bg.state.user(OFFICER) as officer:
        await officer.patch("/api/projects/orphaned", json={"meta": {"org": "x"}})
    entries = await breakglass_entries(bg, "orphaned")
    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry["is_system"] is True, "a system entry, so a purge never redacts it"
    assert entry["by_id"] == OFFICER
    assert entry["event"] == "access.breakglass"
    assert OFFICER in entry["text"] and "EMERGENCY" in entry["text"].upper()
    assert "not granted by this project's access list" in entry["text"]


async def test_the_record_is_visible_to_the_projects_new_owners(bg) -> None:
    await orphan(bg)
    async with bg.state.user(OFFICER) as officer:
        await officer.patch(
            "/api/projects/orphaned",
            json={
                "access": {
                    "owners": ["new.owner@hospital.example"],
                    "writers": [],
                    "readers": [],
                }
            },
        )
    async with bg.state.user("new.owner@hospital.example") as owner:
        texts = [
            e["text"] for e in (await owner.get("/api/projects/orphaned/log")).json()
        ]
    assert any("EMERGENCY ACCESS" in t and OFFICER in t for t in texts), texts


async def test_the_entry_survives_a_purge(bg) -> None:
    await orphan(bg)
    async with bg.state.user(OFFICER) as officer:
        await officer.get("/api/projects/orphaned/versions")
        assert (
            await officer.delete("/api/projects/orphaned/versions")
        ).status_code == 204
    entries = await breakglass_entries(bg, "orphaned")
    assert entries, "the evidence that emergency access was used is not purgeable"
    assert all("purged" not in str(e.get("text", "")).lower() for e in entries)


async def test_reads_are_throttled_but_writes_are_not(bg) -> None:
    await orphan(bg)
    async with bg.state.user(OFFICER) as officer:
        for _ in range(4):
            await officer.get("/api/projects/orphaned/versions")
    assert len(await breakglass_entries(bg, "orphaned")) == 1, (
        "a refresh storm is one entry"
    )
    async with bg.state.user(OFFICER) as officer:
        await officer.patch("/api/projects/orphaned", json={"meta": {"org": "a"}})
        await officer.patch("/api/projects/orphaned", json={"meta": {"org": "b"}})
    assert len(await breakglass_entries(bg, "orphaned")) == 3, (
        "each write is its own entry"
    )


async def test_ordinary_owners_leave_no_emergency_record(bg) -> None:
    async with bg.state.user(TEST_EMAIL) as owner:
        await owner.post("/api/projects/mine", json={"meta": {"solution": "Mine"}})
        await owner.patch("/api/projects/mine", json={"meta": {"org": "x"}})
        await owner.get("/api/projects/mine/versions")
    assert await breakglass_entries(bg, "mine") == []


async def test_the_officer_owning_a_project_normally_is_not_an_emergency(bg) -> None:
    async with bg.state.user(OFFICER) as officer:
        await officer.post(
            "/api/projects/theirs", json={"meta": {"solution": "Theirs"}}
        )
        await officer.patch("/api/projects/theirs", json={"meta": {"org": "x"}})
    assert await breakglass_entries(bg, "theirs") == []


async def test_a_use_is_also_loud_in_the_process_log(
    bg, caplog: pytest.LogCaptureFixture
) -> None:
    await orphan(bg)
    caplog.set_level(logging.WARNING)
    async with bg.state.user(OFFICER) as officer:
        await officer.get("/api/projects/orphaned/versions")
        await officer.get("/api/projects")
    lines = [
        r.getMessage() for r in caplog.records if "access.breakglass" in r.getMessage()
    ]
    assert any("project='orphaned'" in line for line in lines), lines
    assert any("action=list" in line for line in lines), lines


async def test_without_configuration_nobody_has_emergency_access(
    client: AsyncClient,
) -> None:
    """Off by default: no identity is special unless the deployment says so."""
    await client.post(
        "/api/projects/locked",
        json={"access": {"owners": [LEAVER], "writers": [], "readers": []}},
    )
    async with AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers={**TEST_HEADERS, "X-Forwarded-Email": OFFICER},
    ) as officer:
        assert (await officer.get("/api/projects/locked/versions")).status_code == 404


def test_the_ids_are_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "EMERGENCY_ACCESS_IDS", f" {OFFICER} , second@hospital.example ,"
    )
    monkeypatch.setenv("RUN_MIGRATIONS", "true")
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    settings = Settings.from_env()
    assert settings.emergency_access_ids == frozenset(
        {OFFICER, "second@hospital.example"}
    )


def test_the_old_singular_name_works_too(monkeypatch) -> None:
    monkeypatch.delenv("EMERGENCY_ACCESS_IDS", raising=False)
    monkeypatch.setenv("EMERGENCY_ACCESS_ID", OFFICER)
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    assert Settings.from_env().emergency_access_ids == frozenset({OFFICER})


def test_it_is_off_by_default(monkeypatch) -> None:
    for name in (
        "EMERGENCY_ACCESS_IDS",
        "EMERGENCY_ACCESS_ID",
        "APP_POSTGRES_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)
    assert Settings.from_env().emergency_access_ids == frozenset()


async def test_the_startup_log_names_who_holds_emergency_access(
    breakglass_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    app = create_app(breakglass_settings)
    async with app.router.lifespan_context(app):
        pass
    assert any(
        "emergency access" in r.getMessage().lower() and OFFICER in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
