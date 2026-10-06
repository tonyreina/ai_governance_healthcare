#!/usr/bin/env python3
"""Audit entries must not be dropped silently.

writeLog() used to end in `.catch(()=>{})`. An audit log that loses entries
while continuing to look complete is worse than no log: a reviewer cannot tell
a quiet period from a dropped write.

    pixi run test-audit
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def load(browser):
    page = browser.new_page()
    page.goto(APP.as_uri())
    page.wait_for_timeout(400)
    return page


def install_store(page, script):
    """Replace STORE.log with a controllable stub."""
    page.evaluate(
        "fn => { RO = false;"
        " STORE = Object.assign(Object.create(STORE), {log: eval(fn)}); }",
        script,
    )


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        # 1. A transient failure is retried, not dropped.
        page = load(browser)
        install_store(
            page,
            """
            (() => { let n = 0; globalThis.__calls = () => n;
              return (pid, e) => { n++;
                globalThis.__last = e;
                return n < 3 ? Promise.reject({code:'unavailable'}) : Promise.resolve();
              }; })()
        """,
        )
        page.evaluate("() => writeLog('p1', 'Checkpoint A: approved')")
        page.wait_for_timeout(2500)
        check(
            "a transient failure is retried until it lands",
            page.evaluate("() => __calls()") >= 3,
            f"calls={page.evaluate('() => __calls()')}",
        )
        check(
            "the entry that eventually lands is the right one",
            page.evaluate("() => __last.text") == "Checkpoint A: approved",
        )
        check("the queue drains", page.evaluate("() => pendingLogCount()") == 0)
        page.close()

        # 2. A permanent failure is surfaced, not swallowed.
        page = load(browser)
        install_store(page, "(pid, e) => Promise.reject({code:'permission_denied'})")
        page.evaluate("() => writeLog('p1', 'Checkpoint B: approved')")
        page.wait_for_timeout(600)
        saved = page.evaluate("() => document.getElementById('saved').textContent")
        toast = page.evaluate("() => document.getElementById('toast').textContent")
        check(
            "a permission failure is reported in the save indicator",
            "not recorded" in saved.lower(),
            saved,
        )
        check(
            "the user is told the change is not in the audit log",
            "audit log" in toast.lower(),
        )
        check(
            "it is not retried forever", page.evaluate("() => pendingLogCount()") == 0
        )
        page.close()

        # 3. A failure that survives every retry is also surfaced.
        page = load(browser)
        install_store(
            page,
            """
            (() => { let n = 0; globalThis.__calls = () => n;
              return () => { n++; return Promise.reject({code:'unavailable'}); }; })()
        """,
        )
        page.evaluate("() => writeLog('p1', 'Checkpoint C')")
        page.wait_for_timeout(8000)
        saved = page.evaluate("() => document.getElementById('saved').textContent")
        check(
            "a persistent outage gives up and says so",
            "not recorded" in saved.lower(),
            saved,
        )
        check(
            "it stopped retrying rather than spinning",
            page.evaluate("() => __calls()") <= 6,
            f"calls={page.evaluate('() => __calls()')}",
        )
        page.close()

        # 4. The happy path is unchanged and ordered.
        page = load(browser)
        install_store(
            page,
            """
            (() => { globalThis.__seen = [];
              return (pid, e) => {
                __seen.push(e.text); return Promise.resolve();
              }; })()
        """,
        )
        page.evaluate(
            "() => { writeLog('p1','one');"
            " writeLog('p1','two'); writeLog('p1','three'); }"
        )
        page.wait_for_timeout(500)
        check(
            "entries land in the order they were written",
            page.evaluate("() => __seen.join(',')") == "one,two,three",
            page.evaluate("() => __seen.join(',')"),
        )
        page.close()

        # 5. Read-only still writes nothing.
        page = load(browser)
        install_store(
            page,
            """
            (() => { globalThis.__seen = [];
              return (pid, e) => {
                __seen.push(e.text); return Promise.resolve();
              }; })()
        """,
        )
        page.evaluate("() => { RO = true; writeLog('p1','nope'); }")
        page.wait_for_timeout(300)
        check(
            "read-only mode writes no entries",
            page.evaluate("() => __seen.length") == 0,
        )
        page.close()

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("audit log checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
