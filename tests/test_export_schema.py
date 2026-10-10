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
  * the example framework's build (app/frameworks/example/): its samples, an empty
    project and a hostile one, and its definition's values (statuses, categories,
    sections, checkpoints, phases) are the ones its export uses.

Where the schema fixes the published framework's values (the `chai-review/2`
condition), each list is checked against CHAI's definition, so the two cannot
drift either.

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

Every sample exports the same file in every language, a dated flag included (its
date was in the reader's language). An older record, missing fields the
dashboard fills in, is hashed and exported as stored, as the server hashes it.
A lone surrogate survives the trip from the downloaded file to load_export.py.

The validator is shown failing: a missing field, a foreign export id, a value
outside the published framework's lists, an undescribed field (closed only), a
bad date.

    pixi run test-export-schema
"""

from __future__ import annotations

import copy
import datetime as dt
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


def closed(schema: object, path: tuple[str, ...] = ()) -> object:
    """The schema with every object it describes closed to other fields.

    The published framework's conditional lists (`$defs/chai`) only narrow
    values the open part already describes, so they are left as they are."""
    if isinstance(schema, dict):
        if path[-2:] == ("$defs", "chai"):
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


def valid(name: str, export: dict) -> None:
    found = problems(export)
    check(name, not found, "; ".join(sorted(set(found))[:6]))


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
    e["schema"] = "example-review/1"
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
    e["schema"] = "example-review/1"
    check(
        "the one intended difference: another framework's export id",
        bool(list(OLD.iter_errors(e))) and not refused(e),
    )


def older_record(page) -> None:
    """A record an older dashboard wrote lacks fields normalize() now fills. The
    dashboard hashed its filled-in copy and the server the stored record, so the
    same record had two fingerprints (#177). It is the stored record's, everywhere
    the dashboard shows or writes one, and the export's record is the stored one, so
    a reader recomputes the same digest."""
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
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    want = LOADER.fingerprint({"_state": stored, "project_id": pid})
    filled = page.evaluate("S.meta.chaiUseCase")
    check("the dashboard fills it in to show it", filled == "", repr(filled))
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
    shown = page.evaluate("changelogHTML()")
    check(
        "the history view shows the stored record's fingerprint",
        want["md5"] in shown,
        "not in the view",
    )
    n = page.evaluate("LOG.length")
    page.evaluate("edit('meta.org', 'Later')")
    wait_until(page, f"LOG.length > {n}")
    # Saved: the save waits for typing to pause, so nothing pending is not soon.
    wait_until(
        page, "!Object.keys(pending).length && !Object.values(flushing).some(Boolean)"
    )
    after = json.loads(
        page.evaluate(f"JSON.stringify(STORE.d.projects[{json.dumps(pid)}])")
    )
    want_after = LOADER.fingerprint({"_state": after, "project_id": pid})["md5"]
    entry = page.evaluate("LOG[0].hash")
    check(
        "an edit's history entry carries the fingerprint of what was stored",
        entry == want_after,
        f"{entry} != {want_after}",
    )
    check(
        "what was stored is the older record and the edit, nothing filled in",
        "chaiUseCase" not in after["meta"] and "card" not in after,
        str(sorted(after)),
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
        exports = []
        for pid in page.evaluate("[...PROJECTS.keys()].sort()"):
            page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
            settle(page)
            exports.append(export_of(page))
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
        state_closed(exports[0], "example", STATE_BOGUS_GENERAL)
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
            "{'9': {status: 'done'}, '10': {status: 'todo'}}, S.items); }"
        )
        numeric = export_of(page)
        verified(
            "answers keyed by numbers: fingerprint recomputed (regression)", numeric
        )
        check("the example build raised no error", not errors, "; ".join(errors[:3]))
        page.close()


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        published(browser)
        example_build(browser)
        browser.close()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("export schema checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
