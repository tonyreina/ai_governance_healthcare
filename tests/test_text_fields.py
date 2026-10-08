#!/usr/bin/env python3
"""Free-text governance fields must not hand their contents to the browser (#59).

Textareas default to `spellcheck="true"`, and with a cloud-backed spellchecker
(Chrome's "Enhanced spell check", some Safari/macOS settings) what is typed is
sent to a third party as it is typed. These fields hold evidence, rationale and
risk notes, and the migration that adds the purge path cites "a patient
identifier pasted into an evidence field" as the reason it exists. The text
would leave the workstation before it is saved and before any server-side
control, every one of which starts at a PATCH, could apply. The same fields
should not persist into the browser's form history either.

This sweeps every view of a project, with OPTICA switched on so its views exist
too, and asserts that EVERY editable textarea opts out of both. Sweeping the
rendered DOM, rather than listing the fields, is the point: a field added next
year is covered without anyone remembering this.

Scope, on purpose: textareas, where evidence, rationale and pasted cases go. The
single-line inputs (an owner, a metric's name, a date) keep the browser's
spellcheck, because they hold short names and numbers rather than narrative, and
turning it off everywhere is a real usability cost on a tool meant to be pleasant
to fill in. The deployment guide also tells operators to disable cloud-backed
spellcheck by policy, which is the control that can actually be enforced.

    pixi run test-text-fields
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

# Editable multi-line fields. Read-only export panes hold output the user does
# not type.
SWEEP = """
() => [...document.querySelectorAll('textarea:not([readonly])')]
  .map(el => ({
    id: el.id || el.getAttribute('data-bind') || el.getAttribute('aria-label') || '?',
    tag: el.tagName.toLowerCase(),
    spellcheck: el.spellcheck,
    autocomplete: el.getAttribute('autocomplete'),
  }))
"""

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size > 0", timeout=15000)
        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        page.evaluate(f"openProject({pid!r}, 'setup')")
        page.wait_for_timeout(300)
        page.click('[data-framework="optica"]')
        page.wait_for_timeout(400)

        views = page.evaluate("activeViews().map(v => v.id)")
        check(
            "the sweep covers CHAI, setup and OPTICA views",
            len(views) > 20,
            str(len(views)),
        )

        seen = 0
        bad: list[str] = []
        for view in views:
            page.evaluate(f"go({view!r})")
            page.wait_for_timeout(60)
            for el in page.evaluate(SWEEP):
                seen += 1
                if el["spellcheck"] is not False or el["autocomplete"] != "off":
                    bad.append(
                        f"{view}:{el['tag']}#{el['id']} spellcheck={el['spellcheck']}"
                        f" autocomplete={el['autocomplete']}"
                    )
        check("the sweep found textareas to check", seen > 20, str(seen))
        check(
            "every editable textarea opts out of spellcheck and form history",
            not bad,
            f"{len(bad)} of {seen}: " + "; ".join(bad[:4]),
        )

        # The sweep must be able to fail: a field that opts out of neither is caught.
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend',"
            " '<textarea id=\"probe\"></textarea>')"
        )
        probe = [e for e in page.evaluate(SWEEP) if e["id"] == "probe"]
        check(
            "a field with the browser defaults is noticed",
            bool(probe) and (probe[0]["spellcheck"] is not False),
            str(probe),
        )
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("text field checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
