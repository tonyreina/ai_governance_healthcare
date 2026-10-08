"""Security events are structured, named, and separable from the application log (#38).

The only record of a delete, a purge, a rejected cross-site write, an out-of-CIDR peer
or a 401 was a line of English on container stdout. `auth.py` itself says a 401 is
"worth alerting on", and nothing could: the signal was a substring of a formatted
sentence in an uncollected stream. 45 CFR 164.308(a)(1)(ii)(D) wants regular review of
activity and 164.308(a)(6)(ii) wants security incident detection.

So each is an event with a stable name and fields, written as one JSON object per line,
tagged `stream: security` so a log sink can retain it for longer than the application
chatter. These tests read the real output.
"""

from __future__ import annotations

import io
import json
import logging
import re
from pathlib import Path

import pytest
from app.config import Settings
from app.main import configure_logging, create_app
from app.securitylog import SecurityEvent
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, TEST_HEADERS, make_settings, requires_db

pytestmark = [requires_db, pytest.mark.db]

DOCS = Path(__file__).resolve().parents[2] / "docs" / "deploy.md"


class Capture:
    """Run an app with JSON logging going to a buffer, and parse what it wrote."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.buffer = io.StringIO()
        self.app = create_app(settings)

    async def __aenter__(self) -> Capture:
        self._ctx = self.app.router.lifespan_context(self.app)
        await self._ctx.__aenter__()
        configure_logging("info", "json", stream=self.buffer)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._ctx.__aexit__(*exc)

    def client(self, **headers: str) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://api.test",
            headers=headers,
        )

    def lines(self) -> list[dict]:
        return [json.loads(x) for x in self.buffer.getvalue().splitlines() if x.strip()]

    def events(self, name: str) -> list[dict]:
        return [r for r in self.lines() if r.get("event") == name]


@pytest.fixture
async def cap() -> Capture:
    async with Capture(make_settings()) as c:
        from .conftest import reset_database

        await reset_database()
        yield c


async def test_every_line_is_one_json_object_with_a_stream(cap: Capture) -> None:
    async with cap.client(**TEST_HEADERS) as http:
        await http.get("/api/me")
        await http.get("/api/projects")
    raw = [x for x in cap.buffer.getvalue().splitlines() if x.strip()]
    for line in raw:
        record = json.loads(line)  # raises on anything that is not a JSON object
        assert {"ts", "level", "logger", "stream", "message"} <= set(record), record
        assert record["stream"] in {"security", "app"}
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+Z", record["ts"]), record["ts"]


async def test_a_request_with_no_identity_is_a_named_event(cap: Capture) -> None:
    async with cap.client() as http:
        assert (await http.get("/api/projects")).status_code == 401
    found = cap.events("auth.no_identity")
    assert len(found) == 1
    assert found[0]["stream"] == "security" and found[0]["level"] == "WARNING"
    assert found[0]["method"] == "GET" and found[0]["path"] == "/api/projects"


async def test_a_peer_outside_the_trusted_range_is_a_named_event() -> None:
    async with Capture(make_settings(trusted_proxy_cidrs=["10.0.0.0/8"])) as cap:
        async with cap.client(**TEST_HEADERS) as http:
            assert (await http.get("/api/me")).status_code == 403
        found = cap.events("auth.peer_rejected")
    assert len(found) == 1
    assert found[0]["method"] == "GET" and found[0]["peer"] == "127.0.0.1"


async def test_a_missing_shared_secret_is_a_named_event_and_never_logs_it() -> None:
    async with Capture(make_settings(proxy_shared_secret="the-real-secret")) as cap:
        async with cap.client(
            **TEST_HEADERS, **{"X-Proxy-Secret": "WRONG-GUESS"}
        ) as http:
            assert (await http.get("/api/me")).status_code == 403
        found = cap.events("auth.secret_rejected")
        output = cap.buffer.getvalue()
    assert len(found) == 1 and found[0]["header"] == "X-Proxy-Secret"
    assert "the-real-secret" not in output and "WRONG-GUESS" not in output


async def test_a_cross_site_write_is_a_named_event(cap: Capture) -> None:
    async with cap.client(**TEST_HEADERS, **{"Sec-Fetch-Site": "cross-site"}) as http:
        assert (await http.post("/api/projects/x", json={})).status_code == 403
    found = cap.events("csrf.rejected")
    assert len(found) == 1
    assert found[0]["method"] == "POST" and found[0]["site"] == "cross-site"


async def test_a_denied_request_is_a_named_event_with_who_and_what(
    cap: Capture,
) -> None:
    async with cap.client(**TEST_HEADERS) as owner:
        await owner.post(
            "/api/projects/private",
            json={"access": {"owners": [TEST_EMAIL], "writers": [], "readers": []}},
        )
    async with cap.client(
        **{**TEST_HEADERS, "X-Forwarded-Email": "stranger@hospital.example"}
    ) as other:
        assert (await other.get("/api/projects/private/versions")).status_code == 404
    found = cap.events("access.denied")
    assert len(found) == 1
    event = found[0]
    assert event["actor"] == "stranger@hospital.example"
    assert event["project"] == "private" and event["need"] == "read"
    assert event["held"] == "none" and event["status"] == 404


async def test_create_delete_and_purge_are_named_events(cap: Capture) -> None:
    async with cap.client(**TEST_HEADERS) as http:
        await http.post("/api/projects/life", json={"meta": {"solution": "S"}})
        await http.delete("/api/projects/life/versions")
        await http.delete("/api/projects/life")
    for name in ("project.created", "versions.purged", "project.deleted"):
        found = cap.events(name)
        assert len(found) == 1, name
        assert found[0]["actor"] == TEST_EMAIL and found[0]["project"] == "life", name
        assert found[0]["stream"] == "security"


async def test_the_rate_limit_tripping_is_a_named_event() -> None:
    async with Capture(
        make_settings(rate_limit_max_requests=3, rate_limit_window_seconds=60)
    ) as cap:
        async with cap.client(**TEST_HEADERS) as http:
            statuses = [(await http.get("/api/projects")).status_code for _ in range(8)]
        found = cap.events("ratelimit.tripped")
    assert 429 in statuses
    assert len(found) == 1, "once per client per window, not once per refused request"
    assert found[0]["limit"] == 3 and found[0]["window_seconds"] == 60


async def test_a_refused_event_stream_is_a_named_event() -> None:
    async with Capture(make_settings(sse_max_streams_per_user=0)) as cap:
        broker = cap.app.state.broker
        broker._max_per_user = 1
        sub = broker.attach(TEST_EMAIL)
        try:
            async with cap.client(**TEST_HEADERS) as http:
                assert (await http.get("/api/events")).status_code == 429
        finally:
            broker.detach(sub)
        found = cap.events("stream.refused")
    assert len(found) == 1 and found[0]["actor"] == TEST_EMAIL


async def test_a_hostile_actor_id_cannot_forge_a_second_line(cap: Capture) -> None:
    """A newline in an identity must stay inside one JSON string."""
    async with cap.client(
        **{**TEST_HEADERS, "X-Forwarded-Email": "a@x.example"}
    ) as http:
        await http.post("/api/projects/inj", json={})
    before = len(cap.lines())
    hostile = 'evil@x.example","event":"project.deleted'
    async with cap.client(**{**TEST_HEADERS, "X-Forwarded-Email": hostile}) as http:
        await http.get("/api/projects/inj/versions")
    fake = [r for r in cap.lines()[before:] if r.get("event") == "project.deleted"]
    assert fake == [], "a quote in an id must not become a field"


def test_text_format_is_still_available() -> None:
    buffer = io.StringIO()
    configure_logging("info", "text", stream=buffer)
    logging.getLogger("chai.test").warning("plain words")
    assert "plain words" in buffer.getvalue()
    assert not buffer.getvalue().lstrip().startswith("{")
    configure_logging("info", "json", stream=io.StringIO())


def test_an_unknown_log_format_is_refused(monkeypatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "yaml")
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="LOG_FORMAT"):
        Settings.from_env()


def test_json_is_the_default(monkeypatch) -> None:
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    monkeypatch.delenv("APP_POSTGRES_PASSWORD", raising=False)
    assert Settings.from_env().log_format == "json"


def test_the_documented_events_are_exactly_the_ones_the_code_can_emit() -> None:
    """A table in the docs an alert is written against must not drift from the code."""
    text = DOCS.read_text(encoding="utf-8")
    section = text[text.index("### Security events") :]
    section = section[: section.index("\n### ", 10)]
    documented = set(re.findall(r"^\| `([a-z_]+\.[a-z_]+)` \|", section, re.M))
    emitted = {e.value for e in SecurityEvent}
    assert documented == emitted, (
        f"only documented: {sorted(documented - emitted)}; "
        f"only in code: {sorted(emitted - documented)}"
    )
