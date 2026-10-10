#!/usr/bin/env python3
"""End-to-end checks for the OPTICA framework in a real browser.

Covers the properties the crosswalk analysis says must hold: OPTICA is off by
default, switching it on adds exactly 14 views and 77 items, answers persist
through a disable/enable cycle, and -- the one that matters most -- an OPTICA
answer never moves a CHAI score.

    pixi run test-app
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

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


def run() -> list[str]:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
        if not ok:
            failures.append(name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(FREEZE)
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size > 0", timeout=15000)

        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        page.evaluate(f"openProject({pid!r}, 'setup')")
        page.wait_for_timeout(300)

        check(
            "OPTICA defaults to off",
            page.evaluate("FACADES.optica.enabled(S) === false"),
        )
        check(
            "no optica key on an untouched project",
            page.evaluate("S.optica === undefined"),
        )
        base_views = page.evaluate("activeViews().length")
        chai_before = page.evaluate(
            "FACADES.chai.score(ENGINES.chai.sections[0].items, S).pct"
        )

        # Switch it on through the UI, not by poking state.
        page.click('[data-framework="optica"]')
        page.wait_for_timeout(400)

        check(
            "OPTICA reports enabled",
            page.evaluate("FACADES.optica.enabled(S) === true"),
        )
        added = page.evaluate("activeViews().length") - base_views
        check("adds 14 views (overview + 13 chapters)", added == 14, f"added {added}")
        check("exposes 77 items", page.evaluate("ENGINES.optica.items.length") == 77)
        check(
            "item keys are dot-free",
            page.evaluate("ENGINES.optica.items.every(i => !i.id.includes('.'))"),
        )

        # Answer an item, then assert CHAI is untouched.
        page.evaluate("go('o7')")
        page.wait_for_timeout(300)
        page.click('[data-set="7-11"][data-s="met"]')
        page.wait_for_timeout(400)
        check(
            "answer recorded",
            page.evaluate("(FACADES.optica.answers(S)['7-11'] || {}).status === 'met'"),
        )
        check(
            "CHAI score unmoved by an OPTICA answer",
            page.evaluate("FACADES.chai.score(ENGINES.chai.sections[0].items, S).pct")
            == chai_before,
        )
        check("CHAI items untouched", page.evaluate("S.items['7-11'] === undefined"))

        # A decline is answered but contributes nothing to the percentage.
        page.click('[data-set="7-12"][data-s="declined"]')
        page.wait_for_timeout(400)
        sc = page.evaluate("FACADES.optica.score(null, S)")
        check("decline counted separately", sc["declined"] == 1, str(sc))
        check("decline counts as answered", sc["answered"] == 2, str(sc))
        # #173: the change history names an OPTICA status in OPTICA's words.
        page.evaluate("flushChanges(CUR, 'optica.answers.7-11.status')")
        page.wait_for_timeout(300)
        entry = page.evaluate(
            "(LOG.find(e => /OPTICA 7\\.11: status/.test(e.text)) || {}).text || ''"
        )
        check(
            "the history says Answered, OPTICA's word, not CHAI's Met",
            "Answered" in entry and "Met" not in entry,
            entry,
        )

        # #172: the reason field appears as soon as Declined is chosen, not only after
        # the screen is drawn again.
        check(
            "choosing Declined shows the reason field at once",
            page.query_selector('[data-bind="optica.answers.7-12.declineReason"]')
            is not None,
        )

        # #171: a soft refresh re-syncs each status button from the store it names.
        # It used to read every button from CHAI's answers, so OPTICA's pressed
        # state was cleared (no CHAI item has the key 7-11).
        page.evaluate("syncInputs()")
        check(
            "a re-sync keeps an OPTICA answer's button pressed",
            page.get_attribute('[data-set="7-11"][data-s="met"]', "aria-pressed")
            == "true",
            page.get_attribute('[data-set="7-11"][data-s="met"]', "aria-pressed") or "",
        )
        check(
            "and leaves the other buttons unpressed",
            page.get_attribute('[data-set="7-11"][data-s="notmet"]', "aria-pressed")
            == "false",
        )

        # Off then on again must not lose answers.
        page.evaluate("go('setup')")
        page.wait_for_timeout(200)
        page.click('[data-framework="optica"]')
        page.wait_for_timeout(400)
        check(
            "views removed when off",
            page.evaluate("activeViews().length") == base_views,
        )
        check(
            "answers kept while off",
            page.evaluate("(FACADES.optica.answers(S)['7-11'] || {}).status === 'met'"),
        )
        page.click('[data-framework="optica"]')
        page.wait_for_timeout(400)
        check(
            "answers survive an off/on cycle",
            page.evaluate("(FACADES.optica.answers(S)['7-11'] || {}).status === 'met'"),
        )

        check("no page errors", not errors, "; ".join(errors[:3]))
        browser.close()
    return failures


def main() -> int:
    if not APP.exists():
        print("error: build the app first (pixi run build-app)", file=sys.stderr)
        return 1
    print("OPTICA framework")
    failures = run()
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
