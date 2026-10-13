#!/usr/bin/env python3
"""Every skip in the test code honors REQUIRE_TESTS (claim C-33).

CI sets REQUIRE_TESTS=1 so that a suite which cannot run FAILS instead of
skipping, because a skip exits 0 and reads as a pass: that is how CI once ran
none of the tests (#32). test_workflows.py shows the workflow sets the variable.
It cannot show that each suite then HONORS it, and one that ignores it is a silent
hole. This scans the test code for the ways this repository skips, and demands
that each one reads REQUIRE_TESTS within a few lines:

  * `skipif(`, `pytest.skip(`, `@pytest.mark.skip`, `importorskip(`, `SkipTest`;
  * a script that prints "...skipping..." and returns (a suite that needs Docker,
    a stack or gpg and finds none).

It names these constructs; a new kind of skip with different wording would not be
seen, which is why the scan also demands that it still finds the known sites (it
cannot quietly match nothing). A skip is a failure (CLAUDE.md): never add a
`skip` or `skipif` that ignores the variable, and never edit the allowlist to
get a check green.

    pixi run test-require-tests
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("tests", "server/tests", "mcp/tests")
# Files whose "skip" text is data, not a skip. Each needs its reason here.
ALLOWED = {
    "tests/test_check_claims.py": "synthetic test sources the claims checker reads",
    "tests/test_require_tests.py": "this scan's own examples",
    "server/tests/test_require_behavior.py": "a broken marker it runs on purpose",
    "mcp/tests/test_require_behavior.py": "a broken marker it runs on purpose",
}
# The constructs that skip. A comment is never a skip.
CONSTRUCT = re.compile(
    r"skipif\(|pytest\.skip\(|\.mark\.skip\b|importorskip\(|unittest\.skip|SkipTest"
)
PRINTED = re.compile(r"^\s*print\(.*skipping", re.I)
BEFORE, AFTER = 3, 7  # lines around a skip in which REQUIRE_TESTS must be read
KNOWN_SITES = (  # the scan must still find these, or it has stopped working
    "server/tests/conftest.py",
    "mcp/tests/conftest.py",
    "server/tests/test_merge.py",
    "tests/test_stack.py",
    "tests/test_proxy_identity.py",
    "tests/test_backup_crypto.py",
    "tests/test_proxy_agent_mutations.py",
)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def code_lines(text: str) -> list[str]:
    """The lines, with a comment-only line blanked: a comment that says
    REQUIRE_TESTS is not code that reads it."""
    return ["" if line.lstrip().startswith("#") else line for line in text.split("\n")]


def skip_sites(text: str) -> list[int]:
    """Line numbers (1-based) of every skip in `text`."""
    return [
        number
        for number, line in enumerate(code_lines(text), 1)
        if CONSTRUCT.search(line) or PRINTED.search(line)
    ]


def ignoring_the_variable(text: str) -> list[int]:
    """The skips whose surrounding lines never read REQUIRE_TESTS."""
    lines = code_lines(text)
    bad = []
    for number in skip_sites(text):
        window = lines[max(0, number - 1 - BEFORE) : number + AFTER]
        if not any("REQUIRE_TESTS" in line for line in window):
            bad.append(number)
    return bad


def scanned_files() -> list[Path]:
    found = []
    for directory in SCANNED:
        for path in sorted((ROOT / directory).rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "fixtures" in path.parts or rel in ALLOWED:
                continue
            found.append(path)
    return found


def main() -> int:
    print("Every skip reads REQUIRE_TESTS")
    sites: dict[str, list[int]] = {}
    for path in scanned_files():
        text = path.read_text(encoding="utf-8")
        found = skip_sites(text)
        if found:
            sites[path.relative_to(ROOT).as_posix()] = found
        bad = ignoring_the_variable(text)
        if found:
            check(
                f"{path.relative_to(ROOT).as_posix()}: no skip ignores REQUIRE_TESTS",
                not bad,
                f"a skip at line(s) {bad} never reads it within {BEFORE}/{AFTER} lines",
            )
    check(
        "the scan still finds every known skip site",
        all(site in sites for site in KNOWN_SITES),
        f"missing {[s for s in KNOWN_SITES if s not in sites]}",
    )
    check(
        "the scan finds a plausible number of skips",
        sum(len(v) for v in sites.values()) >= 8,
        str(sum(len(v) for v in sites.values())),
    )

    print("The scan notices (mutation)")
    honest_decorator = (
        "@pytest.mark.skipif(\n"
        '    shutil.which("node") is None and not os.getenv("REQUIRE_TESTS"),\n'
        '    reason="node is not installed",\n)\ndef test_x(): ...\n'
    )
    honest_script = (
        "def main() -> int:\n"
        "    if not stack_up():\n"
        '        print("stack not running - skipping")\n'
        "        return 1 if REQUIRE_TESTS else 0\n"
    )
    check(
        "a decorator that reads REQUIRE_TESTS passes",
        not ignoring_the_variable(honest_decorator),
    )
    check(
        "a script that returns 1 under REQUIRE_TESTS passes",
        not ignoring_the_variable(honest_script),
    )
    mutations = {
        "a bare skipif": (
            "@pytest.mark.skipif(shutil.which('node') is None, reason='x')\n"
            "def test_x(): ...\n"
        ),
        "a bare pytest.skip": "def test_x():\n    pytest.skip('no node')\n",
        "a bare mark.skip": "@pytest.mark.skip\ndef test_x(): ...\n",
        "an importorskip": "np = pytest.importorskip('numpy')\n",
        "a script that prints skipping and exits 0": (
            "def main() -> int:\n"
            '    print("docker unavailable; skipping")\n'
            "    return 0\n"
        ),
        "REQUIRE_TESTS named only in a comment": (
            "def main() -> int:\n"
            "    # REQUIRE_TESTS turns this into a failure, in theory\n"
            '    print("docker unavailable; skipping")\n'
            "    return 0\n"
        ),
        "the variable read far from the skip": (
            "REQUIRE_TESTS = 1\n"
            + "x = 1\n" * 20
            + "@pytest.mark.skipif(True, reason='x')\n"
        ),
    }
    for label, source in mutations.items():
        check(f"{label} is noticed", bool(ignoring_the_variable(source)))
    check(
        "a comment that says skipping is not a skip",
        not skip_sites("# a skip exits 0, skipping it is silent\n"),
    )

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("every skip honors REQUIRE_TESTS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
