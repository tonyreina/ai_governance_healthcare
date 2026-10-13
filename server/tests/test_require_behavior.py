"""A database test with no database FAILS under REQUIRE_TESTS=1 (claim C-33).

tests/test_require_tests.py scans for skip constructs; it never watches a suite
fail. This runs a real pytest in a subprocess where there is no database and
demands that the real ``requires_db`` marker (imported from conftest, not copied)
and the node parity test in test_merge.py:

  * FAIL with REQUIRE_TESTS=1 (the test runs, finds no database or no node, fails);
  * are SKIPPED without it (so the variable is what changes the outcome).

Hermetic: no database, no network, an EMPTY directory as PATH for the node test.

Mutation: a marker that ignores the variable, and a copy of test_merge.py whose
skipif does, are run the same way and must be noticed.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
CONFTEST = SERVER / "tests" / "conftest.py"
TEST_MERGE = SERVER / "tests" / "test_merge.py"
TIMEOUT = 120

# Loads the REAL conftest by path, and uses its REAL marker on a test that, like
# every database test, cannot pass without a database.
CHILD_MARKER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("real_conftest", {conftest!r})
real = importlib.util.module_from_spec(spec)
sys.modules["real_conftest"] = real
spec.loader.exec_module(real)

@real.requires_db
def test_needs_a_database():
    assert real.DB_URL, "this test needs a database and there is none"
"""
# The marker as it would be if it ignored the variable.
CHILD_BROKEN_MARKER = """
import os, pytest
DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
requires_db = pytest.mark.skipif(not DB_URL, reason="no database")

@requires_db
def test_needs_a_database():
    assert DB_URL, "this test needs a database and there is none"
"""


def run_pytest(
    workdir: Path, args: list[str], require: bool, path: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("REQUIRE_TESTS", "TEST_DATABASE_URL", "DATABASE_URL")
        and not k.startswith("PYTEST_")
    }
    env["PYTHONPATH"] = str(SERVER)
    if path is not None:
        env["PATH"] = path
    if require:
        env["REQUIRE_TESTS"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            "--rootdir",
            str(workdir),
            "-c",
            str(workdir / "pytest.ini"),
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=workdir,
        env=env,
        timeout=TIMEOUT,
    )


def counts(done: subprocess.CompletedProcess[str]) -> dict[str, int]:
    return {
        word: int(n)
        for n, word in re.findall(r"(\d+) (passed|failed|skipped|error)", done.stdout)
    }


@pytest.fixture
def work(tmp_path: Path) -> Path:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    return tmp_path


def marker_runs(work: Path, source: str) -> tuple[dict[str, int], dict[str, int]]:
    (work / "test_child.py").write_text(source, encoding="utf-8")
    quiet = run_pytest(work, ["test_child.py"], require=False)
    loud = run_pytest(work, ["test_child.py"], require=True)
    return counts(quiet), counts(loud)


def test_requires_db_skips_without_the_variable_and_fails_with_it(work: Path) -> None:
    quiet, loud = marker_runs(work, CHILD_MARKER.format(conftest=str(CONFTEST)))
    assert quiet.get("skipped") == 1 and not quiet.get("failed"), quiet
    assert loud.get("failed") == 1 and not loud.get("skipped"), loud


def test_a_marker_that_ignores_the_variable_is_noticed(work: Path) -> None:
    quiet, loud = marker_runs(work, CHILD_BROKEN_MARKER)
    assert quiet.get("skipped") == 1, quiet
    # The real marker fails here; this one skips, which is the silent pass.
    assert not loud.get("failed") and loud.get("skipped") == 1, loud


def node_parity(
    work: Path, test_file: Path, require: bool
) -> subprocess.CompletedProcess[str]:
    empty = work / "empty"
    empty.mkdir(exist_ok=True)
    return run_pytest(
        work,
        [str(test_file), "-k", "test_parity_with_the_browsers_deepmerge"],
        require=require,
        path=str(empty),
    )


def test_node_parity_skips_without_the_variable_and_fails_with_it(work: Path) -> None:
    quiet = counts(node_parity(work, TEST_MERGE, require=False))
    loud = counts(node_parity(work, TEST_MERGE, require=True))
    assert quiet.get("skipped") == 1 and not quiet.get("failed"), quiet
    assert loud.get("failed") == 1 and not loud.get("skipped"), loud


def test_a_node_skipif_that_ignores_the_variable_is_noticed(work: Path) -> None:
    source = TEST_MERGE.read_text(encoding="utf-8")
    broken = source.replace(' and not os.getenv("REQUIRE_TESTS")', "", 1)
    assert broken != source, "test_merge.py's skipif no longer reads REQUIRE_TESTS"
    copy = work / "test_merge_copy.py"
    copy.write_text(broken, encoding="utf-8")
    loud = counts(node_parity(work, copy, require=True))
    assert loud.get("skipped") == 1 and not loud.get("failed"), loud
