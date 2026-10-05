#!/usr/bin/env python3
"""Assemble app/ into the single self-contained docs/app/index.html.

Why a build step, and why a single file out:

* The dashboard must stay ONE self-contained file. It runs as a Claude artifact
  (which is a single document), it is opened straight off disk with no server,
  and it is published to GitHub Pages. Native ES modules would break the first
  two, because `file://` blocks module loading.
* But a 1400-line HTML file with CSS, two governance frameworks and all the
  rendering in one <script> is not maintainable, and the frameworks cannot be
  worked on separately.

So the source is split under app/ and concatenated here. The output is
generated: never edit docs/app/index.html by hand.

Run via: pixi run build-app
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app"
OUT = ROOT / "docs" / "app" / "index.html"

CSS_MARK = "/*@CSS@*/"
JS_MARK = "/*@JS@*/"

BANNER = (
    "<!-- GENERATED FILE - do not edit.\n"
    "     Built from app/ by scripts/build_app.py (pixi run build-app).\n"
    "     Edit the sources under app/, then rebuild. -->\n"
)


def ordered(directory: Path, suffix: str) -> list[Path]:
    """Concatenation order, by numeric prefix at EVERY path segment.

    Sorting on the leaf name alone is wrong once sources are nested: both
    `00-core/00-util.js` and `10-frameworks/00-registry.js` start with `00`, and
    a leaf-only sort would interleave them by filename. The key below walks the
    whole relative path so directory order dominates, which is what decides the
    order declarations appear in the bundle.
    """

    def key(path: Path) -> tuple:
        parts = []
        for segment in path.relative_to(directory).parts:
            m = re.match(r"(\d+)", segment)
            parts.append((int(m.group(1)) if m else 9999, segment))
        return tuple(parts)

    return sorted((p for p in directory.rglob(f"*{suffix}")), key=key)


def main() -> int:
    shell = (SRC / "index.html").read_text(encoding="utf-8")
    for mark in (CSS_MARK, JS_MARK):
        if mark not in shell:
            print(f"error: {mark} missing from app/index.html", file=sys.stderr)
            return 1

    css_files = ordered(SRC / "css", ".css")
    js_files = ordered(SRC / "js", ".js")
    if not css_files or not js_files:
        print("error: no sources found under app/", file=sys.stderr)
        return 1

    # Blank line between modules, matching how the sections were separated when
    # this was one file. Keeps the generated output stable and readable.
    css = "\n\n".join(p.read_text(encoding="utf-8").strip("\n") for p in css_files)
    js = "\n\n".join(p.read_text(encoding="utf-8").strip("\n") for p in js_files) + "\n"

    html = shell.replace(CSS_MARK, css).replace(JS_MARK, js)
    if not html.startswith("<!--"):
        html = BANNER + html

    OUT.parent.mkdir(parents=True, exist_ok=True)
    previous = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    OUT.write_text(html, encoding="utf-8")

    changed = "unchanged" if previous == html else "updated"
    print(
        f"{changed}: {OUT.relative_to(ROOT)} "
        f"({len(html):,} bytes from {len(css_files)} css + {len(js_files)} js)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
