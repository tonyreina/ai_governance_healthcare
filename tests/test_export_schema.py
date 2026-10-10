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
  return it;
}"""

# A record keyed by numbers, which a JavaScript object lists in numeric order
# whatever order its keys were added in.
NUMERIC = """() => {
  S.card = Object.assign(S.card || {}, {"9": "nine", "10": "ten", "1": "one"});
  S.meta.solution = "Keyed by numbers \\uffff \\u{1F600}";
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
    fw_pattern = json.loads(FRAMEWORK_SCHEMA.read_text(encoding="utf-8"))
    sid = fw_pattern["properties"]["export"]["properties"]["schemaId"]["pattern"]
    check(
        "the export id pattern is the one a definition's schemaId must match",
        SCHEMA["properties"]["schema"]["pattern"] == sid,
        f"{SCHEMA['properties']['schema']['pattern']} != {sid}",
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
            " a[ids[1]] = {status: 'declined', declineReason: 'r'}; }"
        )
        on = export_of(page)
        check(
            f"{name}, OPTICA on: its record is in the export", "optica" in on["_state"]
        )
        valid(f"{name}, OPTICA on", on)
        verified(f"{name}, OPTICA on: fingerprint recomputed", on)
        n = page.evaluate("LOG.length")
        page.evaluate("setFrameworkEnabled('optica', false)")
        wait_until(page, f"LOG.length > {n}")
        settle(page)

    print("Every language exports the same file")
    pid = pids[0][1]
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    english = without_stamp(export_of(page))
    for loc in page.evaluate("[...LOCALE_CHOICES, Locale.PSEUDO]"):
        page.evaluate(f"setLocale({json.dumps(loc)}); relocalize()")
        other = without_stamp(export_of(page))
        check(f"{loc}: the export is the English one", other == english)
    page.evaluate("setLocale('en'); relocalize()")

    print("An empty project, references, a hostile one, one keyed by numbers")
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

    page.evaluate(NUMERIC)
    numeric = export_of(page)
    valid("a record keyed by numbers", numeric)
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
    entry, shown = page.evaluate("[LOG[LOG.length - 1].hash, contentHash(S)]")
    check(
        "the 'Project created' entry's hash is the setup page's (regression)",
        entry == shown,
        f"{entry} != {shown}",
    )
    validator_fails(first_export)
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
