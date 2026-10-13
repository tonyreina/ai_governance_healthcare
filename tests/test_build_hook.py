#!/usr/bin/env python3
"""The generated dashboard cannot go stale (claim C-31).

docs/app/index.html, docs/app/manifest.json and proxy/csp.caddy are generated from
app/ by scripts/build_app.py. A pre-commit hook rebuilds them and prek fails the run
when a rebuild changes a file, so a stale file or a hand edit cannot be committed.
Until this test the only evidence was that the hook existed. This shows the hook
would fail:

  * the committed generated files equal a fresh build (so none is stale today);
  * a hand edit of docs/app/index.html is undone by a rebuild, which is a change,
    and a change is what makes prek fail the run;
  * an edit of a source under app/ makes a rebuild differ from the committed file;
  * the hook's `files` pattern matches the sources AND the generated file, so a
    hand edit of the generated file alone also triggers it on a local commit (it did
    not: only CI's `prek run --all-files` caught that), and it takes no filenames
    (it rebuilds everything).

Everything runs on a temporary copy of app/, scripts/ and the generated files, so
nothing in the repository changes. The build takes about a quarter of a second.

    pixi run test-build-hook
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ("docs/app/index.html", "docs/app/manifest.json", "proxy/csp.caddy")
HOOK_ID = "build-app"
MATCHES = (  # a change to any of these must trigger the rebuild
    "app/js/00-core/00-util.js",
    "app/css/app.css",
    "app/frameworks/chai/framework.json",
    "scripts/build_app.py",
    "scripts/build_manifest.py",
    "scripts/framework_enums.py",
    "docs/app/manifest.json",
    "docs/app/index.html",
)
MISSES = ("README.md", "docs/index.md", "server/app/main.py")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def find_hook(config: dict) -> dict | None:
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == HOOK_ID:
                return hook
    return None


def hook_problems(hook: dict | None) -> list[str]:
    """What is wrong with the hook that rebuilds the dashboard."""
    if hook is None:
        return [f"there is no `{HOOK_ID}` hook"]
    problems = []
    if hook.get("entry") != "pixi run build-app":
        problems.append(f"entry is {hook.get('entry')!r}, not `pixi run build-app`")
    if hook.get("pass_filenames") is not False:
        problems.append("it passes filenames, so it would not rebuild everything")
    pattern = hook.get("files") or ""
    for path in MATCHES:
        if not re.search(pattern, path):
            problems.append(f"its `files` pattern does not match {path}")
    for path in MISSES:
        if re.search(pattern, path):
            problems.append(
                f"its `files` pattern matches {path}, which is not a source"
            )
    return problems


def build(workdir: Path) -> None:
    """Run the real build script inside the copy."""
    done = subprocess.run(
        [sys.executable, str(workdir / "scripts" / "build_app.py")],
        capture_output=True,
        text=True,
        cwd=workdir,
    )
    if done.returncode != 0:
        raise RuntimeError(f"build_app.py failed: {done.stderr or done.stdout}")


def make_copy(into: Path) -> None:
    shutil.copytree(ROOT / "app", into / "app")
    shutil.copytree(ROOT / "scripts", into / "scripts")
    (into / "docs").mkdir()
    shutil.copytree(ROOT / "docs" / "app", into / "docs" / "app")
    (into / "proxy").mkdir()
    shutil.copy(ROOT / "proxy" / "csp.caddy", into / "proxy" / "csp.caddy")


def main() -> int:
    print("The hook is wired to rebuild everything on any source or generated change")
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = find_hook(config)
    check(
        "the real build-app hook is right",
        not hook_problems(hook),
        "; ".join(hook_problems(hook)),
    )
    assert hook is not None
    pattern = hook["files"]
    both = r"docs/app/(manifest\.json|index\.html)$"
    assert both in pattern, "the hook's file pattern changed shape; update this test"
    mutants = {
        "the generated file left out of `files`": {
            **hook,
            "files": pattern.replace(both, r"docs/app/manifest\.json$"),
        },
        "the manifest left out of `files`": {
            **hook,
            "files": pattern.replace(both, r"docs/app/index\.html$"),
        },
        "the sources left out of `files`": {
            **hook,
            "files": r"^scripts/build_app\.py$",
        },
        "a hook that takes filenames": {**hook, "pass_filenames": True},
        "a different entry": {**hook, "entry": "pixi run check-app"},
    }
    for label, mutant in mutants.items():
        check(f"{label} is noticed", bool(hook_problems(mutant)))
    check("a missing hook is noticed", bool(hook_problems(None)))

    print("A rebuild disagrees with a stale or hand-edited file")
    committed = {path: (ROOT / path).read_bytes() for path in GENERATED}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        make_copy(work)
        build(work)
        for path in GENERATED:
            check(
                f"the committed {path} equals a fresh build",
                (work / path).read_bytes() == committed[path],
                "it is stale: run pixi run build-app",
            )

        page = work / "docs" / "app" / "index.html"
        page.write_bytes(committed["docs/app/index.html"] + b"<!-- a hand edit -->\n")
        before = page.read_bytes()
        build(work)
        check(
            "a rebuild changes a hand-edited index.html (which is what fails prek)",
            page.read_bytes() != before,
        )
        check(
            "and the rebuild restores the generated file exactly",
            page.read_bytes() == committed["docs/app/index.html"],
        )

        source = work / "app" / "js" / "00-core" / "00-util.js"
        source.write_text(source.read_text() + "\n// a source edit\n", encoding="utf-8")
        build(work)
        check(
            "an edited source makes a rebuild differ from the committed file",
            page.read_bytes() != committed["docs/app/index.html"],
            "the build ignored a change under app/",
        )
        # A deleted generated file is regenerated too: nothing depends on it existing.
        page.unlink()
        build(work)
        check("a deleted index.html is regenerated", page.exists())

    check(
        "the repository's own generated files were not touched",
        all((ROOT / path).read_bytes() == data for path, data in committed.items()),
    )

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("the build-app hook would fail on a stale or hand-edited dashboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())
