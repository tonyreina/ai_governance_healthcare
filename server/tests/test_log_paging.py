"""The audit history must be readable all the way back (#40).

`GET /api/projects/{id}/log` had `LIMIT 60` and no way to ask for anything older:
entry 61 and everything before it was not slow to reach, it was unreachable
through the API, so every export carried the window silently and recovering the
rest needed database access, which is exactly the privileged path an audit should
not depend on. 45 CFR 164.312(b) is about being able to *examine* activity.

The page is still the newest 60 by default (that is right for a sidebar), and the
total is disclosed so nothing can pass a window off as the whole history. A cursor
reaches the rest.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, TEST_HEADERS, requires_db

pytestmark = [requires_db, pytest.mark.db]

TOTAL = 130


@pytest.fixture
async def long_history(client: AsyncClient) -> str:
    assert (
        await client.post("/api/projects/long", json={"meta": {"solution": "Long"}})
    ).status_code == 201
    async with client.app.state.db.acquire() as conn:
        # Direct, not 130 requests: this is about reading, and the rate limiter
        # would (rightly) object to 130 writes.
        #
        # Each entry gets an explicit, increasing timestamp. `now()` would do, until
        # the machine's clock steps backwards between two inserts (WSL does this),
        # which reordered entries and failed this test once in a full run.
        for i in range(TOTAL):
            await conn.execute(
                "INSERT INTO project_log (project_id, at, by_id, entry) "
                "VALUES ($1, now() + make_interval(secs => $2), $3, $4)",
                "long",
                float(i),
                TEST_EMAIL,
                {"at": "x", "by": TEST_EMAIL, "text": f"entry {i:03d}"},
            )
    return "long"


def texts(response) -> list[str]:
    return [e["text"] for e in response.json()]


async def test_the_default_page_is_the_newest_60_and_says_how_many_there_are(
    client: AsyncClient, long_history: str
) -> None:
    response = await client.get(f"/api/projects/{long_history}/log")
    assert response.status_code == 200
    assert len(response.json()) == 60
    assert texts(response)[0] == "entry 129", "newest first"
    # `entry 129` is newest of the 130 inserted by hand, plus any server-written
    # entry from the create (none: the project was created without a log write).
    assert response.headers["X-Log-Total"] == str(TOTAL)
    assert response.headers["X-Log-Next"], "there is more, and here is where"


async def test_a_cursor_reaches_every_entry_exactly_once(
    client: AsyncClient, long_history: str
) -> None:
    seen: list[str] = []
    url = f"/api/projects/{long_history}/log"
    pages = 0
    while url:
        response = await client.get(url)
        assert response.status_code == 200
        seen += texts(response)
        pages += 1
        cursor = response.headers.get("X-Log-Next")
        url = f"/api/projects/{long_history}/log?before={cursor}" if cursor else None
        assert pages < 10, "the cursor never ends"
    assert pages == 3, f"130 entries at 60 a page is three pages, got {pages}"
    assert len(seen) == TOTAL
    assert len(set(seen)) == TOTAL, "no entry repeats"
    assert seen == [f"entry {i:03d}" for i in range(TOTAL - 1, -1, -1)], (
        "newest to oldest, with no gap"
    )


async def test_the_last_page_has_no_cursor(
    client: AsyncClient, long_history: str
) -> None:
    first = await client.get(f"/api/projects/{long_history}/log?limit=500")
    assert len(first.json()) == TOTAL
    assert "X-Log-Next" not in first.headers


async def test_limit_is_respected_and_capped(
    client: AsyncClient, long_history: str
) -> None:
    small = await client.get(f"/api/projects/{long_history}/log?limit=5")
    assert len(small.json()) == 5
    huge = await client.get(f"/api/projects/{long_history}/log?limit=100000")
    assert huge.status_code == 200
    assert len(huge.json()) <= 500, "an unbounded page is a way to hurt the server"
    for bad in ("0", "-3", "abc"):
        assert (
            await client.get(f"/api/projects/{long_history}/log?limit={bad}")
        ).status_code == 422


async def test_a_malformed_cursor_is_refused(
    client: AsyncClient, long_history: str
) -> None:
    for bad in (
        "nonsense",
        "12345",
        "x.y",
        "123.abc",
        ".5",
        "99999999999999999999999.1",
    ):
        response = await client.get(f"/api/projects/{long_history}/log?before={bad}")
        assert response.status_code == 400, bad


async def test_paging_is_still_access_controlled(
    client: AsyncClient, long_history: str
) -> None:
    await client.patch(
        f"/api/projects/{long_history}",
        json={"access": {"owners": [TEST_EMAIL], "writers": [], "readers": []}},
    )
    first = await client.get(f"/api/projects/{long_history}/log")
    cursor = first.headers["X-Log-Next"]
    async with AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers={**TEST_HEADERS, "X-Forwarded-Email": "stranger@hospital.example"},
    ) as other:
        for url in (
            f"/api/projects/{long_history}/log",
            f"/api/projects/{long_history}/log?before={cursor}",
        ):
            response = await other.get(url)
            assert response.status_code == 404
            assert "X-Log-Total" not in response.headers, "the count is not leaked"


async def test_a_project_with_no_log_still_answers_with_an_empty_list(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/projects/never-existed/log")
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers["X-Log-Total"] == "0"
