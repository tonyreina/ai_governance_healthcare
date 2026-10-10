#!/usr/bin/env python3
"""The published checklist pages are the framework definitions, and nothing else.

scripts/gen_framework_docs.py writes docs/frameworks/<id>-checklist.md from each
app/frameworks/<id>/framework.json (#168, D-75). This suite asserts:

* a fresh run, into a temporary directory, writes exactly the committed pages,
  byte for byte, and there is a committed page for every definition and a
  definition for every page;
* the comparison notices a changed definition (mutation: one item's text edited
  in a temporary copy), so the equality above is shown able to fail;
* a misspelled key in a docs.toml is an error, not a silently ignored setting;
* a definition with no docs.toml still gets a page, in neutral words;
* until the engine reads the definitions (#168 step 2), the app still carries its
  own copy of CHAI's criteria and OPTICA's items. The built dashboard must agree
  with the definitions, or the page's "cannot drift from the checklist the tool
  actually enforces" would be false. Shown failing on an edited copy;
* the pre-commit hook that regenerates the pages runs when a definition, its
  docs.toml or the generator changes, and not only on the retired data file.

No browser, database or Docker: nothing here can skip.

    pixi run test-framework-docs
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FRAMEWORKS = ROOT / "app" / "frameworks"
PAGES = ROOT / "docs" / "frameworks"
APP_HTML = ROOT / "docs" / "app" / "index.html"
PRECOMMIT = ROOT / ".pre-commit-config.yaml"
HOOK_ID = "gen-checklists"

spec = importlib.util.spec_from_file_location(
    "gen_framework_docs", ROOT / "scripts" / "gen_framework_docs.py"
)
gen = importlib.util.module_from_spec(spec)
sys.modules["gen_framework_docs"] = gen
spec.loader.exec_module(gen)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# --- the comparison ---------------------------------------------------------


def page_differences(frameworks: Path, committed: Path, scratch: Path) -> list[str]:
    """Regenerate from `frameworks` into `scratch`; name every page that differs."""
    out = scratch / "out"
    if out.exists():
        shutil.rmtree(out)
    gen.generate(frameworks, out)
    fresh = {p.name: p.read_bytes() for p in out.glob("*-checklist.md")}
    ids = {p.parent.name for p in frameworks.glob(f"*/{gen.DEFINITION}")}
    have = {
        p.name: p.read_bytes()
        for p in committed.glob("*-checklist.md")
        if p.name.removesuffix("-checklist.md") in ids
    }
    # A committed page whose definition is gone is stale too.
    orphans = {
        p.name
        for p in committed.glob("*-checklist.md")
        if p.name.removesuffix("-checklist.md") not in ids
    }
    problems = [f"{name}: no definition" for name in sorted(orphans)]
    for name in sorted(set(fresh) | set(have)):
        if name not in have:
            problems.append(f"{name}: not committed")
        elif name not in fresh:
            problems.append(f"{name}: not generated")
        elif fresh[name] != have[name]:
            problems.append(f"{name}: differs from a fresh run")
    return problems


def copy_frameworks(scratch: Path) -> Path:
    target = scratch / "frameworks"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(FRAMEWORKS, target)
    return target


def edit_definition(frameworks: Path, fid: str, mutate) -> None:
    path = frameworks / fid / gen.DEFINITION
    defn = json.loads(path.read_text(encoding="utf-8"))
    mutate(defn)
    path.write_text(json.dumps(defn, ensure_ascii=False, indent=2), encoding="utf-8")


def first_item(defn: dict) -> dict:
    return defn["sections"][0]["items"][0]


# --- the built app's copy --------------------------------------------------

DEFS_RE = re.compile(r"const FRAMEWORK_DEFS = Object\.freeze\((\{.*?\})\);\n", re.S)


def app_definitions(html: str) -> dict:
    """The definitions the built dashboard embeds and runs (FRAMEWORK_DEFS, #168)."""
    match = DEFS_RE.search(html)
    return json.loads(match.group(1)) if match else {}


def app_drift(html: str, definitions: dict[str, dict]) -> list[str]:
    embedded = app_definitions(html)
    return [
        f"{fid}: the built app runs a different definition"
        for fid in sorted(definitions)
        if embedded.get(fid) != definitions[fid]
    ]


# --- the suite ---------------------------------------------------------------


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)

        print("The committed pages are a fresh run, byte for byte")
        problems = page_differences(FRAMEWORKS, PAGES, scratch)
        check("every page matches its definition", not problems, "; ".join(problems))
        ids = sorted(p.parent.name for p in FRAMEWORKS.glob(f"*/{gen.DEFINITION}"))
        check(
            "the default build's frameworks both have a definition",
            {"chai", "optica"} <= set(ids),
            str(ids),
        )
        chai_page = (PAGES / "chai-checklist.md").read_text(encoding="utf-8")
        check(
            "the CHAI page names its real source, not the built dashboard",
            "Edit the criteria in\n    `app/frameworks/chai/framework.json`"
            in chai_page
            and "docs/app/index.html" not in chai_page,
        )

        print("The comparison notices a changed definition (mutation)")
        for fid in ("chai", "optica"):
            frameworks = copy_frameworks(scratch)
            edit_definition(
                frameworks,
                fid,
                lambda d: first_item(d).update(
                    text=first_item(d)["text"] + " (edited)"
                ),
            )
            found = page_differences(frameworks, PAGES, scratch)
            check(
                f"one {fid} item's text edited",
                found == [f"{fid}-checklist.md: differs from a fresh run"],
                str(found),
            )

        frameworks = copy_frameworks(scratch)
        shutil.copytree(frameworks / "chai", frameworks / "extra")
        edit_definition(frameworks, "extra", lambda d: d.update(id="extra"))
        found = page_differences(frameworks, PAGES, scratch)
        check(
            "a definition with no committed page",
            found == ["extra-checklist.md: not committed"],
            str(found),
        )

        frameworks = copy_frameworks(scratch)
        shutil.rmtree(frameworks / "optica")
        # OPTICA's page cross-references CHAI by name; without it, CHAI is alone.
        found = page_differences(frameworks, PAGES, scratch)
        check(
            "a committed page with no definition",
            found == ["optica-checklist.md: no definition"],
            str(found),
        )

        frameworks = copy_frameworks(scratch)
        docs = frameworks / "optica" / gen.DOCS_CONFIG
        docs.write_text(
            docs.read_text(encoding="utf-8").replace("bold_numbers", "bold_number"),
            encoding="utf-8",
        )
        try:
            gen.generate(frameworks, scratch / "typo")
            raised = ""
        except gen.DefinitionError as exc:
            raised = str(exc)
        check("a misspelled docs.toml key is an error", "bold_number" in raised, raised)

        frameworks = copy_frameworks(scratch)
        edit_definition(frameworks, "optica", lambda d: d.update(id="other"))
        try:
            gen.generate(frameworks, scratch / "mismatch")
            raised = ""
        except gen.DefinitionError as exc:
            raised = str(exc)
        check("an id that is not its directory is an error", "other" in raised, raised)

        print("A definition with no docs.toml gets a page in neutral words")
        stand_in = scratch / "standin"
        (stand_in / "acme").mkdir(parents=True)
        (stand_in / "acme" / gen.DEFINITION).write_text(
            json.dumps(
                {
                    "id": "acme",
                    "name": "Acme",
                    "keys": {"section": "phase", "category": "theme"},
                    "categories": [{"id": "Q", "name": "Quality"}],
                    "sections": [
                        {
                            "id": "p1",
                            "n": 1,
                            "title": "Plan | scope",
                            "items": [
                                {"id": "a", "category": "Q", "text": "A | B"},
                                {"id": "b", "category": "Q", "text": "Second"},
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        gen.generate(stand_in, scratch / "standin-out")
        page = (scratch / "standin-out" / "acme-checklist.md").read_text("utf-8")
        check(
            "titled from the definition's name", page.startswith("# Acme checklist\n")
        )
        check(
            "counts its items", "The 2 items of Acme" in page and "*2 items.*" in page
        )
        check(
            "names its source definition",
            "`app/frameworks/acme/framework.json`" in page,
        )
        check("headings use the definition's own nouns", "## Phase 1: Plan" in page)
        check("a category table leads", "## Themes\n\n| Tag | Theme |" in page)
        check(
            "a pipe in item text cannot break the table",
            "| 1.1 | A \\| B | **Q** |" in page,
            page,
        )
        check(
            "no CHAI or OPTICA words leak in",
            "CHAI" not in page and "OPTICA" not in page,
        )

        print("The built dashboard runs exactly these definitions")
        html = APP_HTML.read_text(encoding="utf-8")
        # The published build's frameworks: a definition outside it (the example)
        # is built only by --config, never into this page.
        published = json.loads((ROOT / "app" / "frameworks.json").read_text("utf-8"))
        definitions = {
            fid: d
            for fid, d in gen.load_definitions(FRAMEWORKS).items()
            if fid in published["frameworks"]
        }
        check(
            "the dashboard embeds CHAI's and OPTICA's definitions",
            {"chai", "optica"} <= set(app_definitions(html)),
        )
        drift = app_drift(html, definitions)
        check("the app and the definitions agree", not drift, "; ".join(drift))
        for fid in ("chai", "optica"):
            edited = copy.deepcopy(definitions)
            first_item(edited[fid])["text"] += " (edited)"
            found = app_drift(html, edited)
            check(
                f"an edited {fid} definition is drift (mutation)",
                len(found) == 1,
                str(found),
            )

        print("The pre-commit hook regenerates the pages when a definition changes")
        hooks = [
            h
            for repo in yaml.safe_load(PRECOMMIT.read_text(encoding="utf-8"))["repos"]
            for h in repo.get("hooks", [])
            if h.get("id") == HOOK_ID
        ]
        check(f"the {HOOK_ID} hook exists", len(hooks) == 1)
        hook = hooks[0] if hooks else {}
        pattern = re.compile(hook.get("files", "(?!)"))
        for path in (
            "app/frameworks/chai/framework.json",
            "app/frameworks/optica/docs.toml",
            "scripts/gen_framework_docs.py",
        ):
            check(f"runs on {path}", bool(pattern.search(path)))
        check("does not run on an unrelated file", not pattern.search("README.md"))
        check("runs the generator", hook.get("entry") == "pixi run gen-docs")

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
