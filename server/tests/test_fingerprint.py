"""The server's fingerprint is the dashboard's, for the same record (#177).

Three programs compute the record fingerprint: the dashboard (what the setup page
and every export show), examples/load_export.py (what a reader recomputes from an
export) and the server (each revision in the version history). They agree only if
they canonicalize alike. tests/fixtures/fingerprint_record.json holds one record
built to separate them, and the digests the dashboard gives it
(tests/test_export_schema.py checks the dashboard against the same file):

* integer-like keys ("9", "10"), which a JavaScript object reorders;
* keys whose order differs between UTF-16 code units (the browser's sort) and code
  points (Python's), an emoji beside a character from U+E000 to U+FFFF;
* every volatile field, at more than one depth;
* the fields a real record carries, a checkpoint's date, an answer's evidence,
  owner, due date and references among them.

And tests/fixtures/sample_export.json is a real export, the published build's
"Sepsis early warning (sample)" with a link and a file added as evidence, so the
fingerprint the dashboard wrote into it is the dashboard's digest of a record shaped
as the dashboard stores one (tests/test_export_schema.py checks the dashboard still
gives it that digest). A server that left out a field the rule keeps, a ``date``
say, agreed with itself on any record built by hand without one, and disagrees here.

The server used to sort by code point, and its revisions were hashed without the
project's id, so the same record had one fingerprint on the setup page and in the
export and another in the history.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from app.routes import content_md5
from httpx import AsyncClient

from .conftest import requires_db

REPO = Path(__file__).resolve().parents[2]
LONE = re.compile("[\ud800-\udfff]")
FIXTURE = json.loads(
    (REPO / "tests" / "fixtures" / "fingerprint_record.json").read_text("utf-8")
)
SAMPLE = json.loads(
    (REPO / "tests" / "fixtures" / "sample_export.json").read_text("utf-8")
)


def paths(value: object, path: tuple = ()) -> set[tuple]:
    """Every key path in a document, list positions left out."""
    out = {path}
    if isinstance(value, dict):
        for k, v in value.items():
            out |= paths(v, (*path, k))
    elif isinstance(value, list):
        for v in value:
            out |= paths(v, path)
    return out


def keys_at_the_end(doc: object) -> set[str]:
    return {p[-1] for p in paths(doc) if p}


def load_export():
    spec = importlib.util.spec_from_file_location(
        "load_export", REPO / "examples" / "load_export.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_server_gives_the_record_the_dashboards_fingerprint():
    assert content_md5(FIXTURE["record"]) == FIXTURE["md5"]


def test_the_shared_record_carries_the_fields_a_real_record_does():
    """Without them, a server that dropped one of them would still agree."""
    record = FIXTURE["record"]
    assert record["gates"]["A"]["date"] and record["gates"]["B"]["date"]
    answer = record["items"]["s1-1"]
    assert answer["evidence"] and answer["owner"] and answer["due"]
    assert answer["refs"]["rfile0001"]["file"]["size"] == 1048576


def test_the_server_gives_a_real_export_the_dashboards_fingerprint():
    """The digest the dashboard wrote into a real export of a sample record."""
    record = {**SAMPLE["_state"], "id": SAMPLE["project_id"]}
    have = keys_at_the_end(record)
    # The fields a real record carries are in it, so dropping any is noticed.
    for key in ("date", "decision", "rationale", "evidence", "owner", "due", "refs"):
        assert key in have, key
    assert content_md5(record) == SAMPLE["fingerprint"]["md5"]


def test_load_export_gives_it_the_same():
    got = load_export().fingerprint({"_state": FIXTURE["record"]})
    assert got == {"md5": FIXTURE["md5"], "sha256": FIXTURE["sha256"]}


def test_keys_are_sorted_by_utf16_code_unit_not_code_point():
    """An emoji (U+1F600, surrogates D83D DE00) sorts before U+FFFF in UTF-16."""
    emoji, high = "\U0001f600", "￿"
    by_unit = content_md5({emoji: 1, high: 2})
    # The same document written in the other order hashes the same: order is the
    # canonical form's, not the input's.
    assert by_unit == content_md5({high: 2, emoji: 1})
    import hashlib

    expected = json.dumps(
        {emoji: 1, high: 2}, ensure_ascii=False, separators=(",", ":")
    )
    assert by_unit == hashlib.md5(expected.encode("utf-8")).hexdigest()


def test_integer_like_keys_sort_as_strings():
    import hashlib

    expected = '{"1":0,"10":0,"9":0}'
    assert (
        content_md5({"9": 0, "10": 0, "1": 0})
        == hashlib.md5(expected.encode()).hexdigest()
    )


@requires_db
class TestARevisionCarriesTheRecordsFingerprint:
    async def test_the_version_history_agrees_with_an_export(self, client: AsyncClient):
        record = {
            k: v for k, v in FIXTURE["record"].items() if k not in ("id", "_state")
        }
        # Without the lone surrogates, which PostgreSQL cannot store (the server
        # refuses such a record: TestALoneSurrogateIsRefused).
        record = json.loads(json.dumps(record))
        del record["meta"]["lone"]
        record["card"] = {k: v for k, v in record["card"].items() if not LONE.search(k)}
        pid = "p-fingerprint"
        assert (await client.post(f"/api/projects/{pid}", json=record)).status_code in (
            200,
            201,
        )
        await client.patch(f"/api/projects/{pid}", json={"meta": {"org": "Later"}})
        versions = (await client.get(f"/api/projects/{pid}/versions")).json()
        reader = load_export()
        assert [v["rev"] for v in versions] == [2, 1]
        for v in versions:
            stored = (
                await client.get(f"/api/projects/{pid}/versions/{v['rev']}")
            ).json()
            # What the dashboard holds is {id, ...doc}, and what it exports is that
            # record as _state with its id beside it: recompute as a reader would.
            export = {"_state": stored["doc"], "project_id": pid}
            assert v["md5"] == reader.fingerprint(export)["md5"], v["rev"]
        # And it is the record's fingerprint, not the stored document's alone.
        first = (await client.get(f"/api/projects/{pid}/versions/1")).json()["doc"]
        assert versions[-1]["md5"] == content_md5({**first, "id": pid})
        assert versions[-1]["md5"] != content_md5(first)


def test_a_lone_surrogate_is_written_as_javascript_writes_it():
    """JSON.stringify writes a lone surrogate as its \\u escape (lowercase hex), so the
    canonical text is ASCII there and UTF-8 can encode it. Python's json.dumps with
    ensure_ascii=False writes the surrogate itself, which UTF-8 cannot encode: the
    server raised UnicodeEncodeError on any such record (#177)."""
    import hashlib

    expected = '{"a\\ud800":"b\\udc00"}'
    assert (
        content_md5({"a\ud800": "b\udc00"})
        == hashlib.md5(expected.encode()).hexdigest()
    )
    # A real pair is one character, written as itself, not escaped.
    pair = '{"k":"\U0001f600"}'
    assert content_md5({"k": "\U0001f600"}) == hashlib.md5(pair.encode()).hexdigest()


@requires_db
class TestARealSampleRecordsRevision:
    async def test_the_version_history_gives_it_the_exports_fingerprint(
        self, client: AsyncClient
    ):
        """The sample's record, sent as the dashboard sends it. The server makes the
        creator an owner and attributes each signed checkpoint, so what it stores is
        not byte for byte what was sent; its revision is the fingerprint of what it
        stored, by the rule the dashboard's export of the sample was checked by, and
        the dates, answers and references are stored as sent."""
        pid = SAMPLE["project_id"]
        sent = SAMPLE["_state"]
        r = await client.post(f"/api/projects/{pid}", json=sent)
        assert r.status_code in (200, 201), r.text
        versions = (await client.get(f"/api/projects/{pid}/versions")).json()
        stored = (await client.get(f"/api/projects/{pid}/versions/1")).json()["doc"]
        assert stored["items"] == sent["items"]
        assert {k: g.get("date") for k, g in stored["gates"].items()} == {
            k: g.get("date") for k, g in sent["gates"].items()
        }
        reader = load_export()
        export = {"_state": stored, "project_id": pid}
        assert versions[-1]["md5"] == reader.fingerprint(export)["md5"]
        # Had the server stored exactly what was sent, it would be the export's.
        same = {**stored, "access": sent["access"], "gates": sent["gates"]}
        assert content_md5({**same, "id": pid}) == SAMPLE["fingerprint"]["md5"]


@requires_db
class TestALoneSurrogateIsRefused:
    async def test_the_server_refuses_a_record_it_cannot_store(
        self, client: AsyncClient
    ):
        """PostgreSQL's jsonb cannot hold a lone surrogate, so the record is refused
        whole, with a 4xx the dashboard reports, not a 500 (docs/exports.md)."""
        body = '{"meta": {"solution": "a \\ud800 b"}, "items": {}}'
        r = await client.post(
            "/api/projects/p-lone",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422, r.text
        listed = (await client.get("/api/projects")).json()
        assert "p-lone" not in [p["id"] for p in listed]


@requires_db
class TestAnOlderRecordIsHashedAsStored:
    async def test_the_revision_is_the_stored_records_fingerprint(
        self, client: AsyncClient
    ):
        """A record from an older version of the dashboard lacks fields its
        normalize() now fills (meta.chaiUseCase, access, card, a checkpoint). The
        dashboard used to hash the filled-in copy, the server the stored one, so the
        same record had two fingerprints. Both now hash the record as stored: the
        dashboard's side is tests/test_export_schema.py ('an older record')."""
        pid = "p-older"
        older = {
            "meta": {"solution": "An older record", "riskTier": "High"},
            "items": {"s1-1": {"status": "met"}},
            "gates": {"A": {"decision": "Approve"}},
            "metrics": [],
            "archived": False,
            "createdAt": "2024-01-01T00:00:00.000Z",
        }
        assert (await client.post(f"/api/projects/{pid}", json=older)).status_code in (
            200,
            201,
        )
        versions = (await client.get(f"/api/projects/{pid}/versions")).json()
        stored = (await client.get(f"/api/projects/{pid}/versions/1")).json()["doc"]
        reader = load_export()
        as_stored = reader.fingerprint({"_state": stored, "project_id": pid})["md5"]
        assert versions[-1]["md5"] == as_stored
        filled = json.loads(json.dumps(stored))
        filled["meta"]["chaiUseCase"] = ""
        filled["card"] = {}
        filled["gates"].update({"B": {}, "C": {}, "D": {}})
        as_filled = reader.fingerprint({"_state": filled, "project_id": pid})["md5"]
        assert as_filled != as_stored
