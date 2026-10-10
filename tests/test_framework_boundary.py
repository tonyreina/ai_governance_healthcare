#!/usr/bin/env python3
"""The shell never names a framework (#168).

The portfolio, the exports, the change history and the events ask the primary
framework through the registry's spine (app/js/10-frameworks/00-registry.js),
so a build with another framework needs no change outside that framework's own
directory. This reads the shell's source (app/js/00-core and app/js/20-app,
comments aside) and fails on any identifier that belongs to CHAI or OPTICA.

A static check, so the mutation at the end shows it notices a use slipped back
in; that each framework still behaves the same is the rest of the suite's job.

    pixi run test-framework-boundary
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
FW_JS = ROOT / "app" / "js" / "10-frameworks"
# Code that must name no framework: the shell, the engine, the project's setup
# screen, the registry and the registration of every definition.
SHELL = [
    ROOT / "app" / "js" / "00-core",
    ROOT / "app" / "js" / "20-app",
    FW_JS / "01-engine",
    FW_JS / "05-project",
]
SHELL_FILES = [FW_JS / "00-registry.js", FW_JS / "90-register.js"]
GENERIC = {"01-engine", "05-project"}

# Every top-level name a framework's own code defines (today only CHAI's plug-ins:
# OPTICA is pure data), read from the directories, so a new one is covered
# without editing this list.
FRAMEWORK_DIRS = sorted(
    d for d in FW_JS.iterdir() if d.is_dir() and d.name not in GENERIC
)

# String literals the shell may keep although they say "chai": the browser storage
# keys people's saved work and settings live under. Renaming one loses that state.
ALLOWED_LITERALS = frozenset(
    {
        "chai-locale",
        "chai-ui-v2",
        "chai-portfolio-local-v1",
        "chai-api-origin-seen",
        "chai-review-v1",
        "chai-legacy-imported",
    }
)
FRAMEWORK_WORD = re.compile(r"\b(chai|optica)\b", re.I)
# The two alternatives never match the same character (a backslash only starts an
# escape), so a run of backslashes cannot make this backtrack (CodeQL).
STRING = re.compile(r"""(["'`])((?:\\.|(?!\1)[^\\])*)\1""")
# Names the engine replaced: defined nowhere now (#168 PR B1).
RETIRED = (
    "STAGES",
    "GATES",
    "PRINCIPLES",
    "OPTICA",
    "OPTICA_ITEMS",
    "allItems",
    "opticaScore",
    "opticaAnswer",
    "setOpticaEnabled",
    "CHAI_SPINE",
    "scoreOf",
)
DEFINITION = re.compile(
    r"^(?:const|let|function|async function)\s+([A-Za-z_$][\w$]*)", re.M
)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def code_only(source: str) -> str:
    source = re.sub(
        r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.S
    )
    return "\n".join(re.sub(r"(^|\s)//.*$", r"\1", line) for line in source.split("\n"))


def strip_strings(code: str) -> str:
    """Blank out string contents, keeping the code inside a template's `${...}`,
    so the word "flags" in a class name or a CSV header is not a use. Line breaks
    are kept so line numbers still match."""
    out: list[str] = []
    i, n = 0, len(code)

    def skip_quoted(j: int, q: str) -> int:
        j += 1
        while j < n and code[j] != q:
            if code[j] == "\\":
                j += 1
            elif code[j] == "\n":
                out.append("\n")
            j += 1
        return j + 1

    def regex_here(j: int) -> bool:
        """A `/` starts a regex literal where an operand is expected."""
        k = len(out) - 1
        while k >= 0 and out[k] in " \t\n":
            k -= 1
        return (
            k < 0
            or out[k] in "(,=:[!&|?{};+-*%<>~^"
            or "".join(out[max(0, k - 5) : k + 1]).endswith("return")
        )

    def skip_regex(j: int) -> int:
        j += 1
        in_class = False
        while j < n and code[j] != "\n":
            c = code[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                j += 1
                while j < n and code[j].isalpha():
                    j += 1
                return j
            j += 1
        return j

    def template(j: int) -> int:
        j += 1
        while j < n and code[j] != "`":
            if code[j] == "\\":
                j += 2
                continue
            if code.startswith("${", j):
                out.append(" ")
                j = expression(j + 2)
                continue
            if code[j] == "\n":
                out.append("\n")
            j += 1
        return j + 1

    def expression(j: int) -> int:
        level = 0
        while j < n:
            c = code[j]
            if c in "'\"":
                j = skip_quoted(j, c)
                out.append('""')
                continue
            if c == "`":
                j = template(j)
                out.append('""')
                continue
            if c == "/" and regex_here(j):
                j = skip_regex(j)
                out.append("/r/")
                continue
            if c == "{":
                level += 1
            elif c == "}":
                if level == 0:
                    out.append(" ")
                    return j + 1
                level -= 1
            out.append(c)
            j += 1
        return j

    while i < n:
        c = code[i]
        if c in "'\"":
            i = skip_quoted(i, c)
            out.append('""')
        elif c == "`":
            i = template(i)
            out.append('""')
        elif c == "/" and regex_here(i):
            i = skip_regex(i)
            out.append("/r/")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def framework_names() -> set[str]:
    names: set[str] = set()
    for d in FRAMEWORK_DIRS:
        for path in sorted(d.glob("*.js")):
            names |= set(DEFINITION.findall(path.read_text(encoding="utf-8")))
    return names


def uses(source: str, names: set[str]) -> list[tuple[int, str]]:
    found = []
    for n, line in enumerate(strip_strings(code_only(source)).split("\n"), 1):
        for name in names:
            # Not a property (`x.flags`) and not an object key (`flags: ...`).
            if re.search(rf"(?<![\w$.]){re.escape(name)}(?![\w$])(?!\s*:(?!:))", line):
                found.append((n, name))
    return found


# A framework that is not CHAI: two sections, one gate, its own categories. The
# shell must draw its track, its status and its exports from it alone.
STAND_IN = """
() => {
  const SECTIONS = [
    {id: "q1", n: 1, title: "Intake ZZQ",
     items: [{id: "q1-1", text: "Need stated ZZQ"}]},
    {id: "q2", n: 2, title: "Review ZZQ",
     items: [{id: "q2-1", text: "Risks weighed ZZQ"},
             {id: "q2-2", text: "Owner named ZZQ"}]},
  ];
  const ITEMS = SECTIONS.flatMap(s => s.items.map(it =>
    ({...it, category: it.id.endsWith("1") ? "K" : "M", section: s})));
  const CLS = {"Approve ZZQ": GateClass.GO, "Halt ZZQ": GateClass.STOP};
  const sp = {
    items: () => ITEMS, itemLabel: it => it.text,
    sections: () => SECTIONS, sectionLabel: s => s.title,
    categories: () => [{id: "K", name: "Keep ZZQ"}, {id: "M", name: "Mind ZZQ"}],
    categoryLabel: k => k === "K" ? "Keep ZZQ" : "Mind ZZQ",
    gates: () => [{id: "G1", after: "q1", title: "Gate one ZZQ"}],
    gateLabel: () => "Gate one ZZQ", gateQuestion: () => "Go on ZZQ?",
    optionLabel: o => o, gateRecord: (p, k) => ((p.zz || {}).gates || {})[k] || {},
    decisionClass: d => CLS[d] || null,
    answers: p => (p.zz || {}).answers || {},
    phase: p => ({key: "intake", label: "Intake ZZQ", msg: "phase.intake", stage: 1}),
    flags: p => [{sev: "amber", text: "Stand-in flag ZZQ"}],
    status: p => ({key: "amber", label: "Needs update", msg: "status.amber"}),
    nextReview: () => null,
    score: (p, list) => ENGINES.chai.score(list || ITEMS, (p.zz || {}).answers || {}),
    reportBody: () => "<p>Stand-in report ZZQ</p>",
    isLive: ph => ph.role === "live", reportViewId: "report", reviewGateId: () => null,
    fileSuffix: "zz-review", schemaId: "zz-review/1",
    statusKnown: v => v === "met", statusLabel: v => v,
  };
  FRAMEWORKS.forEach(f => { f.primary = false; });
  registerFramework({id: "zz", label: "ZZ", primary: true, spine: sp,
    enabled: () => true,
    views: () => [], render: () => "",
    blank: () => ({zz: {answers: {"q1-1": {status: "met"}},
                        gates: {G1: {decision: "Approve ZZQ"}}}}),
    normalize: p => { p.zz = p.zz || {answers: {}, gates: {}}; }});
}
"""


def stand_in() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(APP.as_uri())
        end = time.time() + 15
        while time.time() < end and not page.evaluate(
            "() => typeof LOADED !== 'undefined' && LOADED"
        ):
            page.wait_for_timeout(100)
        page.evaluate(STAND_IN)
        page.evaluate(
            "async () => { await STORE.create('zz1',"
            " normalize(blankProject('Stand-in ZZQ'))); }"
        )
        page.wait_for_timeout(300)
        page.evaluate("goHome()")
        page.wait_for_timeout(200)
        track = page.evaluate(
            "() => (document.querySelector('.lc') || {}).innerHTML || ''"
        )
        check(
            "the track has the stand-in's two sections",
            track.count('class="pip') == 2,
            track[:200],
        )
        check(
            "and its one gate, classed as approved",
            track.count('class="gd go"') == 1,
            track[:200],
        )
        row = page.evaluate("() => document.querySelector('#main').innerText")
        check(
            "the row shows the stand-in's flag", "Stand-in flag ZZQ" in row, row[:300]
        )
        page.evaluate("openProject('zz1', 'setup')")
        page.wait_for_timeout(200)
        md = page.evaluate("exportMD()")
        check(
            "the Markdown has its categories, gate and sections",
            all(
                w in md
                for w in ("Keep ZZQ", "Gate one ZZQ", "Review ZZQ", "Owner named ZZQ")
            ),
            md[:400],
        )
        check(
            "and nothing of CHAI's",
            "Checkpoint A" not in md and "Fairness" not in md,
            "",
        )
        data = page.evaluate("projectJSON(S)")
        check(
            "the JSON lists its criteria and scores by its categories",
            [c["id"] for c in data["checklist"]] == ["q1-1", "q2-1", "q2-2"]
            and set(data["scores"]) == {"overall", "K", "M"},
            str(data["scores"]),
        )
        check(
            "and has no model card, which it does not have",
            "model_card" not in data,
            "",
        )
        csv = page.evaluate("exportCSV()")
        check("the CSV has its phase", "Intake ZZQ" in csv, csv[:200])
        html = page.evaluate("exportHTML()")
        check("the HTML export is its report", "Stand-in report ZZQ" in html, "")
        check(
            "the side-panel button hides: it has no panel",
            page.evaluate("() => document.getElementById('openPreview').hidden"),
        )
        check("no page errors", not errors, "; ".join(errors[:3]))
        browser.close()


def literals(source: str) -> list[tuple[int, str]]:
    """String literals that say a framework's name, comments aside."""
    found = []
    for n, line in enumerate(code_only(source).split("\n"), 1):
        for m in STRING.finditer(line):
            text = m.group(2)
            if FRAMEWORK_WORD.search(text) and text not in ALLOWED_LITERALS:
                found.append((n, text[:60]))
    return found


def shell_paths() -> list[Path]:
    return [p for d in SHELL for p in sorted(d.glob("*.js"))] + SHELL_FILES


def main() -> int:
    names = framework_names()
    print("The names a framework's own code defines")
    check(
        "read from its directories, and there are many",
        len(names) > 20 and {"CARD", "loadSamples", "labelHTML"} <= names,
        f"{len(names)}",
    )
    defined = set()
    for p in (ROOT / "app" / "js").rglob("*.js"):
        defined |= set(DEFINITION.findall(p.read_text(encoding="utf-8")))
    check(
        "the names the engine replaced are defined nowhere",
        not (set(RETIRED) & defined),
        str(sorted(set(RETIRED) & defined)),
    )
    check(
        "OPTICA has no code of its own: it is a definition",
        not (FW_JS / "20-optica").exists(),
    )

    print("The shell, the engine and setup name none of them")
    for path in shell_paths():
        found = uses(path.read_text(encoding="utf-8"), names)
        rel = path.relative_to(ROOT).as_posix()
        check(rel, not found, ", ".join(f"line {n}: {w}" for n, w in found[:5]))

    print("Nor say a framework's name in a string")
    for path in shell_paths():
        found = literals(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT).as_posix()
        check(rel, not found, ", ".join(f"line {n}: {w!r}" for n, w in found[:4]))
    check(
        "the allowlist holds only browser storage keys",
        all(k.startswith("chai-") and "." not in k for k in ALLOWED_LITERALS),
    )
    check(
        "a framework's name in a string is noticed (mutation)",
        bool(literals('label = "CHAI use case";')),
    )
    check("a storage key is not", not literals('localStorage.getItem("chai-ui-v2")'))
    check(
        "an escaped quote stays inside its string",
        bool(literals(r'x = "say \"CHAI\" here";')),
    )
    t0 = time.time()
    literals('"' + "\\a" * 5000)
    check("a run of backslashes cannot make it crawl", time.time() - t0 < 1.0)

    print("A use slipped back in is noticed (mutation)")
    check("a direct call", bool(uses("const x = labelHTML(p);", names)))
    check("a definition read", bool(uses("CARD.forEach(s => s)", names)))
    check("not a comment", not uses("// labelHTML(p) was here\n/* CARD */", names))
    check("not a property of the spine", not uses("const f = spine().flags(p);", names))
    check("not an object key", not uses("const row = {phase: x, flags: y};", names))
    check(
        "not words in a string",
        not uses('h = ["Lifecycle phase"]; c = `<ul class="flags">`;', names),
    )
    check(
        "not fooled by a quote in a regex",
        not uses("s.replace(/\"/g, '\"\"'); x = 'phase';", names),
    )
    check(
        "but code inside a template is read",
        bool(uses("h = `<b>${labelHTML(p)}</b>`;", names)),
    )

    print("A stand-in primary drives the portfolio and the exports")
    stand_in()

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("framework boundary checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
