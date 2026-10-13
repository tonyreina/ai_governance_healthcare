#!/usr/bin/env python3
"""Tests for the docs lane's classifier, scripts/ci_changes.py (D-105).

A docs-only pull request skips the heavy jobs. That is safe only while every prose
document a heavy suite reads is classified as NOT docs-only. About thirty tests and
scripts read prose, so the list of such documents (HEAVY_DOCS) would go stale the
first time someone made a test read another page. This test is what stops that:

* the classifier is run on real example file lists, and on the shapes that must never
  be docs-only: code, workflows, docs/app/, media, a heavy-read page, a push;
* a scan of tests/, server/tests/, mcp/tests/ and scripts/ finds which prose document
  each file reads, and which job runs it (parsed from test.yml and pixi.toml). A
  document read by something outside the docs lane must be in HEAVY_DOCS, and a page
  in HEAVY_DOCS that nothing outside the lane reads must not be (a list that only
  grows stops being a list of reasons);
* each of those is shown failing on a broken copy.

    pixi run test-ci-changes
"""

from __future__ import annotations

import ast
import contextlib
import copy
import fnmatch
import io
import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ci_changes  # noqa: E402

TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
# Where code that reads documents lives. Files under SERVER_SIDE run in the server
# job's pytest (or the MCP leg of it), not through a pixi task.
SOURCE_DIRS = ("tests", "server/tests", "mcp/tests", "scripts")
SERVER_SIDE = ("server/tests/", "mcp/tests/")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# --- the scan -----------------------------------------------------------------


def prose_docs() -> list[str]:
    """Every file the classifier would call a prose document, in this checkout."""
    found = [p.name for p in ROOT.glob("*.md")]
    found += [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "docs").rglob("*.md")
        if ci_changes.is_prose_doc(p.relative_to(ROOT).as_posix())
    ]
    return sorted(found)


def sources() -> list[str]:
    out = []
    for directory in SOURCE_DIRS:
        out += [
            p.relative_to(ROOT).as_posix() for p in (ROOT / directory).rglob("*.py")
        ]
    return sorted(out)


# A string literal that is a Markdown glob: "*.md", "*-checklist.md".
GLOB_PATTERN = re.compile(r"(?m)^(\*[\w*.-]*\.md)$")


def code_strings(source: str) -> str:
    """The string literals a Python source uses, docstrings and comments left out:
    a sentence that says "see CLAUDE.md" does not read it. Unparseable source is
    returned whole (over-reporting is the safe direction)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    skip = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                skip.add(id(first.value))
    return "\n".join(
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in skip
    )


def reads(text: str, doc: str) -> bool:
    """Does this source (see code_strings) mention the document? A mention counts
    however the path is built (`"docs" / "deploy.md"` splits it), so this matches
    the file's name; and a
    glob over Markdown counts as a read of every page it matches. It over-reports on
    purpose: an unneeded entry in HEAVY_DOCS costs minutes, a missing one lets a
    broken page merge untested."""
    name = Path(doc).name
    if re.search(rf"(?<![\w.-]){re.escape(name)}(?![\w])", text):
        return True
    if re.search(r"(?m)^docs$", text):
        return any(fnmatch.fnmatch(name, g) for g in GLOB_PATTERN.findall(text))
    return False


def task_files(tasks: dict[str, str]) -> dict[str, set[str]]:
    """pixi task -> the repository files its command names."""
    return {
        name: set(re.findall(r"[\w./-]+\.py", cmd)) | {cmd}
        for name, cmd in tasks.items()
    }


def pixi_tasks() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pixi.toml").read_text(encoding="utf-8"))
    return {
        name: v if isinstance(v, str) else str(v.get("cmd", ""))
        for name, v in data.get("tasks", {}).items()
    }


def job_commands(workflow: dict) -> dict[str, list[str]]:
    return {
        name: [s["run"] for s in job.get("steps", []) if "run" in s]
        for name, job in (workflow.get("jobs") or {}).items()
    }


def jobs_running(workflow: dict, tasks: dict[str, str]) -> dict[str, set[str]]:
    """source file -> the CI jobs that run it, through a pixi task or directly."""
    ran: dict[str, set[str]] = {}
    for job, commands in job_commands(workflow).items():
        for command in commands:
            for task in re.findall(r"pixi run ([\w-]+)", command):
                for path in task_files(tasks).get(task, set()):
                    ran.setdefault(path, set()).add(job)
            for path in re.findall(r"[\w./-]+\.py", command):
                ran.setdefault(path, set()).add(job)
            for path in re.findall(r"[\w./-]+/tests(?:/[\w.-]+)?", command):
                ran.setdefault(path, set()).add(job)
    return ran


def is_heavy_source(
    path: str, ran: dict[str, set[str]], heavy_text: str, lane_only: set[str]
) -> bool:
    """Is this file run, or imported, by a job outside the docs lane and by no lane
    job? A file a lane job runs is covered by the lane."""
    if path in lane_only:
        return False
    jobs_for = ran.get(path, set())
    if path.startswith(SERVER_SIDE):
        return True  # the server job's pytest; the lane runs only named tests
    if jobs_for:
        return not (jobs_for & ci_changes.LANE_JOBS)
    if path.startswith("scripts/"):
        # Run by no CI task: a hook (the lint workflow runs on every pull request)
        # or a helper. A helper a heavy suite imports is heavy.
        module = Path(path).stem
        return bool(re.search(rf"\b{re.escape(module)}\b", heavy_text))
    return path.startswith("tests/") and not Path(path).name.startswith("test_")


def lane_pytest_files(workflow: dict) -> set[str]:
    """Server-side test files the docs job runs by name (a pytest step that selects
    them). Their document reads are covered by the lane."""
    found = set()
    docs_job = (workflow.get("jobs") or {}).get("docs", {})
    for step in docs_job.get("steps", []):
        run = step.get("run", "")
        if "pytest" in run:
            found |= set(re.findall(r"(?:server|mcp)/tests/[\w.]+\.py", run))
            found |= {
                f"{step['working-directory']}/{m}"
                for m in re.findall(r"\btests/[\w.]+\.py", run)
                if step.get("working-directory")
            }
    return found


def heavy_readers(
    workflow: dict, tasks: dict[str, str], texts: dict[str, str] | None = None
) -> dict[str, list[str]]:
    """prose document -> the heavy sources that read it."""
    texts = texts or {p: (ROOT / p).read_text(encoding="utf-8") for p in sources()}
    ran = jobs_running(workflow, tasks)
    lane_only = lane_pytest_files(workflow)
    heavy_text = "\n".join(
        t
        for p, t in texts.items()
        if p.startswith(SERVER_SIDE)
        or (ran.get(p) and not ran[p] & ci_changes.LANE_JOBS)
    )
    heavy = [p for p in texts if is_heavy_source(p, ran, heavy_text, lane_only)]
    docs = prose_docs()
    strings = {p: code_strings(texts[p]) for p in heavy}
    return {d: [p for p in heavy if reads(strings[p], d)] for d in docs}


def list_problems(readers: dict[str, list[str]], listed: frozenset[str]) -> list[str]:
    problems = []
    for doc, who in readers.items():
        if who and doc not in listed:
            problems.append(
                f"{doc} is read by {who[0]} (outside the docs lane), not in HEAVY_DOCS"
            )
        if not who and doc in listed:
            problems.append(
                f"{doc} is in HEAVY_DOCS but no suite outside the lane reads it"
            )
    problems += [
        f"{doc} is in HEAVY_DOCS but is not a prose document"
        for doc in sorted(listed - set(readers))
    ]
    return problems


# --- tests --------------------------------------------------------------------


def main() -> int:
    workflow = yaml.safe_load(TEST_WORKFLOW.read_text(encoding="utf-8"))
    tasks = pixi_tasks()
    texts = {p: (ROOT / p).read_text(encoding="utf-8") for p in sources()}
    listed = ci_changes.HEAVY_DOCS
    classify = ci_changes.classify

    print("The classifier, on real file lists")
    check("one guide page is docs-only", classify(["docs/running.md"]))
    check(
        "several pages and the README",
        classify(
            [
                "README.md",
                "docs/guide.md",
                "docs/adopting.md",
                "docs/frameworks/chai.md",
            ]
        ),
    )
    check("a record file", classify(["DECISIONS.md", "REQUIREMENTS.md"]))
    check("a new page", classify(["docs/new-page.md"]))
    check("a deleted page is still a page", classify(["docs/adopting.md"]))
    for name, files in {
        "a Python file": ["server/app/main.py"],
        "a test": ["tests/test_workflows.py"],
        "a workflow": [".github/workflows/test.yml"],
        "the classifier itself": ["scripts/ci_changes.py"],
        "the built dashboard": ["docs/app/index.html"],
        "a built-dashboard sibling": ["docs/app/manifest.json"],
        "a Markdown file under the built dashboard": ["docs/app/notes.md"],
        "the dashboard source": ["app/js/00-core/boot.js"],
        "the proxy config": ["proxy/Caddyfile"],
        "pixi.toml": ["pixi.toml"],
        "the lock": ["pixi.lock"],
        "compose.yaml": ["compose.yaml"],
        "the site config": ["zensical.toml"],
        "a Dockerfile": ["server/Dockerfile"],
        "a README inside the server package": ["server/README.md"],
        "the showcase video": ["docs/assets/ai-healthcare-governance-demo.mp4"],
        "a non-Markdown file under docs": ["docs/data.json"],
        "an example": ["examples/project.json"],
        "a path that climbs out": ["docs/../server/app/main.py"],
        "no files at all (unclear)": [],
    }.items():
        check(f"{name} is not docs-only", not classify(files), str(files))
    check(
        "one code file among many pages is not docs-only",
        not classify(["docs/guide.md", "docs/adopting.md", "scripts/gen_crosswalk.py"]),
    )
    for doc in sorted(listed):
        check(
            f"{doc}, which a heavy suite reads, is not docs-only", not classify([doc])
        )
    check(
        "a heavy-read page among harmless ones is not docs-only",
        not classify(["docs/guide.md", "docs/deploy.md"]),
    )
    check(
        "a push is never docs-only",
        not classify(["docs/guide.md"], event="push"),
    )
    check(
        "a manual run is never docs-only",
        not classify(["docs/guide.md"], event="workflow_dispatch"),
    )

    print("Failing closed")
    check(
        "no base commit is not docs-only",
        not ci_changes.decide("pull_request", "", "abc"),
    )
    with contextlib.redirect_stderr(io.StringIO()):
        bad_range = ci_changes.decide("pull_request", "0" * 40, "1" * 40)
    check("a failing diff is not docs-only", not bad_range)
    check("a push event is not docs-only", not ci_changes.decide("push", "a", "b"))

    print("The scan: HEAVY_DOCS is what the heavy suites read")
    docs = prose_docs()
    check("there are prose documents to scan", len(docs) >= 15, str(len(docs)))
    check("there are sources to scan", len(texts) >= 50, str(len(texts)))
    readers = heavy_readers(workflow, tasks, texts)
    problems = list_problems(readers, listed)
    check(
        "HEAVY_DOCS is exactly the documents a heavy suite reads",
        not problems,
        "; ".join(problems),
    )
    check(
        "the pages a docs-only change can touch are read only inside the lane",
        all(not who for d, who in readers.items() if d not in listed),
    )

    print("Mutation tests: the scan must notice")
    check(
        "a heavy-read page missing from HEAVY_DOCS is noticed",
        bool(list_problems(readers, listed - {"docs/deploy.md"})),
    )
    check(
        "a page listed as heavy that nothing heavy reads is noticed",
        bool(list_problems(readers, listed | {"docs/guide.md"})),
    )
    check(
        "a listed page that does not exist is noticed",
        bool(list_problems(readers, listed | {"docs/gone.md"})),
    )
    planted = {**texts, "server/tests/test_new.py": 'open("docs/guide.md")\n'}
    check(
        "a new server test that reads a page makes that page heavy",
        bool(list_problems(heavy_readers(workflow, tasks, planted), listed))
        and "docs/guide.md"
        in "".join(list_problems(heavy_readers(workflow, tasks, planted), listed)),
    )
    planted = {
        **texts,
        "server/tests/test_new.py": 'list((ROOT / "docs").glob("*.md"))\n',
    }
    check(
        "a new server test that globs every page makes every page heavy",
        len(list_problems(heavy_readers(workflow, tasks, planted), listed)) >= 5,
    )
    # A browser suite that begins to read a page: it runs outside the lane.
    planted = {
        **texts,
        "tests/test_session_ui.py": texts["tests/test_session_ui.py"]
        + '\nPAGE = "guide.md"\n',
    }
    check(
        "an existing browser suite that starts to read a page makes it heavy",
        "docs/guide.md"
        in "".join(list_problems(heavy_readers(workflow, tasks, planted), listed)),
    )
    # The same read, in a suite the docs lane runs, is covered.
    planted = {
        **texts,
        "tests/test_docs_media.py": texts["tests/test_docs_media.py"]
        + '\nPAGE = "guide.md"\n',
    }
    check(
        "the same read in a suite the docs lane runs is covered",
        not list_problems(heavy_readers(workflow, tasks, planted), listed),
    )
    moved = copy.deepcopy(workflow)
    moved["jobs"]["docs"]["steps"] = [
        s
        for s in moved["jobs"]["docs"]["steps"]
        if "test-data-scope" not in s.get("run", "")
    ]
    moved["jobs"]["browser-3"]["steps"].append({"run": "pixi run test-data-scope"})
    check(
        "a suite that reads every page, moved out of the lane, makes every page heavy",
        len(list_problems(heavy_readers(moved, tasks, texts), listed)) >= 5,
    )
    unlisted = copy.deepcopy(workflow)
    unlisted["jobs"]["docs"]["steps"] = [
        s for s in unlisted["jobs"]["docs"]["steps"] if "pytest" not in s.get("run", "")
    ]
    check(
        "dropping the docs job's pytest of the all-pages server test is noticed",
        len(list_problems(heavy_readers(unlisted, tasks, texts), listed)) >= 5,
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("ci_changes checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
