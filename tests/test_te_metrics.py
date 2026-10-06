#!/usr/bin/env python3
"""Check the CHAI Testing & Evaluation metric picker.

CHAI's guidance is to consult the use-case T&E framework when completing the
Applied Model Card. This covers that path end to end: choosing a use case shows
its metrics, selecting one adds a row with the name and category filled and the
measurement fields left empty, and an already-added metric cannot be added twice.

    pixi run test-te
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
DATA = ROOT / "data" / "chai_te_metrics.json"

FREEZE = """
(() => {
  Date.now = () => 1767225600000;
  const R = Date;
  globalThis.Date = class extends R {
    constructor(...a) { return a.length ? new R(...a) : new R(1767225600000); }
    static now() { return 1767225600000; }
  };
  Math.random = () => 0.42;
})()
"""


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
        if not ok:
            failures.append(name)

    expected = json.loads(DATA.read_text(encoding="utf-8"))
    by_slug = {u["slug"]: u for u in expected["use_cases"]}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(FREEZE)
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size > 0", timeout=15000)

        check(
            "all 10 use cases are bundled",
            page.evaluate("Object.keys(CHAI_TE).length") == 10,
            str(page.evaluate("Object.keys(CHAI_TE).length")),
        )

        total = page.evaluate(
            "Object.values(CHAI_TE).reduce((n,u)=>n+u.metrics.length,0)"
        )
        expected_total = sum(len(u["metrics"]) for u in expected["use_cases"])
        check(
            "metric count matches the data file",
            total == expected_total,
            f"{total} != {expected_total}",
        )

        check(
            "records carry CHAI's benchmarks",
            page.evaluate(
                "Object.values(CHAI_TE).some(u=>u.metrics.some(m=>m.benchmark))"
            ),
        )
        check(
            "records carry CHAI's descriptions",
            page.evaluate(
                "Object.values(CHAI_TE).some(u=>u.metrics.some(m=>m.description))"
            ),
        )

        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        page.evaluate(f"openProject({pid!r}, 's4')")
        page.wait_for_timeout(400)

        check("picker is present", page.locator("[data-te-use]").count() == 1)

        # The picker sits inside a collapsed <details> so stage 4 is not
        # dominated by it. Open it the way a user would.
        summary = page.locator("summary", has_text="Suggested metrics from CHAI")
        preselected = page.evaluate("!!(S.meta && S.meta.chaiUseCase)")
        check(
            "picker open iff a use case is already chosen",
            page.locator("[data-te-use]").is_visible() == preselected,
        )
        if not page.locator("[data-te-use]").is_visible():
            summary.click()
            page.wait_for_timeout(300)
        check("picker is reachable", page.locator("[data-te-use]").is_visible())

        slug = "prior-authorization-ai-supported-criteria-matching"
        page.select_option("[data-te-use]", slug)
        page.wait_for_timeout(500)

        offered = page.locator("[data-te]").count()
        check(
            "offers that use case's metrics",
            offered == len(by_slug[slug]["metrics"]),
            f"{offered} != {len(by_slug[slug]['metrics'])}",
        )
        check(
            "choice persists on the project",
            page.evaluate("S.meta.chaiUseCase") == slug,
        )

        before = page.evaluate("S.metrics.length")
        first = page.locator("[data-te]").first
        name = first.get_attribute("data-te")
        first.click()
        page.wait_for_timeout(500)

        check("adds one metric row", page.evaluate("S.metrics.length") == before + 1)
        added = page.evaluate("S.metrics[S.metrics.length-1]")
        check("name is filled from CHAI", added["name"] == name, str(added))
        check("category is filled", added["cat"] in page.evaluate("METRIC_CATS"))
        check(
            "measurement fields stay empty",
            added["value"] == "" and added["ci"] == "" and added["pop"] == "",
            str(added),
        )

        again = page.locator(f'[data-te="{name}"]')
        check("an added metric cannot be added twice", again.is_disabled())

        check(
            "attribution is shown",
            "Coalition for Health AI" in page.inner_text("#main"),
        )
        check("no page errors", not errors, "; ".join(errors[:2]))
        browser.close()

    print()
    if failures:
        print(
            f"{len(failures)} check(s) failed: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
