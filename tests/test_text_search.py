#!/usr/bin/env python3
"""The dashboard can find every project that contains some text (#57).

Answering "where does this person, vendor or phrase appear?" used to mean opening every
project. "Search all text" on the portfolio looks through every field of every project
the viewer can open, archived ones included, and lists the matching projects with
where the text was found. Each result opens its project. A person's name finds the ids
they are stored under, since access lists and sign-offs hold ids, not names.

It searches the current records only, and says so: earlier revisions and the audit log
are not in the browser. In a real browser, against the built dashboard.

    pixi run test-text-search
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def search(page, text: str, everything: bool) -> None:
    box = page.locator("#qall")
    if box.is_checked() != everything:
        box.click()
    page.fill("#q", text)
    page.wait_for_timeout(250)


def shown(page) -> list[str]:
    return page.eval_on_selector_all(
        ".plist .prow", "rows => rows.map(r => r.dataset.open)"
    )


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        page.set_default_timeout(6000)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        ids = page.evaluate("[...PROJECTS.keys()]")
        target, other, hidden = ids[0], ids[1], ids[2]

        # Plant text in places the name search does not look.
        page.evaluate(
            """([target, other, hidden]) => {
              const put = (id, f) => {
                openProject(id, 'checklist'); f(); flushAllChanges(); };
              put(target, () => edit(`items.${allItems()[0].id}.evidence`,
                                     'Traced to ZEBRA-41 in the vendor packet'));
              const access = {owners: [ME.id || 'me@hosp.org'], writers: [],
                              readers: ['pat@hosp.org']};
              put(other, () => edit('access', access));
              put(hidden, () => edit('meta.scope', 'Covers the zebra-41 rollout'));
              PROJECTS.get(hidden).archived = true;
              NAMES['pat@hosp.org'] = 'Pat Example';
              goHome();
            }""",
            [target, other, hidden],
        )
        page.wait_for_timeout(400)

        print("The quick search still looks at names only")
        search(page, "zebra-41", everything=False)
        check(
            "text inside a field is not a name match",
            shown(page) == [],
            str(shown(page)),
        )

        print("Search all text")
        search(page, "zebra-41", everything=True)
        found = shown(page)
        check(
            "finds every project with the text, case-insensitively",
            sorted(found) == sorted([target, hidden]),
            str(found),
        )
        check("archived projects are included", hidden in found)
        where = page.locator(f'.prow[data-open="{target}"] .hits').inner_text()
        check(
            "each result says where the text was found", "evidence of" in where, where
        )
        note = page.locator("#searchNote").inner_text().lower()
        check(
            "it says earlier versions and the audit log are not searched",
            "earlier versions" in note and "audit log" in note,
            note,
        )

        search(page, "pat example", everything=True)
        check(
            "a person's name finds the projects that hold their id",
            shown(page) == [other],
            str(shown(page)),
        )
        where = page.locator(f'.prow[data-open="{other}"] .hits').inner_text()
        check("and says it was the access list", "access" in where.lower(), where)

        search(page, "no-such-text-anywhere", everything=True)
        check(
            "no match says so",
            shown(page) == []
            and "no project contains" in page.inner_text("#plistHost").lower(),
        )

        print("A result is a link to its project")
        search(page, "zebra-41", everything=True)
        page.click(f'.prow[data-open="{target}"] .pname')
        page.wait_for_timeout(300)
        check("clicking a result opens that project", page.evaluate("CUR") == target)

        print("Hostile content")
        page.evaluate(
            """() => {
              const id = [...PROJECTS.keys()][3];
              openProject(id, 'setup');
              edit('meta.solution', '<img src=x onerror="window.__xss=1">ZEBRA-41');
              flushAllChanges();
              const p = PROJECTS.get(id);
              Object.defineProperty(p, '__proto__', {value: {polluted: 'ZEBRA-41'},
                enumerable: true, configurable: true, writable: true});
              goHome();
            }"""
        )
        page.wait_for_timeout(300)
        search(page, "zebra-41", everything=True)
        check(
            "a project name is shown as text, not markup",
            page.evaluate("window.__xss") is None,
        )
        check(
            "an odd key in a document does not break the search",
            not errors,
            str(errors[:2]),
        )
        check("and does not reach a prototype", page.evaluate("({}).polluted") is None)

        search(page, "", everything=False)
        check("clearing the search shows the portfolio again", len(shown(page)) >= 9)
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("text search checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
