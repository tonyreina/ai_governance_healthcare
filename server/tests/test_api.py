"""The REST contract, against a real PostgreSQL."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from .conftest import TEST_EMAIL, requires_db

pytestmark = [requires_db, pytest.mark.db]


# --- health and identity ----------------------------------------------------


async def test_health_needs_no_identity(client: AsyncClient) -> None:
    """Load balancer probes arrive with no identity header, by definition."""
    response = await client.get("/api/health", headers={"X-Forwarded-Email": ""})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert body["version"] == "test"


async def test_health_leaks_nothing_about_the_deployment(client: AsyncClient) -> None:
    body = await client.get("/api/health")
    text = json.dumps(body.json())
    assert "postgres" not in text.lower()
    assert "password" not in text.lower()


async def test_me_returns_the_proxy_identity(client: AsyncClient) -> None:
    response = await client.get("/api/me")
    assert response.status_code == 200
    assert response.json() == {
        "id": TEST_EMAIL,
        "name": "Test Er",
        "email": TEST_EMAIL,
        "dev": False,
    }


async def test_every_response_carries_the_auth_mode(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.headers["X-Chai-Auth-Mode"] == "proxy-header:proxy"


# --- create -----------------------------------------------------------------


async def test_create_returns_the_document_with_its_id(client: AsyncClient) -> None:
    response = await client.post("/api/projects/pnew1", json={"meta": {"org": "X"}})
    assert response.status_code == 201
    assert response.json() == {"id": "pnew1", "meta": {"org": "X"}}


async def test_duplicate_create_is_409(client: AsyncClient, project: str) -> None:
    response = await client.post(f"/api/projects/{project}", json={"meta": {}})
    assert response.status_code == 409
    assert project in response.json()["detail"]


async def test_duplicate_create_does_not_overwrite(
    client: AsyncClient, project: str
) -> None:
    """A 409 must leave the existing document exactly as it was."""
    await client.post(f"/api/projects/{project}", json={"meta": {"org": "WRONG"}})
    fetched = await client.get("/api/projects")
    [stored] = [p for p in fetched.json() if p["id"] == project]
    assert stored["meta"]["org"] == "St Elsewhere"


async def test_concurrent_creates_of_one_id_produce_exactly_one_201(
    client: AsyncClient,
) -> None:
    """``ON CONFLICT DO NOTHING`` rather than check-then-insert."""
    results = await asyncio.gather(
        *[client.post("/api/projects/prace", json={"n": i}) for i in range(8)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1
    assert codes.count(409) == 7


async def test_a_bad_project_id_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/projects/has%2Fslash", json={"a": 1})
    assert response.status_code in (404, 422)


# --- list -------------------------------------------------------------------


async def test_list_returns_every_project(client: AsyncClient, project: str) -> None:
    await client.post("/api/projects/psecond", json={"meta": {"org": "Y"}})
    response = await client.get("/api/projects")
    assert response.status_code == 200
    assert {p["id"] for p in response.json()} == {project, "psecond"}


async def test_list_spreads_the_document_alongside_the_id(
    client: AsyncClient, project: str
) -> None:
    """``subscribeAll`` hands the app ``{id, ...project}``."""
    [stored] = (await client.get("/api/projects")).json()
    assert stored["id"] == project
    assert stored["meta"]["solution"] == "Sepsis alert"
    assert stored["items"]["s4-1"]["status"] == "met"
    assert stored["metrics"][0]["name"] == "TPR gap"
    assert stored["archived"] is False


# --- patch ------------------------------------------------------------------


async def test_patch_deep_merges_and_keeps_siblings(
    client: AsyncClient, project: str
) -> None:
    response = await client.patch(
        f"/api/projects/{project}", json={"items": {"s4-2": {"status": "met"}}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"]["s4-2"]["status"] == "met"
    assert body["items"]["s4-2"]["owner"] == "A. Reviewer"
    assert body["items"]["s4-1"]["evidence"] == "validation report"
    assert body["meta"]["solution"] == "Sepsis alert"


async def test_patch_replaces_arrays_wholesale(
    client: AsyncClient, project: str
) -> None:
    response = await client.patch(
        f"/api/projects/{project}",
        json={"metrics": [{"name": "AUROC", "value": "0.9"}]},
    )
    assert response.json()["metrics"] == [{"name": "AUROC", "value": "0.9"}]


async def test_patch_persists(client: AsyncClient, project: str) -> None:
    await client.patch(f"/api/projects/{project}", json={"meta": {"org": "New Org"}})
    [stored] = (await client.get("/api/projects")).json()
    assert stored["meta"]["org"] == "New Org"
    assert stored["meta"]["solution"] == "Sepsis alert"


async def test_patch_on_a_missing_project_is_404(client: AsyncClient) -> None:
    response = await client.patch("/api/projects/pnope", json={"a": 1})
    assert response.status_code == 404


async def test_empty_patch_is_rejected(client: AsyncClient, project: str) -> None:
    assert (await client.patch(f"/api/projects/{project}", json={})).status_code == 422


async def test_patch_body_must_be_an_object(client: AsyncClient, project: str) -> None:
    assert (
        await client.patch(f"/api/projects/{project}", json=[1, 2])
    ).status_code == 422


# --- delete -----------------------------------------------------------------


async def test_delete_removes_the_project(client: AsyncClient, project: str) -> None:
    assert (await client.delete(f"/api/projects/{project}")).status_code == 204
    assert (await client.get("/api/projects")).json() == []


async def test_delete_removes_the_log_with_it(
    client: AsyncClient, project: str
) -> None:
    await client.post(f"/api/projects/{project}/log", json={"text": "Created"})
    await client.delete(f"/api/projects/{project}")
    await client.post(f"/api/projects/{project}", json={"meta": {}})
    assert (await client.get(f"/api/projects/{project}/log")).json() == []


async def test_deleting_twice_is_404(client: AsyncClient, project: str) -> None:
    await client.delete(f"/api/projects/{project}")
    assert (await client.delete(f"/api/projects/{project}")).status_code == 404


# --- audit log --------------------------------------------------------------


async def test_log_appends_and_reads_back_newest_first(
    client: AsyncClient, project: str
) -> None:
    for text in ("Project created", "Checkpoint A recorded", "Archived"):
        response = await client.post(
            f"/api/projects/{project}/log", json={"text": text}
        )
        assert response.status_code == 201

    entries = (await client.get(f"/api/projects/{project}/log")).json()
    assert [e["text"] for e in entries] == [
        "Archived",
        "Checkpoint A recorded",
        "Project created",
    ]


async def test_log_is_capped_at_sixty(client: AsyncClient, project: str) -> None:
    """``subscribeLog`` asks for the newest 60."""
    for index in range(65):
        await client.post(
            f"/api/projects/{project}/log", json={"text": f"entry {index}"}
        )
    entries = (await client.get(f"/api/projects/{project}/log")).json()
    assert len(entries) == 60
    assert entries[0]["text"] == "entry 64"


async def test_log_author_is_the_proxy_identity_not_the_body(
    client: AsyncClient, project: str
) -> None:
    """The browser sends ``by``. The server must not believe it."""
    response = await client.post(
        f"/api/projects/{project}/log",
        json={"text": "Checkpoint B signed", "by": "ceo@hospital.example"},
    )
    assert response.status_code == 201
    assert response.json()["by"] == TEST_EMAIL


async def test_log_timestamp_is_the_server_clock(
    client: AsyncClient, project: str
) -> None:
    response = await client.post(
        f"/api/projects/{project}/log",
        json={"text": "backdated?", "at": "1999-01-01T00:00:00.000Z"},
    )
    assert not response.json()["at"].startswith("1999")


async def test_log_keeps_fields_it_does_not_own(
    client: AsyncClient, project: str
) -> None:
    response = await client.post(
        f"/api/projects/{project}/log", json={"text": "x", "gate": "A"}
    )
    assert response.json()["gate"] == "A"


async def test_there_is_no_route_to_change_or_remove_a_log_entry(client) -> None:
    """Append-only is a property of the published API, not a convention.

    Asserted against the OpenAPI document rather than the route objects: it is
    what clients are actually offered, and it does not break when FastAPI
    changes how an included router is stored internally.
    """
    paths = client.app.openapi()["paths"]
    log_path = "/api/projects/{project_id}/log"
    assert set(paths[log_path]) == {"get", "post"}
    for path, operations in paths.items():
        if path.endswith("/log"):
            assert not {"put", "patch", "delete"} & set(operations), path


async def test_the_database_itself_refuses_to_update_a_log_entry(
    client: AsyncClient, project: str
) -> None:
    """A trigger, so a future bug cannot quietly rewrite history."""
    import asyncpg

    await client.post(f"/api/projects/{project}/log", json={"text": "original"})
    async with client.app.state.db.acquire() as conn:
        with pytest.raises(asyncpg.PostgresError, match="append-only"):
            await conn.execute(
                'UPDATE project_log SET entry = \'{"text":"tampered"}\'::jsonb'
            )
    entries = (await client.get(f"/api/projects/{project}/log")).json()
    assert entries[0]["text"] == "original"


async def test_log_on_a_missing_project_is_404(client: AsyncClient) -> None:
    response = await client.post("/api/projects/pnope/log", json={"text": "x"})
    assert response.status_code == 404


async def test_reading_the_log_of_a_missing_project_is_empty_not_404(
    client: AsyncClient,
) -> None:
    """Avoids an error toast when a subscription races a delete."""
    response = await client.get("/api/projects/pnope/log")
    assert response.status_code == 200
    assert response.json() == []


async def test_a_log_entry_needs_text(client: AsyncClient, project: str) -> None:
    assert (
        await client.post(f"/api/projects/{project}/log", json={})
    ).status_code == 422
    assert (
        await client.post(f"/api/projects/{project}/log", json={"text": ""})
    ).status_code == 422


# --- auth on the data routes ------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/me"),
        ("GET", "/api/projects"),
        ("POST", "/api/projects/px"),
        ("PATCH", "/api/projects/px"),
        ("DELETE", "/api/projects/px"),
        ("GET", "/api/projects/px/log"),
        ("POST", "/api/projects/px/log"),
        ("GET", "/api/events"),
    ],
)
async def test_every_data_route_needs_identity(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(
        method, path, headers={"X-Forwarded-Email": ""}, json={"text": "x"}
    )
    assert response.status_code == 401, f"{method} {path} did not require identity"
