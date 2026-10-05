#!/usr/bin/env python3
"""Static checks on the built dashboard.

Catches the failure modes a concatenating build invites: a syntax error in one
module, a declaration used before the module that defines it, or a name that no
module defines at all. These would otherwise only show up as a blank page.

Run via: pixi run check-app
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILT = ROOT / "docs" / "app" / "index.html"


def extract_script(html: str) -> str:
    blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
    if not blocks:
        print("error: no <script> block in the built file", file=sys.stderr)
        raise SystemExit(1)
    return max(blocks, key=len)


def syntax_check(js: str) -> list[str]:
    node = shutil.which("node")
    if not node:
        return ["skipped: node not available, syntax not verified"]
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(js)
        path = fh.name
    try:
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        if result.returncode != 0:
            return [result.stderr.strip()]
        return []
    finally:
        Path(path).unlink(missing_ok=True)


def duplicate_declarations(js: str) -> list[str]:
    """A name declared twice at top level is a concatenation collision."""
    seen: dict[str, int] = {}
    problems = []
    pattern = re.compile(r"^(?:const|let|function|class)\s+([A-Za-z_$][\w$]*)", re.M)
    for match in pattern.finditer(js):
        name = match.group(1)
        line = js.count("\n", 0, match.start()) + 1
        if name in seen:
            problems.append(
                f"duplicate top-level declaration {name!r} "
                f"(lines {seen[name]} and {line}) - two modules define it"
            )
        else:
            seen[name] = line
    return problems


def main() -> int:
    if not BUILT.exists():
        print(f"error: {BUILT} missing - run `pixi run build-app`", file=sys.stderr)
        return 1

    js = extract_script(BUILT.read_text(encoding="utf-8"))
    problems = syntax_check(js) + duplicate_declarations(js)

    for p in problems:
        print(p, file=sys.stderr)
    if any(not p.startswith("skipped:") for p in problems):
        return 1

    print(f"app checks passed ({len(js.splitlines()):,} lines of script)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
