#!/usr/bin/env python3
"""A suite whose tool is missing FAILS under REQUIRE_TESTS=1 (claim C-33).

tests/test_require_tests.py is a static scan: it finds the skip constructs it has
words for. A guard written another way (a bare `return 0` when docker is missing)
would not be seen, and the scan never watches a suite fail. This does. It runs each
guarded suite as a real subprocess in an environment where its tool is absent, and
demands that:

  * with REQUIRE_TESTS=1 it exits non-zero, having printed that it was skipping
    (so it is the guard that failed it, not a crash); and
  * without the variable it exits 0 and says it was skipping (so the variable is
    what changes the outcome, not a suite that always fails).

"Absent" is an EMPTY directory as PATH (no docker, gpg, make or node), the absolute
interpreter, and a stack URL on a refused local port. Nothing here starts Docker or
a database, and the only network traffic is one refused connection to 127.0.0.1.

The pytest suites (server and mcp `requires_db`, the node parity test) are run the
same way by server/tests/test_require_behavior.py and
mcp/tests/test_require_behavior.py, because they need pytest.

Not exercised here, and named in claim C-33's Gap: the guards that sit AFTER a
stack answers (tests/test_stack.py: "playwright not installed" and the 404 on the
agent API; tests/test_stack_mcp.py: the 404 on the agent API). They cannot be
reached without a running stack, which this suite never starts.

Mutation: a copy of each guard rewritten to return 0 whatever the variable says is
run through the same check, and must be noticed.

    pixi run test-require-behavior
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 120  # seconds for one child; each takes well under one in practice
GUARD = "return 1 if REQUIRE_TESTS else 0"
# Refused at once: nothing listens on port 1 and nothing may.
UNREACHABLE_STACK = "http://127.0.0.1:1"

# Each is a script suite that guards on a tool or service that is absent here.
SUITES = (
    "tests/test_stack.py",
    "tests/test_stack_mcp.py",
    "tests/test_proxy_identity.py",
    "tests/test_proxy_agent_mutations.py",
    "tests/test_proxy_mcp_mutations.py",
    "tests/test_proxy_image.py",
    "tests/test_backup_crypto.py",
    "tests/test_verify_backup.py",
    "tests/test_dockerignore.py",
)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


@dataclass
class Run:
    code: int
    text: str


def child_env(empty_dir: str, require: bool) -> dict[str, str]:
    """Only what a child needs; the caller's REQUIRE_TESTS, database and tokens are
    not inherited, so the variable is exactly what this run says."""
    env = {
        "PATH": empty_dir,
        "HOME": empty_dir,
        "STACK_URL": UNREACHABLE_STACK,
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if require:
        env["REQUIRE_TESTS"] = "1"
    return env


def run_suite(root: Path, rel: str, require: bool, empty_dir: str) -> Run:
    done = subprocess.run(
        [sys.executable, str(root / rel)],
        capture_output=True,
        text=True,
        cwd=root,
        env=child_env(empty_dir, require),
        timeout=TIMEOUT,
    )
    return Run(done.returncode, done.stdout + done.stderr)


def honest_guard(suite: Run, suite_with_variable: Run) -> tuple[bool, str]:
    """(ok, why not). `suite` ran without REQUIRE_TESTS, the other with it."""
    if "Traceback" in suite.text + suite_with_variable.text:
        return False, "it crashed instead of reaching its guard"
    if suite.code != 0 or "skipping" not in suite.text:
        return False, f"without the variable: exit {suite.code}, not a quiet skip"
    if suite_with_variable.code == 0:
        return False, "with REQUIRE_TESTS=1 it still exited 0 (a silent pass)"
    if "skipping" not in suite_with_variable.text:
        return False, "with REQUIRE_TESTS=1 it failed, but not at its guard"
    return True, ""


def mutated_tree(rel: str, source: str, parent: Path) -> Path:
    """A copy of the repository's top level (symlinks) in which only `rel` is a
    real file, holding `source`. The copy's ROOT is the tree, so it reads the real
    files through the links and cannot change the real suite."""
    tree = parent / "tree"
    tree.mkdir()
    target = tree / rel
    for entry in ROOT.iterdir():
        if entry.name in (".git", ".pixi", "node_modules"):
            continue
        if entry.name == Path(rel).parts[0]:
            continue
        (tree / entry.name).symlink_to(entry)
    target.parent.mkdir(parents=True, exist_ok=True)
    for sibling in (ROOT / Path(rel).parent).iterdir():
        if sibling.name != Path(rel).name and sibling.name != "__pycache__":
            (target.parent / sibling.name).symlink_to(sibling)
    target.write_text(source, encoding="utf-8")
    return tree


def node_check_run(root: Path, require: bool, empty_dir: str) -> list[str]:
    """scripts/check_app.py's node_check, run with no node on PATH."""
    code = (
        "import json, sys; sys.path.insert(0, 'scripts'); import check_app; "
        "print(json.dumps([check_app.SKIPPED] + check_app.node_check('const a = 1;')))"
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=root,
        env=child_env(empty_dir, require),
        timeout=TIMEOUT,
    )
    if done.returncode != 0:
        return [f"crashed: {done.stderr[-300:]}"]
    return json.loads(done.stdout.strip().splitlines()[-1])


def node_check_honest(root: Path, empty_dir: str) -> tuple[bool, str]:
    """With node missing, node_check reports a FAILURE under the variable, and only
    a said skip without it. The first element is the SKIPPED marker itself."""
    local = node_check_run(root, False, empty_dir)
    ci = node_check_run(root, True, empty_dir)
    marker = local[0]
    if len(local) != 2 or not local[1].startswith(marker):
        return False, f"without the variable it did not say it skipped: {local}"
    if len(ci) != 2 or ci[1].startswith(marker):
        return False, f"with REQUIRE_TESTS=1 it still reported a skip: {ci}"
    return True, ""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="chai-require-") as scratch:
        empty = Path(scratch) / "empty"
        empty.mkdir()
        empty_dir = str(empty)

        print("A suite with its tool missing fails under REQUIRE_TESTS=1")
        honest: list[bool] = []
        noticed: list[bool] = []
        for rel in SUITES:
            quiet = run_suite(ROOT, rel, False, empty_dir)
            loud = run_suite(ROOT, rel, True, empty_dir)
            ok, why = honest_guard(quiet, loud)
            check(f"{rel} fails under REQUIRE_TESTS=1 and skips without it", ok, why)
            honest.append(ok)
        check(
            "every guarded script suite fails under REQUIRE_TESTS=1, skips without",
            len(honest) == len(SUITES) and all(honest),
        )

        ok, why = node_check_honest(ROOT, empty_dir)
        check("scripts/check_app.py node check fails under REQUIRE_TESTS=1", ok, why)

        print("The behavioral check notices (mutation)")
        for rel in SUITES:
            source = (ROOT / rel).read_text(encoding="utf-8")
            check(f"{rel} has a guard to mutate", GUARD in source)
            broken = source.replace(GUARD, "return 0", 1)
            work = Path(scratch) / Path(rel).stem
            work.mkdir()
            tree = mutated_tree(rel, broken, work)
            quiet = run_suite(tree, rel, False, empty_dir)
            loud = run_suite(tree, rel, True, empty_dir)
            ok, why = honest_guard(quiet, loud)
            check(
                f"{rel} with a guard that returns 0 is noticed",
                not ok and "silent pass" in why,
                why,
            )
            noticed.append(not ok and "silent pass" in why)
        check(
            "every guarded script suite with a guard that returns 0 is noticed",
            len(noticed) == len(SUITES) and all(noticed),
        )

        source = (ROOT / "scripts/check_app.py").read_text(encoding="utf-8")
        check(
            "check_app.py has the node guard to mutate", "if REQUIRE_TESTS:" in source
        )
        work = Path(scratch) / "check_app"
        work.mkdir()
        tree = mutated_tree(
            "scripts/check_app.py",
            source.replace("if REQUIRE_TESTS:", "if False:", 1),
            work,
        )
        ok, _ = node_check_honest(tree, empty_dir)
        check("check_app.py with a node guard that never fails is noticed", not ok)

        print("The harness itself (a crash and an always-failing suite are not honest)")
        crashed = Run(1, "Traceback (most recent call last):\n")
        quiet_ok = Run(0, "docker unavailable; skipping x")
        always_fails = Run(1, "docker unavailable; skipping x")
        check(
            "a suite that crashes is not accepted as a guard",
            not honest_guard(quiet_ok, crashed)[0],
        )
        check(
            "a suite that fails with and without the variable is not accepted",
            not honest_guard(always_fails, always_fails)[0],
        )
        check(
            "a suite that passes under REQUIRE_TESTS=1 is not accepted",
            not honest_guard(quiet_ok, quiet_ok)[0],
        )
        check(
            "a suite that fails under the variable at its guard is accepted",
            honest_guard(quiet_ok, always_fails)[0],
        )

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("every guarded suite fails when its tool is missing and REQUIRE_TESTS=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
