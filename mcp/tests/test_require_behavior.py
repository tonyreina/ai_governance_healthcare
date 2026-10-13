"""The MCP suite's `requires_db` FAILS with no database under REQUIRE_TESTS=1 (C-33).

Runs a real pytest in a subprocess with no database and demands that the real
marker, imported from mcp/tests/conftest.py by path, FAILS with REQUIRE_TESTS=1 and
is SKIPPED without it. Mutation: a marker that ignores the variable is noticed.
The server suite's twin is server/tests/test_require_behavior.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

MCP = Path(__file__).resolve().parents[1]
PACKAGE = MCP / "tests"
TIMEOUT = 120

# Loads the real conftest as a package (it imports `.harness`), under a name that
# cannot collide with the installed `mcp` library.
CHILD_MARKER = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "mcp_service_tests", {init!r}, submodule_search_locations=[{package!r}]
)
pkg = importlib.util.module_from_spec(spec)
sys.modules["mcp_service_tests"] = pkg
spec.loader.exec_module(pkg)
from mcp_service_tests import conftest as real

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


def run_pytest(workdir: Path, require: bool) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("REQUIRE_TESTS", "TEST_DATABASE_URL", "DATABASE_URL")
        and not k.startswith("PYTEST_")
    }
    env["PYTHONPATH"] = str(MCP)
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
            "test_child.py",
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


def runs(tmp_path: Path, source: str) -> tuple[dict[str, int], dict[str, int]]:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_child.py").write_text(source, encoding="utf-8")
    return counts(run_pytest(tmp_path, False)), counts(run_pytest(tmp_path, True))


def test_requires_db_skips_without_the_variable_and_fails_with_it(
    tmp_path: Path,
) -> None:
    source = CHILD_MARKER.format(
        init=str(PACKAGE / "__init__.py"), package=str(PACKAGE)
    )
    quiet, loud = runs(tmp_path, source)
    assert quiet.get("skipped") == 1 and not quiet.get("failed"), quiet
    assert loud.get("failed") == 1 and not loud.get("skipped"), loud


def test_a_marker_that_ignores_the_variable_is_noticed(tmp_path: Path) -> None:
    quiet, loud = runs(tmp_path, CHILD_BROKEN_MARKER)
    assert quiet.get("skipped") == 1, quiet
    assert not loud.get("failed") and loud.get("skipped") == 1, loud
