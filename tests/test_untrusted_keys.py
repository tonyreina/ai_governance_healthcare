#!/usr/bin/env python3
"""A key in a document can never write to an object's prototype (#124).

JSON.parse makes "__proto__" an ordinary own key, and a project document is JSON that
any writer on the project controls. A helper that merges or assigns by key without
looking at the key would then write into Object.prototype, and from there into every
object on the page of everyone who opens the project. CodeQL flagged the path setter
(js/prototype-pollution-utility); the same holds for the merge, the path reader and the
patch builder, so each is checked, in a real browser against the built dashboard.

    pixi run test-untrusted-keys
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# APP_HTML points the suite at another build, to show it failing on one without the fix.
APP = Path(
    os.environ.get("APP_HTML")
    or Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"
)

failures: list[str] = []

UNSAFE = ("__proto__", "constructor", "prototype")


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


POLLUTED = (
    "() => ({}).polluted !== undefined || Object.prototype.polluted !== undefined"
)
CLEAN = "() => { delete Object.prototype.polluted; }"


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("openProject([...PROJECTS.keys()][0], 'checklist')")
        page.wait_for_timeout(300)

        print("A merged document")
        page.evaluate(
            """() => deepMerge({}, JSON.parse('{"__proto__": {"polluted": "yes"}}'))"""
        )
        check("deepMerge does not write through __proto__", not page.evaluate(POLLUTED))
        page.evaluate(CLEAN)
        page.evaluate(
            """() => deepMerge({}, JSON.parse(
                 '{"constructor": {"prototype": {"polluted": "yes"}}}'))"""
        )
        check("nor through constructor.prototype", not page.evaluate(POLLUTED))
        page.evaluate(CLEAN)
        merged = page.evaluate(
            """() => deepMerge({a: {b: 1}}, JSON.parse('{"a": {"c": 2}, "d": 3}'))"""
        )
        check(
            "and still merges ordinary keys", merged == {"a": {"b": 1, "c": 2}, "d": 3}
        )

        print("A path")
        for path in ("__proto__.polluted", "constructor.prototype.polluted"):
            page.evaluate("(p) => setLocal(p, 'yes')", path)
            check(f"setLocal({path!r}) does not pollute", not page.evaluate(POLLUTED))
            page.evaluate(CLEAN)
            patch = page.evaluate(
                "(p) => JSON.stringify(patchFromPath(p, 'yes'))",
                path,
            )
            check(
                f"patchFromPath({path!r}) builds nothing",
                not page.evaluate(POLLUTED) and "polluted" not in patch,
                patch,
            )
            page.evaluate(CLEAN)
            page.evaluate("(p) => edit(p, 'yes')", path)
            check(f"edit({path!r}) writes nothing", not page.evaluate(POLLUTED))
            page.evaluate(CLEAN)
        check(
            "get() does not read a prototype",
            page.evaluate("() => get('constructor.name')") is None,
        )
        check(
            "an ordinary edit still lands",
            page.evaluate(
                "() => { const id = allItems()[0].id; edit(`items.${id}.owner`, 'Ok');"
                " return S.items[id].owner; }"
            )
            == "Ok",
        )

        print("The probe notices (mutation)")
        page.evaluate(
            """() => {
              const naive = (t, s) => { for (const k in s) {
                const both = s[k] && typeof s[k] === "object"
                  && t[k] && typeof t[k] === "object";
                if (both) naive(t[k], s[k]); else t[k] = s[k]; } return t; };
              naive({}, JSON.parse('{"__proto__": {"polluted": "yes"}}'));
            }"""
        )
        check(
            "a merge without the key check is caught by this test",
            page.evaluate(POLLUTED),
        )
        page.evaluate(CLEAN)
        check("and the page is clean again", not page.evaluate(POLLUTED))
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("untrusted key checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
