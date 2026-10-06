#!/usr/bin/env python3
"""Capture what the dashboard renders, so a refactor can be proved behavior-safe.

Loads a build in a real browser, seeds the built-in example projects, then dumps
the rail and every view's markup. Two builds that render the same HTML for the
same data are behaviorally identical for everything a user can see.

    pixi run python tests/snapshot_app.py <path-to-index.html> <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SEED = """
(() => {
  // Deterministic: the example seeder uses today's date and random ids, which
  // would make every snapshot differ. Freeze both before seeding.
  Date.now = () => 1767225600000;                       // 2026-01-01T00:00:00Z
  const RealDate = Date;
  globalThis.Date = class extends RealDate {
    constructor(...a) {
      return a.length ? new RealDate(...a) : new RealDate(1767225600000);
    }
    static now() { return 1767225600000; }
  };
  Math.random = () => 0.42;
})()
"""


def snapshot(index: Path) -> dict:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on(
            "console",
            lambda m: (
                errors.append(f"console.error: {m.text}") if m.type == "error" else None
            ),
        )

        page.add_init_script(SEED)
        page.goto(index.resolve().as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)

        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size > 0", timeout=15000)

        out: dict = {"errors": errors, "views": {}}
        out["dashboard"] = (
            page.inner_html("#main") if page.query_selector("#main") else None
        )

        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
        page.wait_for_timeout(400)

        out["rail"] = page.inner_html("#rail")
        out["viewIds"] = page.evaluate(
            "typeof activeViews === 'function' "
            "? activeViews().map(v => v.id) : VIEWS.map(v => v.id)"
        )

        for vid in out["viewIds"]:
            page.evaluate(f"go({json.dumps(vid)})")
            page.wait_for_timeout(120)
            out["views"][vid] = page.inner_html("#main")

        out["label"] = page.inner_html("#labelHost")
        browser.close()
        return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    data = snapshot(Path(argv[0]))
    Path(argv[1]).write_text(
        json.dumps(data, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(
        f"captured {len(data['views'])} views, "
        f"{len(data['errors'])} errors -> {argv[1]}"
    )
    for e in data["errors"]:
        print("  " + e, file=sys.stderr)
    return 1 if data["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
