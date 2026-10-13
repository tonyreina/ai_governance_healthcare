#!/usr/bin/env python3
"""Decide whether a pull request changes prose documentation and nothing else (D-105).

The Test workflow runs a dozen heavy jobs (a database, three browsers, a Compose
stack, a real Caddy). A pull request that only rewords a page of the guide does not
need them. This script reads the files a pull request changes and prints
`docs_only=true` only when EVERY one is a prose document that no heavy suite reads.
test.yml's `changes` job runs it and the heavy jobs skip on its answer.

It fails closed. Anything unclear (a push, an empty list, a git error, a missing
variable) is `docs_only=false`, which runs everything: a wrong "false" costs minutes,
a wrong "true" lets a change merge without the tests that would have caught it.

What counts as prose documentation:

* a Markdown file at the repository root (README.md, DECISIONS.md, ...), and
* a Markdown file under docs/, except docs/app/ (the built dashboard, which is code
  in effect) and anything that is not Markdown (docs/assets/ holds media).

Even then, a page that a heavy suite reads is NOT docs-only (HEAVY_DOCS), because a
sentence on it can break that suite: server/tests/test_agent_docs.py quotes
docs/agent-api.md, the supply-chain test reads deploy.md, and so on.
tests/test_ci_changes.py scans every test and script for the documents they read and
fails when this list is stale, in either direction. Do not edit it by hand without
running that test.

    git diff --name-only BASE...HEAD | python scripts/ci_changes.py --files
    python scripts/ci_changes.py   # in Actions: reads the event, writes the output
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import PurePosixPath

# The jobs that run for every pull request, docs-only or not: `changes` itself, the
# unit tests of the configuration, and `docs`, added for the docs lane (D-105): the
# suites that read prose and need no database, browser or Docker.
LANE_JOBS = frozenset({"changes", "workflows", "docs"})

# Prose documents that a suite OUTSIDE the lane reads. A change to one runs the full
# pipeline. Keep it exact: tests/test_ci_changes.py fails if a page is missing from
# it (a heavy suite reads it) or does not belong (none does).
HEAVY_DOCS = frozenset(
    {
        "SECURITY.md",
        "docs/agent-api.md",
        "docs/deploy.md",
        "docs/mcp.md",
        "docs/privacy.md",
        "docs/self-hosting.md",
    }
)

PROSE_SUFFIX = ".md"
DOCS_DIR = "docs"
BUILT_APP_DIR = "app"  # docs/app/
PULL_REQUEST = "pull_request"  # enum-ok: GitHub's own event name


def is_prose_doc(path: str) -> bool:
    """A Markdown page at the root or under docs/, outside docs/app/."""
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or p.suffix != PROSE_SUFFIX:
        return False
    if len(p.parts) == 1:
        return True
    return p.parts[0] == DOCS_DIR and p.parts[1] != BUILT_APP_DIR


def classify(files: list[str], event: str = PULL_REQUEST) -> bool:
    """True when the change may skip the heavy jobs. Anything unclear is False."""
    if event != PULL_REQUEST or not files:
        return False
    return all(is_prose_doc(f) and f not in HEAVY_DOCS for f in files)


def changed_files(base: str, head: str) -> list[str]:
    """What the pull request changes since it left the base branch. --no-renames
    lists both halves of a rename, so a code file renamed into docs/ still shows."""
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [f for f in out.split("\0") if f]


def decide(event: str, base: str, head: str) -> bool:
    try:
        if event != PULL_REQUEST or not base or not head:
            return False
        return classify(changed_files(base, head), event)
    except Exception as error:  # fail closed: run everything
        print(f"ci_changes: {error!r}; running every job", file=sys.stderr)
        return False


def main(argv: list[str]) -> int:
    if argv[1:] == ["--files"]:  # classify a list on stdin, for a human
        files = [line.strip() for line in sys.stdin if line.strip()]
        print(f"docs_only={str(classify(files)).lower()}")
        return 0
    docs_only = decide(
        os.environ.get("EVENT_NAME", ""),
        os.environ.get("BASE_SHA", ""),
        os.environ.get("HEAD_SHA", ""),
    )
    line = f"docs_only={str(docs_only).lower()}"
    print(line)
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as out:
            out.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
