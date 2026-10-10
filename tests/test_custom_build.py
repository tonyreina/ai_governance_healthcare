#!/usr/bin/env python3
"""A build of other frameworks works, with nothing of CHAI or OPTICA in it (#168).

Builds app/frameworks/example/ (a made-up framework, not in the published build)
with `build_app.py --config app/frameworks/example/build.json --out DIR`, then
drives it in a real browser:

  - it boots under its own Content-Security-Policy with no error, and asks for
    nothing from another origin;
  - the samples written as data in the definition load, and every screen, the
    report and every export (Markdown, HTML, JSON, CSV) render with no word of
    CHAI's or OPTICA's (their names, "criterion", "checkpoint", "stage",
    "principle", their file suffixes);
  - every record it makes is stamped with its primary, and its browser storage
    keys carry the primary's id, so its work never mixes with the published
    build's on one origin;
  - a record of another framework (an unstamped one is the published build's) is
    left off the portfolio with a note saying how many, refused when opened, and
    refused when imported; its own export imports back;
  - Spanish, which the example supplies, shows the Spanish text with no note;
    German, which it does not, shows the English with the "not translated" note;
  - definition text is text: a definition whose words are markup builds a page
    that shows the markup and runs none of it.

    pixi run test-custom-build
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402

EXAMPLE = ROOT / "app" / "frameworks" / "example"
CONFIG = EXAMPLE / "build.json"

# What the published build's frameworks would leave behind in another's screens.
# Whole words, any case. JSON keys are a stable wire format (D-78), so the export
# sweep reads only values.
FOREIGN = re.compile(
    r"\b(chai|optica|criterion|criteria|checkpoints?|stages?|principles?"
    r"|model card|chai-review|optica-review)\b",
    re.I,
)
PAYLOAD = '<img src=x onerror="window.__pwned=1">'

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def build(out: Path, frameworks: Path | None = None) -> Path:
    code = build_app.main(
        ["--config", str(CONFIG), "--out", str(out)], frameworks=frameworks
    )
    if code != 0:
        raise SystemExit(f"build_app exited {code}")
    return out / "index.html"


def strings(value: object) -> list[str]:
    """Every string value in a JSON document, not its keys."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return [value] if isinstance(value, str) else []


def foreign_words(text: str) -> list[str]:
    return sorted({m.group(0) for m in FOREIGN.finditer(text)})


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


def visible_text(page, selector: str = "body") -> str:
    """What a reader sees, plus the words a screen reader is given."""
    return page.evaluate(
        """sel => {
          const el = document.querySelector(sel);
          const attrs = [...el.querySelectorAll('[title],[aria-label],[placeholder]')]
            .filter(e => !e.closest('[hidden]'))
            .map(e => [e.title, e.getAttribute('aria-label'), e.placeholder].join(' '));
          return el.innerText + '\\n' + attrs.join('\\n') + '\\n' + document.title;
        }""",
        selector,
    )


def open_page(browser, index: Path, init: str = ""):
    page = browser.new_page(viewport={"width": 1400, "height": 1000})
    errors: list[str] = []
    foreign_requests: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on(
        "console",
        lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None,
    )
    page.on(
        "request",
        lambda r: (
            None
            if r.url.startswith(("file:", "data:", "blob:", "about:"))
            else foreign_requests.append(r.url)
        ),
    )
    if init:
        page.add_init_script(init)
    page.goto(index.as_uri())
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    return page, errors, foreign_requests


def sweep_app(browser, index: Path) -> None:
    print("The example build, driven")
    page, errors, requests = open_page(browser, index)
    check(
        "it is the example's build",
        page.evaluate("BUILD.primary === 'example' && !BUILD.published"),
    )
    check(
        "only the example's definition is embedded",
        page.evaluate("Object.keys(FRAMEWORK_DEFS)") == ["example"],
        str(page.evaluate("Object.keys(FRAMEWORK_DEFS)")),
    )
    words = foreign_words(visible_text(page))
    check("the empty portfolio names no other framework", not words, str(words))

    page.evaluate("spine().samples.loadAll()")
    page.wait_for_function("PROJECTS && PROJECTS.size === 2", timeout=15000)
    settle(page)
    names = sorted(page.evaluate("[...PROJECTS.values()].map(p => p.meta.solution)"))
    check(
        "the definition's two samples load",
        names == ["Sample: fall-risk score", "Sample: note summarizer"],
        str(names),
    )
    stamps = page.evaluate("[...PROJECTS.values()].map(p => p.meta.framework)")
    check(
        "every record it makes is stamped with its primary",
        stamps == [{"id": "example"}] * 2,
        str(stamps),
    )
    keys = page.evaluate("Object.keys(localStorage)")
    check(
        "its records are stored under the example's key, not the published build's",
        "chai-portfolio-local-v1@example" in keys
        and "chai-portfolio-local-v1" not in keys,
        str(keys),
    )
    words = foreign_words(visible_text(page))
    check("the portfolio names no other framework", not words, str(words))

    pid = page.evaluate(
        "[...PROJECTS.values()].find(p => p.meta.solution.includes('fall')).id"
    )
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    views = page.evaluate("activeViews().map(v => v.id)")
    want = {"example-plan", "example-test", "example-run", "ggo", "gyearly", "report"}
    check(
        "the rail has the example's steps, its two checkpoints and the report",
        want <= set(views),
        str(views),
    )
    seen: dict[str, list[str]] = {}
    for vid in views:
        page.evaluate(f"go({json.dumps(vid)})")
        page.wait_for_timeout(30)
        hit = foreign_words(visible_text(page))
        if hit:
            seen[vid] = hit
    check("no screen names another framework", not seen, str(seen))
    check(
        "the go-live decision shows on its gate",
        "Approve with conditions" in page.evaluate("JSON.stringify(S.gates)"),
    )
    status = page.evaluate("spine().status(S).label")
    check("the project has a status from the example's rules", bool(status), status)

    md = page.evaluate("exportMD()")
    html = page.evaluate("exportHTML()")
    data = page.evaluate("projectJSON(S)")
    csv = page.evaluate("exportCSV()")
    for name, text in (
        ("Markdown", md),
        ("HTML", html),
        ("JSON", "\n".join(strings({k: v for k, v in data.items() if k != "meta"}))),
        ("CSV", csv),
    ):
        words = foreign_words(text)
        check(f"the {name} export names no other framework", not words, str(words))
    check("the JSON export is the example's", data["schema"] == "example-review/1")
    check(
        "the export file name is the example's",
        page.evaluate("spine().fileSuffix") == "example-review",
    )
    check(
        "an export carries the stamp, so it imports back",
        data["_state"]["meta"]["framework"] == {"id": "example"},
    )
    check(
        "the report and the Markdown give the example's own item text",
        "Results are compared across patient groups" in md
        and "Results are compared across patient groups" in html,
    )

    print("Its own export imports back")
    page.evaluate("goHome()")
    path = Path(tempfile.mkdtemp()) / "own.json"
    own = copy.deepcopy(data)
    own["_state"]["meta"]["solution"] = "Reimported"
    path.write_text(json.dumps(own), encoding="utf-8")
    page.set_input_files("#importFile", str(path))
    page.wait_for_function("PROJECTS.size === 3", timeout=10000)
    check("the example's own export is accepted", True)

    print("Records of another framework")
    for name, meta in (
        ("unstamped (the published build's)", {"solution": "Old CHAI review"}),
        (
            "stamped with another primary",
            {"solution": "Other", "framework": {"id": "other"}},
        ),
    ):
        path.write_text(
            json.dumps({"_state": {"meta": meta, "items": {}, "gates": {}}}),
            encoding="utf-8",
        )
        page.set_input_files("#importFile", str(path))
        page.wait_for_timeout(400)
        check(
            f"an import of a record {name} is refused",
            page.evaluate("PROJECTS.size") == 3,
            str(page.evaluate("PROJECTS.size")),
        )
        toast = page.inner_text("#toast")
        check(
            f"... and the refusal says why ({name})",
            "does not open" in toast,
            toast,
        )
    shutil.rmtree(path.parent)
    check("no page errors", not errors, str(errors[:3]))
    check("no request leaves the page", not requests, str(requests[:3]))
    page.close()


# Two records another build left in this build's store: one unstamped, one stamped
# with a different primary.
FOREIGN_SEED = """
(() => {
  if (localStorage.getItem('seeded')) return;
  const rec = (name, extra) => ({meta: {solution: name, ...extra}, items: {}, gates: {},
    updatedAt: '2026-01-01T00:00:00Z', createdAt: '2026-01-01T00:00:00Z'});
  localStorage.setItem('chai-portfolio-local-v1@example', JSON.stringify({
    projects: {
      a: rec('Theirs, unstamped', {}),
      b: rec('Theirs, other', {framework: {id: 'other'}}),
      c: rec('Ours', {framework: {id: 'example'}}),
    }, logs: {}}));
  localStorage.setItem('seeded', '1');
})()
"""


def foreign_records(browser, index: Path) -> None:
    print("Records of another framework in the store")
    page, errors, _ = open_page(browser, index, FOREIGN_SEED)
    page.wait_for_function("PROJECTS.size === 3", timeout=10000)
    page.wait_for_timeout(200)
    rows = page.evaluate("dashData().map(r => r.p.meta.solution)")
    check("the portfolio lists only the example's record", rows == ["Ours"], str(rows))
    note = (
        page.inner_text("#foreignNote") if page.query_selector("#foreignNote") else ""
    )
    check(
        "a note says two records of another framework are not shown",
        "2" in note and "another framework" in note,
        note,
    )
    page.evaluate("openProject('a', 'setup')")
    page.wait_for_timeout(200)
    check("opening an unstamped record is refused", page.evaluate("!S"))
    check(
        "... with a note naming its framework",
        "chai" in page.inner_text("#toast"),
        page.inner_text("#toast"),
    )
    page.evaluate("openProject('b', 'setup')")
    page.wait_for_timeout(200)
    check("opening another primary's record is refused", page.evaluate("!S"))
    page.evaluate("openProject('c', 'setup')")
    page.wait_for_timeout(200)
    check("its own record opens", page.evaluate("!!S && S.meta.solution === 'Ours'"))
    check("no page errors", not errors, str(errors[:3]))
    page.close()


def languages(browser, index: Path) -> None:
    print("Languages: supplied, and not")
    for loc, shown, note in (
        ("es", "Los resultados se comparan entre grupos de pacientes", False),
        ("de", "Results are compared across patient groups", True),
    ):
        page, errors, _ = open_page(
            browser, index, f"localStorage.setItem('chai-locale', '{loc}')"
        )
        if page.evaluate("LOCALE") != loc:
            key = page.evaluate("LOCALE_KEY")
            page.evaluate(f"localStorage.setItem({json.dumps(key)}, '{loc}')")
            page.reload()
            page.wait_for_function("typeof LOADED !== 'undefined' && LOADED")
        check(f"the page is in {loc}", page.evaluate("LOCALE") == loc)
        page.evaluate("spine().samples.loadAll()")
        page.wait_for_function("PROJECTS.size === 2", timeout=15000)
        settle(page)
        pid = page.evaluate("[...PROJECTS.keys()][0]")
        page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
        settle(page)
        page.evaluate("go('example-test')")
        page.wait_for_timeout(100)
        text = page.inner_text("#main")
        check(
            f"{loc}: the item text is {'English' if note else 'Spanish'}", shown in text
        )
        untranslated = page.evaluate("t('engine.fw.untranslated', {name: 'Example'})")
        has_note = untranslated.split("{")[0][:20] in text
        check(
            f"{loc}: the 'not translated' note is {'shown' if note else 'absent'}",
            has_note is note,
            untranslated,
        )
        check(f"{loc}: no page errors", not errors, str(errors[:3]))
        page.close()


def poisoned(browser, work: Path) -> None:
    print("Definition text is text")
    frameworks = work / "frameworks"
    shutil.copytree(EXAMPLE, frameworks / "example")
    shutil.rmtree(frameworks / "example" / "i18n")
    path = frameworks / "example" / "framework.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["name"] = PAYLOAD
    doc["title"] = PAYLOAD
    doc["notice"] = PAYLOAD
    doc["sections"][0]["title"] = PAYLOAD
    doc["sections"][0]["summary"] = PAYLOAD
    doc["sections"][0]["items"][0]["text"] = PAYLOAD
    doc["categories"][0]["name"] = PAYLOAD
    doc["statuses"][0]["label"] = PAYLOAD
    doc["gates"][0]["title"] = PAYLOAD
    doc["gates"][0]["question"] = PAYLOAD
    doc["gates"][0]["options"][1]["short"] = PAYLOAD
    doc["phases"][0]["label"] = PAYLOAD
    doc["samples"][0]["name"] = PAYLOAD
    path.write_text(json.dumps(doc), encoding="utf-8")
    index = build(work / "poisoned", frameworks=frameworks)

    page, errors, _ = open_page(browser, index)
    page.evaluate("spine().samples.loadAll()")
    page.wait_for_function("PROJECTS.size === 2", timeout=15000)
    settle(page)
    shown = PAYLOAD in visible_text(page)
    find = f"p => p.meta.solution === {json.dumps(PAYLOAD)}"
    pid = page.evaluate(f"[...PROJECTS.values()].find({find}).id")
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    for vid in page.evaluate("activeViews().map(v => v.id)"):
        page.evaluate(f"go({json.dumps(vid)})")
        page.wait_for_timeout(30)
        shown = shown or PAYLOAD in visible_text(page)
    md = page.evaluate("exportMD()")
    html = page.evaluate("exportHTML()")
    page.evaluate("exportCSV(); projectJSON(S)")
    page.wait_for_timeout(300)
    check("the HTML export holds no tag from it", "<img" not in html)
    # Markdown escapes a character with a backslash: an unescaped < is a tag.
    tags = re.finditer(r"(?<!\\)<img", md)
    raw = [md[max(0, m.start() - 40) : m.end()] for m in tags]
    check("the Markdown export holds no tag from it", not raw, str(raw[:3]))
    check("the markup shows as text", shown)
    check("none of it runs", page.evaluate("window.__pwned === undefined"))
    check(
        "no element it names is made",
        page.evaluate("!document.querySelector('img[src=\"x\"]')"),
    )
    check("no page errors", not errors, str(errors[:3]))
    page.close()


def control(browser) -> None:
    """The sweep is not vacuous: on the published build it finds CHAI's words, in
    the screens and in every export."""
    print("Control: the sweep, on the published build")
    page, _, _ = open_page(browser, ROOT / "docs" / "app" / "index.html")
    page.evaluate("spine().samples.loadAll()")
    page.wait_for_function("PROJECTS.size > 0", timeout=15000)
    settle(page)
    pid = page.evaluate("[...PROJECTS.keys()][0]")
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    page.evaluate("go(spine().reportViewId)")
    page.wait_for_timeout(100)
    check("it finds them on a screen", bool(foreign_words(visible_text(page))))
    for name, js in (
        ("Markdown", "exportMD()"),
        ("HTML", "exportHTML()"),
        ("CSV", "exportCSV()"),
    ):
        check(
            f"it finds them in the {name} export",
            bool(foreign_words(page.evaluate(js))),
        )
    data = page.evaluate("projectJSON(S)")
    check(
        "it finds them in the JSON export's values",
        bool(foreign_words("\n".join(strings(data)))),
    )
    page.close()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="custom-build-"))
    try:
        index = build(work / "example")
        policy = (work / "example" / "csp.caddy").read_text(encoding="utf-8")
        check(
            "the build writes its own proxy policy beside the page", "sha256-" in policy
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            control(browser)
            sweep_app(browser, index)
            foreign_records(browser, index)
            languages(browser, index)
            poisoned(browser, work)
            browser.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if failures:
        print(f"\n{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("\nAll passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
