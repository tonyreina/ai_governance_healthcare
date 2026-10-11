#!/usr/bin/env python3
"""Real JSON exports validate against the schema published for them (#177).

schema/project.schema.json is published as the contract for "Download project
data (JSON)", and nothing checked a real export against it, so it could drift
from projectJSON() unnoticed. It had: the exports carried fields it did not
describe, and it refused every export of a build of another framework (D-79),
whose id is not `chai-review/2`. This drives the real page, in a real browser,
and validates what it exports with a real JSON Schema validator (jsonschema,
Draft 2020-12), twice: as published, and with every object the schema describes
closed, so a field the export writes and the schema does not name fails too.

Exported and validated:

  * the published build: every sample project with OPTICA off and on, an empty
    project, a project whose every typed field holds a hostile value (the
    payloads of tests/test_injection.py), and evidence references (a link and a
    file); the export in every language is the English one, so the schema's
    English values cover them all;
  * the example framework's build (app/frameworks/example/): its samples (in
    every language), an empty project and a hostile one, and its definition's
    values (statuses, categories, sections, checkpoints, phases) are the ones its
    export uses.

Where the schema fixes a framework's values (the `chai-review/2` and
`example-review/1` conditions), each list is checked against the definition, so
the two cannot drift either, and every primary definition must have a condition.

And the fingerprint (#150) is recomputed from every export by
examples/load_export.py, including a record keyed by numbers ("9", "10"), which
the dashboard used to hash in an order no reader would recompute; the dashboard
gives tests/fixtures/fingerprint_record.json the digests in that file, which the
server and load_export.py give it too (server/tests/test_fingerprint.py); and a
new project's first history entry carries the fingerprint the setup page shows.

Every field the export always writes is required: each is dropped in turn and
must be refused. The record (_state) is described as the dashboard writes it, and
bogus answers, references, card fields, supplements and statuses are refused. The
schema is at least as precise as the one before #177
(tests/fixtures/project.schema.before-177.json): every mutant of a real export
that one refused, this one refuses, but for another framework's export id.

Every sample, of both builds, exports the same file in every language, a dated
flag included (its date was in the reader's language), and so does a record
planted with a review due soon, whose amber flag is checked for its shape and its
English date. An older record, missing fields the dashboard fills in, is hashed
and exported as stored, as the server hashes it: in the JSON, the HTML (and so
PDF) and Markdown reports and the history view, and again after an edit, once
the store has sent the record back. A record made by a signed-in person (access
lists, createdBy) with an OPTICA answer declined with its reason, an owner, a due
date and a file added through the evidence form is exported and its shapes
checked, a file's size an integer. A lone surrogate survives the trip from the
downloaded file to load_export.py. tests/fixtures/sample_export.json, a real
export the server's tests hash, still carries the dashboard's digest.

The example framework's build is held to its condition in the schema: an answer
has only the fields every framework writes (its definition names no reason
field), so a text field added to one, or `due` under another name, is refused.

Coverage: every path the schema describes has a value in some valid export made
here, or is listed in UNEXERCISED with the reason.

The validator is shown failing: a missing field, a foreign export id, a value
outside the published framework's lists, an undescribed field (closed only), a
bad date.

    pixi run test-export-schema
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
SCHEMA_PATH = ROOT / "schema" / "project.schema.json"
FRAMEWORK_SCHEMA = ROOT / "schema" / "framework.schema.json"
CHAI_DEF = ROOT / "app" / "frameworks" / "chai" / "framework.json"
EXAMPLE_CONFIG = ROOT / "app" / "frameworks" / "example" / "build.json"
GOLDEN = ROOT / "tests" / "fixtures" / "fingerprint_record.json"
# A real export of a sample (the published build's "Sepsis early warning (sample)",
# a link and a file added as evidence): the server's tests hash its record and must
# get the digest the dashboard wrote into it (server/tests/test_fingerprint.py).
SAMPLE_EXPORT = ROOT / "tests" / "fixtures" / "sample_export.json"
# The schema as it was before #177 (chai-review/2 only), to show the new one refuses
# everything it refused, but for the export id it now lets other frameworks use.
BEFORE = ROOT / "tests" / "fixtures" / "project.schema.before-177.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import build_app  # noqa: E402
from test_injection import PAYLOADS  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LOADER = load_module("load_export", ROOT / "examples" / "load_export.py")
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# The frameworks the schema names under a condition of their own export id.
CONDITIONS = {"chai-review/2": "chai", "example-review/1": "example"}


def closed(schema: object, path: tuple[str, ...] = ()) -> object:
    """The schema with every object it describes closed to other fields.

    A framework's conditional lists (`$defs/chai`, `$defs/example`) only narrow
    values the open part already describes, so they are left as they are."""
    if isinstance(schema, dict):
        if len(path) >= 2 and path[-2] == "$defs" and path[-1] in CONDITIONS.values():
            return schema
        out = {k: closed(v, (*path, k)) for k, v in schema.items()}
        if "properties" in out and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [closed(v, path) for v in schema]
    return schema


Draft202012Validator.check_schema(SCHEMA)
OPEN = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
CLOSED = Draft202012Validator(closed(SCHEMA), format_checker=FormatChecker())
OLD = Draft202012Validator(
    json.loads(BEFORE.read_text(encoding="utf-8")), format_checker=FormatChecker()
)


def problems(export: dict) -> list[str]:
    """Every way an export breaks the schema, published or closed."""
    out = []
    for kind, validator in (("", OPEN), ("closed: ", CLOSED)):
        for e in validator.iter_errors(export):
            where = "/".join(str(p) for p in e.absolute_path) or "(top)"
            out.append(f"{kind}{where}: {e.message[:160]}")
    # jsonschema checks "date" itself but needs an extra package for "date-time",
    # so the export's own time stamp is checked here.
    try:
        when = dt.datetime.fromisoformat(str(export.get("generated")))
        if when.tzinfo is None:
            out.append("generated: no time zone")
    except ValueError:
        out.append(f"generated: not a date-time: {export.get('generated')!r}")
    return out


# Every export found valid, for the coverage walk (schema_covered).
VALID_EXPORTS: list[dict] = []


def valid(name: str, export: dict) -> None:
    found = problems(export)
    check(name, not found, "; ".join(sorted(set(found))[:6]))
    if not found:
        VALID_EXPORTS.append(copy.deepcopy(export))


def verified(name: str, export: dict) -> None:
    check(
        name,
        LOADER.verify_fingerprint(export) is True,
        f"{export.get('fingerprint')} vs {LOADER.fingerprint(export)}",
    )


def wait_until(page, expr: str, timeout: float = 15000) -> None:
    page.wait_for_function(f"() => !!({expr})", timeout=timeout)


def settle(page) -> None:
    last, same = None, 0
    while same < 10:
        now = page.evaluate(
            "JSON.stringify([Object.keys(pending).length,"
            " Object.values(flushing).some(Boolean), (LOG||[]).length])"
        )
        same = same + 1 if now == last else 0
        last = now
        page.wait_for_timeout(40)


def open_app(browser, index: Path):
    page = browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(index.as_uri())
    wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
    return page, errors


def export_of(page) -> dict:
    return json.loads(page.evaluate("JSON.stringify(projectJSON(S))"))


def without_stamp(export: dict) -> dict:
    out = copy.deepcopy(export)
    out.pop("generated", None)
    return out


# Every field a person types, poisoned; the selects (risk tier, a decision, a
# status, a metric's category) hold one of their options, as the page lets them.
POISON = """(p) => {
  S.meta = Object.assign(S.meta, {solution: p, org: p, developer: p, sourcing: p,
    sponsor: p, reviewers: p, reviewCadence: p, startDate: p, scope: p});
  const fw = spine();
  for (const it of fw.items()) {
    const a = (S.items[it.id] = S.items[it.id] || {});
    Object.assign(a, {evidence: p, owner: p, due: p});
  }
  for (const g of fw.gates()) {
    const r = (S.gates[g.id] = S.gates[g.id] || {});
    Object.assign(r, {by: p, rationale: p, date: p});
  }
  S.metrics = (S.metrics || []).map(m =>
    Object.assign({}, m, {name: p, value: p, ci: p, pop: p}));
  if (typeof CARD_FIELDS !== "undefined") for (const k of CARD_FIELDS) S.card[k] = p;
  const first = fw.items()[0].id;
  S.items[first].refs = {rpoison1: {title: p,
    url: "https://example.org/" + encodeURIComponent(p),
    date: "2026-03-04", at: "2026-03-04T00:00:00Z"}};
  STORED.delete(S);  // written here, not saved: this copy is the record
}"""

# A link and a file, as the page stores them (D-70).
REFS = """() => {
  const it = spine().items()[0].id;
  S.items[it] = Object.assign(S.items[it] || {}, {refs: {
    rlink0001: {title: "Validation report", url: "https://example.org/report?id=7",
                date: "2026-03-04", at: "2026-03-04T10:00:00Z"},
    rfile0001: {title: "", url: "", date: "", at: "2026-03-05T10:00:00Z",
                file: {name: "validation.pdf", size: 1048576, sha256: "ab".repeat(32)}},
  }});
  STORED.delete(S);  // written here, not saved: this copy is the record
  return it;
}"""

# A record keyed by numbers, which a JavaScript object lists in numeric order
# whatever order its keys were added in.
NUMERIC = """() => {
  S.card = Object.assign(S.card || {}, {"9": "nine", "10": "ten", "1": "one"});
  S.meta.solution = "Keyed by numbers \\uffff \\u{1F600}";
  STORED.delete(S);  // written here, not saved: this copy is the record
}"""


def hostile_problems(page, pid: str, where: str) -> None:
    """Every typed field holding each payload: valid, and its fingerprint recomputed."""
    bad: list[str] = []
    for i, payload in enumerate(PAYLOADS):
        page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
        settle(page)
        page.evaluate(POISON, payload)
        hostile = export_of(page)
        if hostile["meta"]["solution"] != payload:
            bad.append(f"{i}: the payload is not in the export")
        bad += [f"{i}: {f}" for f in problems(hostile)[:2]]
        if LOADER.verify_fingerprint(hostile) is not True:
            bad.append(f"{i}: the fingerprint does not recompute")
    check(
        f"{where}: every typed field holding each of {len(PAYLOADS)} hostile values"
        " validates and its fingerprint recomputes",
        not bad,
        "; ".join(bad[:4]),
    )


def validator_fails(page_export: dict) -> None:
    print("The validator, shown failing (mutation)")
    base = copy.deepcopy(page_export)
    check(
        "the export it starts from is valid",
        not problems(base),
        str(problems(base)[:3]),
    )
    cases: list[tuple[str, dict]] = []
    e = copy.deepcopy(base)
    del e["checklist"]
    cases.append(("a missing checklist", e))
    e = copy.deepcopy(base)
    e["schema"] = "chai review 2"
    cases.append(("an export id not of the form <id>-review/<n>", e))
    e = copy.deepcopy(base)
    e["checklist"][0]["status"] = "done"
    cases.append(("a status CHAI does not have, in a chai-review/2 export", e))
    e = copy.deepcopy(base)
    e["scores"]["X"] = 3
    cases.append(("a score for a category CHAI does not have", e))
    e = copy.deepcopy(base)
    e["next_review"] = "next spring"
    cases.append(("a next review that is not a date", e))
    e = copy.deepcopy(base)
    e["generated"] = "yesterday"
    cases.append(("an export time that is not a date-time", e))
    e = copy.deepcopy(base)
    e["fingerprint"]["sha256"] = "x" * 64
    cases.append(("a SHA-256 that is not hex", e))
    for name, broken in cases:
        check(f"{name} is refused", bool(problems(broken)))
    e = copy.deepcopy(base)
    e["surprise"] = 1
    e["_state"]["meta"]["surprise"] = 1
    check(
        "an undescribed field passes as published (the schema stays open to readers)",
        not list(OPEN.iter_errors(e)),
    )
    check("and is refused closed", bool(list(CLOSED.iter_errors(e))))
    e = copy.deepcopy(base)
    e["schema"] = "acme-review/1"
    e["checklist"][0]["status"] = "done"
    e["checklist"][0]["principle"] = "benefit"
    e["checklist"][0]["id"] = "plan-purpose"
    e["scores"] = {"overall": 1, "benefit": 1}
    check(
        "another framework's export is held to the structure, not CHAI's lists",
        not problems(e),
        str(problems(e)[:3]),
    )


def chai_lists_match_definition(page) -> None:
    print("The schema's CHAI lists are CHAI's definition")
    chai = SCHEMA.get("$defs", {}).get("chai", {}).get("properties")
    check("the schema states them, under the chai-review/2 condition", bool(chai))
    if not chai:
        return
    d = json.loads(CHAI_DEF.read_text(encoding="utf-8"))
    item = chai["checklist"]["items"]["properties"]
    statuses = [s["value"] for s in d["statuses"]]
    check(
        "statuses (and null, unanswered)",
        item["status"]["enum"] == [*statuses, None],
        str(item["status"]["enum"]),
    )
    cats = [c["id"] for c in d["categories"]]
    check(
        "categories", item["principle"]["enum"] == cats, str(item["principle"]["enum"])
    )
    check(
        "scores: overall and one per category",
        chai["scores"]["propertyNames"]["enum"] == ["overall", *cats]
        and chai["scores"]["required"] == ["overall", *cats],
    )
    check(
        "the last section's number",
        item["stage"]["maximum"] == max(s["n"] for s in d["sections"]),
    )
    ids = [i["id"] for s in d["sections"] for i in s["items"]]
    check(
        "every item id fits the id pattern",
        all(re.fullmatch(item["id"]["pattern"].strip("^$"), i) for i in ids),
    )
    check(
        "checkpoints",
        chai["gates"]["propertyNames"]["enum"] == [g["id"] for g in d["gates"]],
    )
    check(
        "phases, and the engine's two ends",
        chai["phase"]["enum"]
        == [p["label"] for p in d["phases"]] + ["Retired", "Stopped"],
        str(chai["phase"]["enum"]),
    )
    check(
        "metric categories are the page's",
        chai["metrics"]["items"]["properties"]["cat"]["enum"]
        == page.evaluate("METRIC_CATS"),
    )
    check(
        "the record's lists are stated too (_state: answers, card, supplements)",
        "_state" in chai and "model_card" in chai,
    )
    if "_state" not in chai or "model_card" not in chai:
        return
    state = chai["_state"]["properties"]
    answer = state["items"]["additionalProperties"]
    check(
        "the record's statuses: CHAI's, '' (cleared) and null",
        answer["properties"]["status"]["enum"] == [*statuses, "", None],
        str(answer["properties"]["status"]["enum"]),
    )
    fields = SCHEMA["$defs"]["answer"]["properties"]
    reasons = [s["reasonField"] for s in d["statuses"] if "reasonField" in s]
    check(
        "an answer's fields: the ones the dashboard writes (CHAI asks no reason)",
        answer["propertyNames"]["enum"] == [*fields, *reasons],
        str(answer["propertyNames"]["enum"]),
    )
    check(
        "the record's item ids fit the same pattern",
        state["items"]["propertyNames"]["pattern"] == item["id"]["pattern"],
    )
    check(
        "the record's checkpoints",
        state["gates"]["propertyNames"]["enum"] == [g["id"] for g in d["gates"]],
    )
    check(
        "the record's metric categories are the page's (the old schema's, #177)",
        state["metrics"]["items"]["properties"]["cat"]["enum"]
        == page.evaluate("METRIC_CATS"),
    )
    card = page.evaluate("CARD_FIELDS")
    check(
        "the record's card fields are the page's",
        state["card"]["propertyNames"]["enum"] == card,
    )
    check(
        "the model card is every card field, and only them",
        chai["model_card"]["required"] == card
        and chai["model_card"]["propertyNames"]["enum"] == card,
    )
    supplements = page.evaluate(
        "FRAMEWORKS.filter(f => f.def && !f.primary).map(f => f.id)"
    )
    state_keys = chai["_state"]["propertyNames"]["enum"]
    check(
        "the record's keys: the ones the schema describes, and the published build's"
        " supplements",
        state_keys == [*SCHEMA["properties"]["_state"]["properties"], *supplements]
        and supplements == ["optica"],
        f"{state_keys} vs {supplements}",
    )
    for sid in supplements:
        sd = json.loads(
            (ROOT / "app" / "frameworks" / sid / "framework.json").read_text("utf-8")
        )
        sup = state[sid]["properties"]["answers"]
        sanswer = sup["additionalProperties"]
        sstat = [s["value"] for s in sd["statuses"]]
        check(
            f"{sid}: its statuses, '' and null",
            sanswer["properties"]["status"]["enum"] == [*sstat, "", None],
            str(sanswer["properties"]["status"]["enum"]),
        )
        sreasons = [s["reasonField"] for s in sd["statuses"] if "reasonField" in s]
        check(
            f"{sid}: an answer's fields, and the reason its statuses ask for",
            sanswer["propertyNames"]["enum"] == [*fields, *sreasons],
            str(sanswer["propertyNames"]["enum"]),
        )
        sids = [i["id"] for s in sd["sections"] for i in s["items"]]
        check(
            f"{sid}: every item id fits its id pattern",
            all(
                re.fullmatch(sup["propertyNames"]["pattern"].strip("^$"), i)
                for i in sids
            ),
        )
        check(
            f"{sid}: a supplement's fields",
            state[sid]["propertyNames"]["enum"]
            == list(SCHEMA["$defs"]["supplement"]["properties"]),
        )
    fw_pattern = json.loads(FRAMEWORK_SCHEMA.read_text(encoding="utf-8"))
    sid = fw_pattern["properties"]["export"]["properties"]["schemaId"]["pattern"]
    check(
        "the export id pattern is the one a definition's schemaId must match",
        SCHEMA["properties"]["schema"]["pattern"] == sid,
        f"{SCHEMA['properties']['schema']['pattern']} != {sid}",
    )


def refused(export: dict) -> bool:
    """The published schema, as a reader's validator runs it, refuses this."""
    return bool(list(OPEN.iter_errors(export)))


def required_fields(export: dict, where: str, chai: bool) -> None:
    """Every field projectJSON() always writes is required: an export missing any one
    is refused, so dropping a field from the export cannot go unnoticed (#177). Each
    is dropped in turn (mutation), at the top and inside each object it always
    writes whole."""
    paths: list[tuple] = [(k,) for k in export]
    paths += [("checklist", 0, k) for k in export["checklist"][0]]
    for obj in ("fingerprint", "storage"):
        paths += [(obj, k) for k in export[obj]]
    if export["flags"]:
        paths += [("flags", 0, k) for k in export["flags"][0]]
    # A category's score is the definition's; the schema names CHAI's.
    paths += [("scores", k) for k in (export["scores"] if chai else ["overall"])]
    if chai:
        paths += [("model_card", k) for k in export["model_card"]]
    missed = []
    for path in paths:
        e = copy.deepcopy(export)
        node = e
        for step in path[:-1]:
            node = node[step]
        del node[path[-1]]
        if not refused(e):
            missed.append("/".join(map(str, path)))
    check(
        f"{where}: dropping any of the {len(paths)} fields the export always writes"
        " is refused (mutation, each in turn)",
        not missed,
        f"not noticed: {missed}",
    )
    check(
        f"{where}: the top-level fields the schema requires are the ones written",
        set(export) == set(SCHEMA["required"]) | ({"model_card"} if chai else set()),
        str(sorted(set(export) ^ set(SCHEMA["required"]))),
    )


def mutants(base: dict, cases: list[tuple[str, str]]) -> list[tuple[str, dict]]:
    """(name, a Python statement over `e`, a deep copy of base) -> (name, mutant)."""
    out = []
    for name, stmt in cases:
        e = copy.deepcopy(base)
        exec(stmt, {}, {"e": e})  # a fixed statement written in this file
        out.append((name, e))
    return out


# What the dashboard stores for each answer, a reference and a supplement, and what
# it refuses to be (#177): each of these must be refused in a CHAI export.
STATE_BOGUS_CHAI = [
    (
        "an answer's status CHAI does not have",
        "e['_state']['items'][I]['status'] = 'Bogus'",
    ),
    ("a field an answer does not have", "e['_state']['items'][I]['surprise'] = 'x'"),
    ("an answer that is not an object", "e['_state']['items'][I] = 'met'"),
    (
        "an answer's evidence that is not text",
        "e['_state']['items'][I]['evidence'] = 3",
    ),
    ("an answer under an id CHAI does not have", "e['_state']['items']['zz-9'] = {}"),
    (
        "a reference under an id the dashboard never makes",
        "e['_state']['items'][I]['refs'] = {'notaref': {'title': 't'}}",
    ),
    (
        "a reference field that is not text",
        "e['_state']['items'][I]['refs'] = {'rlink0001': {'title': 5}}",
    ),
    (
        "a field a reference does not have",
        "e['_state']['items'][I]['refs'] = {'rlink0001': {'surprise': 'x'}}",
    ),
    (
        "a reference file whose SHA-256 is not hex",
        "e['_state']['items'][I]['refs'] = {'rfile0001': {'file': {'name': 'a',"
        " 'size': 1, 'sha256': 'x'}}}",
    ),
    (
        "a top-level key of the record that is not one CHAI's build writes",
        "e['_state']['bogus'] = {}",
    ),
    ("an unknown supplement, shaped as one", "e['_state']['nist'] = {'answers': {}}"),
    ("a card field CHAI does not have", "e['_state']['card']['surprise'] = 'x'"),
    ("a card field that is not text", "e['_state']['card']['name'] = 5"),
    (
        "a checkpoint CHAI does not have, in the record",
        "e['_state']['gates']['Z'] = {}",
    ),
    (
        "a metric category CHAI does not have, in the record (regression: the old"
        " schema refused it)",
        "e['_state']['metrics'][0]['cat'] = 'Bogus'",
    ),
    ("a field a supplement does not have", "e['_state']['optica']['surprise'] = 1"),
    (
        "OPTICA's enabled that is not true or false",
        "e['_state']['optica']['enabled'] = 'yes'",
    ),
    (
        "an OPTICA status OPTICA does not have",
        "e['_state']['optica']['answers'][O]['status'] = 'Bogus'",
    ),
    (
        "a field an OPTICA answer does not have",
        "e['_state']['optica']['answers'][O]['surprise'] = 'x'",
    ),
    (
        "an OPTICA answer under an id OPTICA does not have",
        "e['_state']['optica']['answers']['zz-9'] = {}",
    ),
    (
        "a reference file's size that is text (X04: an integer)",
        "e['_state']['items'][I]['refs'] = {'rfile0001': {'file': {'name': 'a',"
        " 'size': '1', 'sha256': 'ab' * 32}}}",
    ),
    (
        "a reference file's size that is a fraction (X04: an integer)",
        "e['_state']['items'][I]['refs'] = {'rfile0001': {'file': {'name': 'a',"
        " 'size': 1.5, 'sha256': 'ab' * 32}}}",
    ),
    ("an access list that is not of user ids", "e['_state']['access']['owners'] = [3]"),
    ("a field access does not have", "e['_state']['access']['surprise'] = []"),
    ("a model card field CHAI does not have", "e['model_card']['surprise'] = 'x'"),
]

# And what the dashboard does write, which must still pass.
STATE_GOOD_CHAI = [
    (
        "an OPTICA answer declined, with its reason",
        "e['_state']['optica']['answers'][O] = {'status': 'declined',"
        " 'declineReason': 'r'}",
    ),
    (
        "a status cleared ('' is what clearing stores)",
        "e['_state']['items'][I]['status'] = ''",
    ),
    (
        "a removed reference (null at its id)",
        "e['_state']['items'][I]['refs'] = {'rlink0001': None}",
    ),
]

# Another framework's: its values are its definition's, but the shapes are fixed.
STATE_BOGUS_GENERAL = [
    ("an answer field that is not text", "e['_state']['items'][I]['surprise'] = {}"),
    ("an answer that is not an object", "e['_state']['items'][I] = 'done'"),
    ("a supplement that is not an object", "e['_state']['other'] = 1"),
    ("a supplement under a key no framework id can be", "e['_state']['a.b'] = {}"),
    ("a field a supplement does not have", "e['_state']['other'] = {'surprise': 1}"),
    (
        "a supplement's answer field that is not text",
        "e['_state']['other'] = {'answers': {'x': {'surprise': {}}}}",
    ),
    ("a card field that is not text", "e['_state']['card']['x'] = 5"),
]


# What the example framework's build must not write (J11, J12): its definition
# names no reason field, so an answer holds only the fields every framework writes.
STATE_BOGUS_EXAMPLE = [
    (
        "a text field an answer does not have (its definition names no reason)",
        "e['_state']['items'][I]['surprise'] = 'x'",
    ),
    (
        "an answer's due date written under another name",
        "a = e['_state']['items'][I]; a['dueDate'] = a.pop('due', '')",
    ),
    ("a supplement the build does not have", "e['_state']['optica'] = {}"),
    (
        "a model card field (the build has no model card)",
        "e['_state']['card']['x'] = 'y'",
    ),
]


def example_condition(page, d: dict) -> None:
    """The schema's `example-review/1` condition is the example's definition: an
    answer's fields are the ones every framework writes and the reasons its
    statuses ask for (none), and the record's keys are the described ones and the
    build's supplements (none)."""
    cond = SCHEMA.get("$defs", {}).get("example", {}).get("properties", {})
    check(
        "the schema names the example framework, by its export id",
        CONDITIONS.get(d["export"]["schemaId"]) == "example" and bool(cond),
    )
    if not cond:
        return
    fields = list(SCHEMA["$defs"]["answer"]["properties"])
    reasons = [s["reasonField"] for s in d["statuses"] if "reasonField" in s]
    answer = cond["_state"]["properties"]["items"]["additionalProperties"]
    check(
        "an answer's fields: the ones every framework writes, and its reasons",
        answer["propertyNames"]["enum"] == [*fields, *reasons],
        str(answer["propertyNames"]["enum"]),
    )
    supplements = page.evaluate(
        "FRAMEWORKS.filter(f => f.def && !f.primary).map(f => f.id)"
    )
    check(
        "the record's keys: the described ones, and the build's supplements",
        cond["_state"]["propertyNames"]["enum"]
        == [*SCHEMA["properties"]["_state"]["properties"], *supplements],
        f"{cond['_state']['propertyNames']['enum']} vs {supplements}",
    )
    check(
        "the record's model card is empty, as the build has no card fields",
        cond["_state"]["properties"]["card"].get("maxProperties") == 0
        and page.evaluate("typeof CARD_FIELDS === 'undefined'"),
    )
    conditioned = [
        c["if"]["properties"]["schema"]["const"] for c in SCHEMA.get("allOf", [])
    ]
    primaries = sorted(
        json.loads(f.read_text(encoding="utf-8"))["export"]["schemaId"]
        for f in (ROOT / "app" / "frameworks").glob("*/framework.json")
        if json.loads(f.read_text(encoding="utf-8")).get("role") == "primary"
    )
    check(
        "every primary framework in this repository has a condition, and no other",
        sorted(conditioned) == sorted(CONDITIONS) == primaries,
        f"{conditioned} vs {primaries}",
    )


def unnamed_framework_reason(base: dict) -> None:
    """A framework the schema does not name may carry the reason field its own
    definition names: the schema cannot list it, so any text field is allowed."""
    e = copy.deepcopy(base)
    e["schema"] = "acme-review/1"
    first = next(iter(e["_state"]["items"]))
    e["_state"]["items"][first]["whyNot"] = "a reason"
    check(
        "another framework's answer may carry its reason field (a text field)",
        not problems(e),
        str(problems(e)[:2]),
    )


def state_closed(base: dict, where: str, cases: list, good: list = ()) -> None:
    """The record (_state) is described closed: each bogus value is refused."""
    item = next(iter(base["_state"]["items"]))
    opt = next(iter((base["_state"].get("optica") or {}).get("answers") or {}), None)
    head = f"I = {item!r}; O = {opt!r}; "
    for name, broken in mutants(base, [(n, head + c) for n, c in cases]):
        check(f"{where}: {name} is refused", bool(problems(broken)))
    for name, fine in mutants(base, [(n, head + c) for n, c in good]):
        check(f"{where}: {name} passes", not problems(fine), str(problems(fine)[:2]))


def leaf_paths(value: object, path: tuple = ()):
    """Every path in an export, taking the first element of each list and the first
    two entries of a map keyed by ids (items, answers), which are alike."""
    yield path
    if isinstance(value, dict):
        keys = list(value)
        if len(keys) > 12 and all(isinstance(value[k], dict) for k in keys):
            keys = keys[:2]
        for k in keys:
            yield from leaf_paths(value[k], (*path, k))
    elif isinstance(value, list) and value:
        yield from leaf_paths(value[0], (*path, 0))


def as_precise_as_before(base: dict) -> None:
    """D-82: the published contract is as precise as it was. Every mutant of a real
    CHAI export that the schema before #177 refused, the schema now refuses too,
    except a foreign export id, which it now allows on purpose (another framework's
    export). Mutants: each path set to text, a number, null, true, an object and a
    list, and deleted."""
    print("As precise as it was: what the old schema refused, the new one refuses")
    bogus = ["Bogus", 99, None, True, {}, []]
    tried = caught = 0
    loosened: list[str] = []
    for path in leaf_paths(base):
        if not path or path == ("schema",):
            continue
        for value in [*bogus, "<delete>"]:
            e = copy.deepcopy(base)
            node = e
            for step in path[:-1]:
                node = node[step]
            if value == "<delete>":
                if not isinstance(node, dict):
                    continue
                del node[path[-1]]
            else:
                node[path[-1]] = value
            if not list(OLD.iter_errors(e)):
                continue
            tried += 1
            if refused(e):
                caught += 1
            else:
                loosened.append(f"{'/'.join(map(str, path))}={value!r}")
    check(
        f"the old schema refused {tried} mutants; the new one refuses them all",
        tried > 50 and not loosened,
        f"{len(loosened)} now pass: {loosened[:8]}",
    )
    e = copy.deepcopy(base)
    e["schema"] = "acme-review/1"
    check(
        "the one intended difference: another framework's export id (one the schema"
        " names no lists for)",
        bool(list(OLD.iter_errors(e))) and not refused(e),
    )


def reports_carry(page, md5: str, sha256: str, where: str, not_md5: str = "") -> None:
    """The HTML report (which the PDF prints) and the Markdown report print the
    fingerprint of the stored record, not of the copy filled in to show it."""
    for name, expr in (
        ("the HTML and PDF report", "exportHTML()"),
        ("the Markdown report", "exportMD()"),
    ):
        text = page.evaluate(expr)
        check(
            f"{where}: {name} prints the stored record's fingerprint (regression)",
            md5 in text and sha256 in text and (not not_md5 or not_md5 not in text),
            "the stored record's digests are not in it"
            if md5 not in text or sha256 not in text
            else "the filled-in copy's digest is in it",
        )


def older_record(page) -> None:
    """A record an older dashboard wrote lacks fields normalize() now fills. The
    dashboard hashed its filled-in copy and the server the stored record, so the
    same record had two fingerprints (#177). It is the stored record's, everywhere
    the dashboard shows or writes one, and the export's record is the stored one, so
    a reader recomputes the same digest. That holds after an edit too, once the
    store has sent the record back (onProjects), which is when the dashboard builds
    its copies again."""
    print("An older record, missing fields the dashboard fills in")
    pid = "p-older"
    stored = page.evaluate(
        """async (pid) => {
          const doc = clone(S); delete doc.id;
          doc.meta.solution = "An older record";
          delete doc.meta.chaiUseCase; delete doc.access; delete doc.card;
          delete doc.cardUpdatedAt; delete doc.createdBy;
          for (const k of Object.keys(doc.gates).slice(1)) delete doc.gates[k];
          await STORE.create(pid, doc);
          return doc;
        }""",
        pid,
    )
    wait_until(page, f"PROJECTS.has({json.dumps(pid)})")
    page.evaluate(f"openProject({json.dumps(pid)}, 'changelog')")
    settle(page)
    want = LOADER.fingerprint({"_state": stored, "project_id": pid})
    filled = page.evaluate("S.meta.chaiUseCase")
    check("the dashboard fills it in to show it", filled == "", repr(filled))
    of_filled = page.evaluate("contentHashes(S)")
    check(
        "the filled-in copy hashes differently, so the checks below can tell them"
        " apart",
        of_filled["md5"] != want["md5"],
    )
    exported = export_of(page)
    got = {k: exported["fingerprint"][k] for k in ("md5", "sha256")}
    check(
        "its export's fingerprint is the stored record's, which the server's version"
        " history gives it (regression)",
        got == want,
        f"{got} != {want}",
    )
    check(
        "its export's record (_state) is the record as stored",
        exported["_state"] == stored,
        str(sorted(set(exported["_state"]) ^ set(stored))),
    )
    verified("load_export.py recomputes it", exported)
    valid("it validates", exported)
    reports_carry(page, want["md5"], want["sha256"], "older record", of_filled["md5"])
    shown = page.evaluate("changelogHTML()")
    check(
        "the history view shows the stored record's fingerprint",
        want["md5"] in shown and of_filled["md5"] not in shown,
        "not in the view",
    )
    n = page.evaluate("LOG.length")
    page.evaluate("edit('meta.org', 'Later')")
    wait_until(page, f"LOG.length > {n}")
    # Saved: the save waits for typing to pause, so nothing pending is not soon.
    wait_until(
        page, "!Object.keys(pending).length && !Object.values(flushing).some(Boolean)"
    )
    # And sent back: the store's copy reached onProjects, which built S again.
    wait_until(page, f"PROJECTS.get({json.dumps(pid)}).meta.org === 'Later'")
    settle(page)
    after = json.loads(
        page.evaluate(f"JSON.stringify(STORE.d.projects[{json.dumps(pid)}])")
    )
    want_after = LOADER.fingerprint({"_state": after, "project_id": pid})
    entry = page.evaluate("LOG[0].hash")
    check(
        "an edit's history entry carries the fingerprint of what was stored",
        entry == want_after["md5"],
        f"{entry} != {want_after['md5']}",
    )
    check(
        "what was stored is the older record and the edit, nothing filled in",
        "chaiUseCase" not in after["meta"] and "card" not in after,
        str(sorted(after)),
    )
    print("  after the store sent the record back (onProjects)")
    kept = json.loads(page.evaluate("JSON.stringify(storedRecord(S))"))
    kept.pop("id", None)
    check(
        "the dashboard's stored record is the store's, nothing filled in (regression)",
        kept == after,
        str(sorted(set(kept) ^ set(after)) or "the values differ"),
    )
    still_filled = page.evaluate("S.meta.chaiUseCase")
    check("and it still shows the filled-in copy", still_filled == "")
    filled_after = page.evaluate("contentHashes(S)")["md5"]
    check(
        "the filled-in copy still hashes differently after the edit",
        filled_after != want_after["md5"],
    )
    page_shown = page.inner_html("#main")
    check(
        "the history page on screen shows the stored record's fingerprint",
        want_after["md5"] in page_shown and filled_after not in page_shown,
        "the rendered page does not show it",
    )
    shown = page.evaluate("changelogHTML()")
    check(
        "changelogHTML() shows the stored record's fingerprint",
        want_after["md5"] in shown and filled_after not in shown,
        "not in the view",
    )
    exported = export_of(page)
    check(
        "the export's fingerprint and record are the stored record's",
        {k: exported["fingerprint"][k] for k in ("md5", "sha256")} == want_after
        and exported["_state"] == after,
        str(exported["fingerprint"]),
    )
    verified("load_export.py recomputes it after the edit", exported)
    reports_carry(
        page, want_after["md5"], want_after["sha256"], "after the edit", filled_after
    )


# A lone surrogate, which JavaScript allows in a string and UTF-8 cannot encode.
LONE = """() => {
  S.meta.solution = "Lone \\ud800 high, lone \\udfff low";
  S.meta["\\udc00 a key"] = "x";
  STORED.delete(S);  // written here, not saved: this copy is the record
}"""


def lone_surrogate(page) -> None:
    """The file the dashboard downloads, read by load_export.py as a person runs it:
    its fingerprint recomputes. load_export.py raised UnicodeEncodeError (#177)."""
    print("A lone surrogate, end to end")
    canon = page.evaluate("canonicalJSON({'k\\udc00': 'v\\ud800', p: '\\u{1F600}'})")
    check(
        "the dashboard writes a lone surrogate as its lowercase \\u escape",
        canon == '{"k\\udc00":"v\\ud800","p":"\U0001f600"}',
        canon,
    )
    page.evaluate(LONE)
    text = page.evaluate("JSON.stringify(projectJSON(S), null, 2)")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "lone-chai-review.json"
        path.write_text(text, encoding="utf-8")
        run = subprocess.run(
            [sys.executable, str(ROOT / "examples" / "load_export.py"), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    check(
        "load_export.py reads the downloaded file and its fingerprint matches"
        " (regression)",
        run.returncode == 0 and "matches the record" in run.stdout,
        (run.stdout + run.stderr)[-300:],
    )


def english_day(day: str) -> str:
    """A date as the dashboard writes it in English: "Sep 5, 2026"."""
    d = dt.date.fromisoformat(day)
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def review_due(page, pids: list) -> None:
    """J07: a live project whose next review falls within the framework's
    dueSoonDays exports the amber 'review due' flag. No sample has one (their
    reviews are overdue), so one is planted: a sample's record, its clock moved,
    stored as a new project."""
    print("A review due soon: the amber flag, its date in English")
    locales = page.evaluate("[...LOCALE_CHOICES, Locale.PSEUDO]")
    for _, src in pids:
        page.evaluate(f"openProject({json.dumps(src)}, 'setup')")
        settle(page)
        if any(
            (f.get("msg") or [""])[0] == "flag.reviewOverdue"
            for f in export_of(page)["flags"]
        ):
            break
    planted = page.evaluate(
        """async (src) => {
          const E = ENGINES[primaryFramework().id], R = E.review;
          const doc = clone(storedRecord(PROJECTS.get(src))); delete doc.id;
          doc.meta.solution = "A review due soon";
          doc.meta.reviewCadence = "1";
          // The clock starts at the first anchor with a decision (nextReview).
          const k = R.anchors.find(a => (doc.gates[a] || {}).decision)
            || R.anchors[R.anchors.length - 1];
          const target = addDays(parseDay(TODAY()), 10);
          const date = ymd(addMonths(target, -1));
          doc.gates[k] = Object.assign(doc.gates[k] || {}, {date});
          await STORE.create("p-due", doc);
          return {soon: R.dueSoonDays};
        }""",
        src,
    )
    wait_until(page, "PROJECTS.has('p-due')")
    page.evaluate("openProject('p-due', 'setup')")
    settle(page)
    english = export_of(page)
    nr = english["next_review"]
    left = (dt.date.fromisoformat(nr) - dt.date.today()).days if nr else None
    check(
        "the planted record's next review is within dueSoonDays",
        left is not None and 0 <= left <= planted["soon"],
        f"{nr} ({left} days; dueSoonDays {planted['soon']})",
    )
    due = [f for f in english["flags"] if (f.get("msg") or [""])[0] == "flag.reviewDue"]
    check(
        "it exports the amber 'review due' flag, shaped as the schema says",
        len(due) == 1
        and due[0]["sev"] == "amber"
        and due[0]["msg"] == ["flag.reviewDue", {"date": nr}]
        and set(due[0]) == {"sev", "text", "msg"},
        json.dumps(english["flags"]),
    )
    if due:
        check(
            "its text writes the date in English",
            due[0]["text"] == f"Periodic review due {english_day(nr)}",
            due[0]["text"],
        )
    valid("the export with a review due validates", english)
    verified("its fingerprint recomputes", english)
    english = without_stamp(english)
    differ = []
    for loc in locales:
        page.evaluate(f"setLocale({json.dumps(loc)}); relocalize()")
        other = without_stamp(export_of(page))
        if other != english:
            differ.append(f"{loc}: {other.get('flags')}"[:200])
    page.evaluate("setLocale('en'); relocalize()")
    check(
        f"the review-due export is the English one in all {len(locales)} languages",
        not differ,
        "; ".join(differ[:2]),
    )


# A file chosen in the evidence form, as a person adds one.
ADDED_FILE = b"%PDF-1.4 bias audit"


def access_and_optica(page) -> None:
    """J13: a record made by a signed-in person (ME.id set), so its access lists
    and createdBy are not empty, with OPTICA on and one of its answers declined
    with a reason, an owner, a due date and a file added through the evidence
    form. Every write goes through the page's own edits and the store."""
    print("A record with a person's id, access lists and OPTICA's fields")
    page.evaluate("ME.id = 'u-alice'")
    pid = page.evaluate(
        "async () => createProject(normalize(blankProject('Access and OPTICA')),"
        " 'Project created')"
    )
    wait_until(page, f"PROJECTS.has({json.dumps(pid)})")
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    page.evaluate(
        "edit('access.writers', ['u-bob']); edit('access.readers', ['u-carol'])"
    )
    n = page.evaluate("LOG.length")
    page.evaluate("setFrameworkEnabled('optica', true)")
    wait_until(page, f"LOG.length > {n}")
    settle(page)
    item, section, reason = page.evaluate(
        "[ENGINES.optica.items[0].id, ENGINES.optica.items[0].section.n,"
        " FACADES.optica.reason]"
    )
    path = f"optica.answers.{item}"
    page.evaluate(
        f"""() => {{
          edit({json.dumps(path + ".status")}, {json.dumps(reason["value"])});
          edit({json.dumps(path + "." + reason["reasonField"])}, "Out of scope here");
          edit({json.dumps(path + ".owner")}, "Data science");
          edit({json.dumps(path + ".due")}, "2027-01-15");
        }}"""
    )
    page.evaluate(f"go('o{section}')")
    page.click(f'li[data-item="{item}"] [data-toggle="{item}"]')
    row = page.locator(f'li[data-item="{item}"]')
    row.locator('[data-refin="title"]').fill("Bias audit")
    row.locator('[data-refin="file"]').set_input_files(
        files=[
            {"name": "audit.pdf", "mimeType": "application/pdf", "buffer": ADDED_FILE}
        ]
    )
    row.locator("[data-addref]").click()
    wait_until(
        page,
        f"Object.keys((FACADES.optica.answers(S)[{json.dumps(item)}] || {{}}).refs"
        " || {}).length === 1",
    )
    wait_until(
        page, "!Object.keys(pending).length && !Object.values(flushing).some(Boolean)"
    )
    settle(page)
    exported = export_of(page)
    state = exported["_state"]
    valid("it validates", exported)
    verified("its fingerprint recomputes", exported)
    stored = json.loads(
        page.evaluate(f"JSON.stringify(STORE.d.projects[{json.dumps(pid)}])")
    )
    stored.pop("id", None)
    check("its export's record is the one in the store", state == stored)
    check(
        "the access lists hold user ids",
        state.get("access")
        == {"owners": ["u-alice"], "writers": ["u-bob"], "readers": ["u-carol"]},
        json.dumps(state.get("access")),
    )
    check(
        "createdBy and updatedBy are the person's id",
        state.get("createdBy") == "u-alice" and state.get("updatedBy") == "u-alice",
        f"{state.get('createdBy')!r} {state.get('updatedBy')!r}",
    )
    answer = (state.get("optica") or {}).get("answers", {}).get(item, {})
    check(
        "OPTICA's answer: declined, with its reason, an owner and a due date",
        answer.get("status") == reason["value"]
        and answer.get(reason["reasonField"]) == "Out of scope here"
        and answer.get("owner") == "Data science"
        and answer.get("due") == "2027-01-15"
        and set(answer) == {"status", reason["reasonField"], "owner", "due", "refs"},
        json.dumps(answer)[:300],
    )
    refs = answer.get("refs") or {}
    ref = next(iter(refs.values()), {}) or {}
    file = ref.get("file") or {}
    check(
        "the reference: under a reference id, the fields the form writes",
        len(refs) == 1
        and all(re.fullmatch(r"r[a-z0-9]{6,24}", k) for k in refs)
        and set(ref) == {"title", "url", "date", "at", "file"}
        and ref["title"] == "Bias audit"
        and set(file) == {"name", "size", "sha256"},
        json.dumps(refs)[:300],
    )
    check(
        "the file's size is an integer, its byte count (X04), and its SHA-256 the"
        " file's",
        type(file.get("size")) is int
        and file.get("size") == len(ADDED_FILE)
        and file.get("sha256") == hashlib.sha256(ADDED_FILE).hexdigest(),
        json.dumps(file),
    )
    page.evaluate("ME.id = null")


def sample_export_fixture(page) -> None:
    """tests/fixtures/sample_export.json, a real export, is the record the server's
    tests hash: the dashboard still gives its record the digest written in it."""
    fixture = json.loads(SAMPLE_EXPORT.read_text(encoding="utf-8"))
    got = page.evaluate("e => contentHashes({...e._state, id: e.project_id})", fixture)
    check(
        "the committed sample export's fingerprint is the dashboard's digest of its"
        " record",
        got == {k: fixture["fingerprint"][k] for k in ("md5", "sha256")},
        str(got),
    )
    valid("the committed sample export validates", fixture)
    verified("load_export.py recomputes it", fixture)


def golden(page, where: str) -> None:
    fixture = json.loads(GOLDEN.read_text(encoding="utf-8"))
    got = page.evaluate("r => contentHashes(r)", fixture["record"])
    check(
        f"{where}: the shared record's fingerprint is the one the server and"
        " load_export.py give",
        got == {"md5": fixture["md5"], "sha256": fixture["sha256"]},
        str(got),
    )


def published(browser) -> dict:
    print("The published build")
    page, errors = open_app(browser, APP)
    golden(page, "published")
    sample_export_fixture(page)
    chai_lists_match_definition(page)

    page.evaluate("loadSamples()")
    wait_until(page, "PROJECTS && PROJECTS.size >= 10")
    pids = page.evaluate(
        "[...PROJECTS.values()].map(p => [p.meta.solution, p.id]).sort()"
    )
    first_export = None
    on_exports: list[dict] = []
    for name, pid in pids:
        page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
        settle(page)
        off = export_of(page)
        first_export = first_export or off
        valid(f"{name}, OPTICA off", off)
        verified(f"{name}: load_export.py recomputes its fingerprint", off)
        n = page.evaluate("LOG.length")
        page.evaluate("setFrameworkEnabled('optica', true)")
        wait_until(page, f"LOG.length > {n}")
        page.evaluate(
            "() => { const a = FACADES.optica.answers(S);"
            " const ids = ENGINES.optica.items.slice(0, 3).map(i => i.id);"
            " a[ids[0]] = {status: 'met', evidence: 'e'};"
            " a[ids[1]] = {status: 'declined', declineReason: 'r'};"
            # Written here, not saved: this copy is the record.
            " STORED.delete(S); }"
        )
        on = export_of(page)
        check(
            f"{name}, OPTICA on: its record is in the export", "optica" in on["_state"]
        )
        valid(f"{name}, OPTICA on", on)
        on_exports.append(on)
        verified(f"{name}, OPTICA on: fingerprint recomputed", on)
        n = page.evaluate("LOG.length")
        page.evaluate("setFrameworkEnabled('optica', false)")
        wait_until(page, f"LOG.length > {n}")
        settle(page)

    print("Every language exports the same file, for every sample")
    # A flag's text is English in the export (and the portfolio CSV): a dated flag
    # wrote its date in the reader's language ("5. Sept. 2026"), so the German
    # export of a project with a review due differed from the English one (#177).
    locales = page.evaluate("[...LOCALE_CHOICES, Locale.PSEUDO]")
    dated = 0
    for name, pid in pids:
        page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
        settle(page)
        english = without_stamp(export_of(page))
        for f in english["flags"]:
            if (f.get("msg") or [""])[0] in ("flag.reviewOverdue", "flag.reviewDue"):
                dated += 1
                check(
                    f"{name}: a dated flag's date is written in English",
                    bool(re.search(r"\b[A-Z][a-z]{2} \d{1,2}, \d{4}$", f["text"])),
                    f["text"],
                )
        differ = []
        for loc in locales:
            page.evaluate(f"setLocale({json.dumps(loc)}); relocalize()")
            other = without_stamp(export_of(page))
            if other != english:
                diff = [k for k in english if other.get(k) != english[k]]
                differ.append(f"{loc}: {diff} {other.get('flags')}"[:240])
        page.evaluate("setLocale('en'); relocalize()")
        check(
            f"{name}: the export is the English one in all {len(locales)} languages",
            not differ,
            "; ".join(differ[:2]),
        )
    check(
        "a sample has a dated flag, so the languages were compared on one",
        dated > 0,
        "no sample has a review flag",
    )
    differ = []
    english_csv = page.evaluate("exportCSV()")
    for loc in locales:
        page.evaluate(f"setLocale({json.dumps(loc)}); relocalize()")
        other = page.evaluate("exportCSV()")
        if other != english_csv:
            differ.append(f"{loc}: {other[:200]}")
    page.evaluate("setLocale('en'); relocalize()")
    check(
        "the portfolio CSV is the English one in every language",
        not differ,
        str(differ),
    )
    review_due(page, pids)

    print("An empty project, references, a hostile one, one keyed by numbers")
    pid = pids[0][1]
    page.evaluate(
        "() => { S = normalize(blankProject('')); S.id = 'p-empty'; CUR = 'p-empty'; }"
    )
    empty = export_of(page)
    valid("an empty project", empty)
    verified("an empty project: fingerprint recomputed", empty)

    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    item = page.evaluate(REFS)
    refs = export_of(page)
    listed = next(c for c in refs["checklist"] if c["id"] == item)["references"]
    check("evidence references are exported", len(listed) == 2, str(listed))
    sizes = [r["file"]["size"] for r in listed if r.get("file")] + [
        r["file"]["size"]
        for r in refs["_state"]["items"][item]["refs"].values()
        if r and r.get("file")
    ]
    check(
        "a file's size is exported as an integer, in the checklist and the record"
        " (X04)",
        sizes == [1048576, 1048576] and all(type(n) is int for n in sizes),
        repr(sizes),
    )
    valid("a project with a link and a file as evidence", refs)
    verified("references: fingerprint recomputed", refs)

    hostile_problems(page, pid, "published")

    # Not validated: CHAI's card has no field named "9", and the schema says so.
    page.evaluate(NUMERIC)
    numeric = export_of(page)
    verified("a record keyed by numbers: fingerprint recomputed (regression)", numeric)

    print("A new project's first history entry carries its fingerprint")
    new_id = page.evaluate(
        "async () => createProject(normalize(blankProject('Created here')),"
        " 'Project created')"
    )
    wait_until(page, f"PROJECTS.has({json.dumps(new_id)})")
    page.evaluate(f"openProject({json.dumps(new_id)}, 'setup')")
    wait_until(page, "LOG.length >= 1")
    settle(page)
    entry, shown = page.evaluate(
        "[LOG[LOG.length - 1].hash, contentHash(storedRecord(S))]"
    )
    check(
        "the 'Project created' entry's hash is the setup page's (regression)",
        entry == shown,
        f"{entry} != {shown}",
    )
    validator_fails(first_export)

    print("Every field the export always writes is required")
    with_flags = next(
        (e for e in on_exports if e["flags"] and e["metrics"]), on_exports[0]
    )
    check(
        "an export with flags and metrics to drop them from", bool(with_flags["flags"])
    )
    required_fields(with_flags, "published", chai=True)

    print("The record (_state) is described closed")
    rich = copy.deepcopy(with_flags)
    first = next(iter(rich["_state"]["items"]))
    rich["_state"]["items"][first]["refs"] = {
        "rlink0001": {
            "title": "t",
            "url": "https://example.org/",
            "date": "2026-03-04",
            "at": "2026-03-04T10:00:00Z",
        },
        "rfile0001": {
            "title": "",
            "url": "",
            "date": "",
            "at": "2026-03-05T10:00:00Z",
            "file": {"name": "a.pdf", "size": 1, "sha256": "ab" * 32},
        },
    }
    rich["_state"]["card"] = {"name": "A card field"}
    check(
        "the record it starts from is valid",
        not problems(rich) and bool(rich["_state"]["metrics"]),
        str(problems(rich)[:3]),
    )
    state_closed(rich, "published", STATE_BOGUS_CHAI, STATE_GOOD_CHAI)
    as_precise_as_before(rich)

    access_and_optica(page)
    older_record(page)
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    lone_surrogate(page)
    check("the published build raised no error", not errors, "; ".join(errors[:3]))
    page.close()
    return first_export


def example_build(browser) -> None:
    print("The example framework's build")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "example"
        code = build_app.main(["--config", str(EXAMPLE_CONFIG), "--out", str(out)])
        check("it builds", code == 0)
        if code:
            return
        page, errors = open_app(browser, out / "index.html")
        golden(page, "example build")
        page.evaluate("spine().samples.loadAll()")
        wait_until(page, "PROJECTS && PROJECTS.size === 2")
        settle(page)
        d = page.evaluate("FRAMEWORK_DEFS.example")
        statuses = {s["value"] for s in d["statuses"]} | {None}
        cats = {c["id"] for c in d["categories"]}
        sections = {s["n"] for s in d["sections"]}
        items = {i["id"] for s in d["sections"] for i in s["items"]}
        gates = {g["id"]: {o["value"] for o in g["options"]} for g in d["gates"]}
        phases = {p["label"] for p in d["phases"]} | {"Retired", "Stopped"}
        example_condition(page, d)
        exports = []
        locales = page.evaluate("[...LOCALE_CHOICES, Locale.PSEUDO]")
        for pid in page.evaluate("[...PROJECTS.keys()].sort()"):
            page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
            settle(page)
            exports.append(export_of(page))
            english = without_stamp(exports[-1])
            differ = []
            for loc in locales:
                page.evaluate(f"setLocale({json.dumps(loc)}); relocalize()")
                if without_stamp(export_of(page)) != english:
                    differ.append(loc)
            page.evaluate("setLocale('en'); relocalize()")
            check(
                f"{english['meta']['solution']}: the export is the English one in all"
                f" {len(locales)} languages",
                not differ,
                str(differ),
            )
        page.evaluate(
            "() => { S = normalize(blankProject(''));"
            " S.id = 'p-empty'; CUR = 'p-empty'; }"
        )
        exports.append(export_of(page))
        for e in exports:
            name = e["meta"]["solution"] or "an empty project"
            check(
                f"{name}: its export id is the definition's",
                e["schema"] == d["export"]["schemaId"],
            )
            valid(f"{name} validates", e)
            verified(f"{name}: load_export.py recomputes its fingerprint", e)
            rows = e["checklist"]
            check(
                f"{name}: its values are its definition's",
                {r["status"] for r in rows} <= statuses
                and {r["principle"] for r in rows} <= cats
                and {r["stage"] for r in rows} <= sections
                and {r["id"] for r in rows} == items
                and set(e["scores"]) == {"overall", *cats}
                and set(e.get("gates") or {}) <= set(gates)
                and all(
                    not g.get("decision") or g["decision"] in gates[k]
                    for k, g in (e.get("gates") or {}).items()
                )
                and e["phase"] in phases,
                json.dumps({k: e[k] for k in ("phase", "scores")}),
            )
        required_fields(exports[0], "example", chai=False)
        state_closed(exports[0], "example", STATE_BOGUS_GENERAL + STATE_BOGUS_EXAMPLE)
        unnamed_framework_reason(exports[0])
        with tempfile.TemporaryDirectory() as files:
            path = Path(files) / "example-review.json"
            path.write_text(json.dumps(exports[0]), encoding="utf-8")
            loaded = LOADER.load(path)
            summary = LOADER.summarize(loaded)
            check(
                "load_export.py reads it and says the fingerprint matches",
                "matches the record" in summary,
                summary,
            )

        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        hostile_problems(page, pid, "example")

        page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
        settle(page)
        page.evaluate(
            "() => { S.items = Object.assign("
            "{'9': {status: 'done'}, '10': {status: 'todo'}}, S.items);"
            # Written here, not saved: this copy is the record.
            " STORED.delete(S); }"
        )
        numeric = export_of(page)
        check(
            "the answers keyed by numbers are in the exported record",
            {"9", "10"} <= set(numeric["_state"]["items"]),
            str(sorted(numeric["_state"]["items"])[:6]),
        )
        canonical = page.evaluate("canonicalJSON(storedRecord(S))")
        check(
            "and in what the dashboard hashed, as strings sort: 10 before 9",
            canonical.find('"10":') != -1
            and canonical.find('"10":') < canonical.find('"9":'),
            canonical[:120],
        )
        verified(
            "answers keyed by numbers: fingerprint recomputed (regression)", numeric
        )
        check("the example build raised no error", not errors, "; ".join(errors[:3]))
        page.close()


def resolve(node: dict) -> dict:
    while isinstance(node, dict) and "$ref" in node:
        node = SCHEMA["$defs"][node["$ref"].rsplit("/", 1)[1]]
    return node


def schema_paths(node: dict, path: tuple = (), out: set | None = None) -> set:
    """Every place the schema describes: a named field, `*` for a map's values
    (additionalProperties), `[]` for a list's items."""
    out = set() if out is None else out
    node = resolve(node)
    for key, sub in node.get("properties", {}).items():
        out.add((*path, key))
        schema_paths(sub, (*path, key), out)
    for step, sub in (
        ("*", node.get("additionalProperties")),
        ("[]", node.get("items")),
    ):
        if isinstance(sub, dict):
            out.add((*path, step))
            schema_paths(sub, (*path, step), out)
    return out


def exercised(node: dict, value: object, path: tuple, out: set) -> None:
    """The schema paths a real export has a value at."""
    node = resolve(node)
    if isinstance(value, dict):
        props, extra = node.get("properties", {}), node.get("additionalProperties")
        for key, v in value.items():
            if key in props:
                step, sub = key, props[key]
            elif isinstance(extra, dict):
                step, sub = "*", extra
            else:
                continue
            out.add((*path, step))
            exercised(sub, v, (*path, step), out)
    elif isinstance(value, list) and isinstance(node.get("items"), dict):
        for v in value:
            out.add((*path, "[]"))
            exercised(node["items"], v, (*path, "[]"), out)


# Described by the schema and written by no export these tests make, each with why.
UNEXERCISED = {
    ("_state", "items", "*", "*"): "a primary framework's reason field: neither CHAI"
    " nor the example framework names one (OPTICA's, a supplement's, is exercised)",
}


def schema_covered() -> None:
    """Coverage: every path the schema describes has a value in some real export
    above, or is listed in UNEXERCISED with the reason. A described field no export
    writes is a field the tests above never validated a real value of."""
    print("Every path the schema describes is in some real export")
    described = schema_paths(SCHEMA)
    seen: set = set()
    for export in VALID_EXPORTS:
        exercised(SCHEMA, export, (), seen)
    missing = sorted(described - seen - set(UNEXERCISED))
    check(
        f"{len(VALID_EXPORTS)} valid exports reach {len(described & seen)} of the"
        f" {len(described)} paths the schema describes; the rest are listed with why",
        not missing and len(VALID_EXPORTS) > 20,
        "never exported: " + ", ".join("/".join(p) for p in missing),
    )
    surprise = copy.deepcopy(SCHEMA)
    surprise["properties"]["surprise"] = {"type": "string"}
    check(
        "a field the schema describes and no export writes is caught (mutation)",
        ("surprise",) in schema_paths(surprise) - seen,
    )
    stale = sorted(p for p in UNEXERCISED if p in seen or p not in described)
    check(
        "nothing listed as unexercised is exercised, or no longer described",
        not stale,
        str(stale),
    )


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        published(browser)
        example_build(browser)
        browser.close()
    schema_covered()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("export schema checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
