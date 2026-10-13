"""What a suite does when it cannot run (claim C-33).

CI sets REQUIRE_TESTS=1 so a suite that cannot run FAILS instead of skipping,
because a skip exits 0 and reads as a pass (#32). Most suites read the variable at
their own guard. The few guards that sit AFTER a running stack has answered cannot
be reached by a test that never starts a stack, so they ask this module instead,
and this module is tested directly (tests/test_require_behavior.py) and its callers
are checked by the scan (tests/test_require_tests.py).

The variable is read when asked, not when imported, so a test can set it.
"""

from __future__ import annotations

import os


def required() -> bool:
    """Is a suite that cannot run a failure? True in CI (REQUIRE_TESTS=1)."""
    return bool(os.environ.get("REQUIRE_TESTS"))


def skip_allowed() -> bool:
    """May this part be skipped? Only when not in CI."""
    return not required()


def cannot_run(why: str, failures: list[str] | tuple[str, ...] = ()) -> int:
    """Say why a suite cannot run and return its exit code: 1 under REQUIRE_TESTS=1
    (or when it already failed something), else 0, a visible skip."""
    print(f"  {why}")
    return 1 if failures or required() else 0
