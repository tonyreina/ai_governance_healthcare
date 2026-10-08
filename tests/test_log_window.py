#!/usr/bin/env python3
"""A window onto the audit history must never pass for the whole of it (#40).

Three things were wrong in the dashboard, beside the API that offered no way back
past entry 60 (tested in server/tests/test_log_paging.py):

* every export rendered whatever the store had, so a PDF filed as the record of a
  two-year review showed the newest 60 entries and said nothing about the rest;
* the changelog said "older entries stay in the store" and gave no way to see them;
* `LocalStore` kept 100 and DELETED the rest, so in browser-only mode entry 101 was
  not hidden from a view, it was gone.

45 CFR 164.316(b)(2)(i) wants documentation retained, and a record that cannot be
read is not meaningfully retained.

    pixi run test-log-window
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


# A stand-in for the network, so the REAL ApiStore runs. What is faked is the
# server's answer, which server/tests/test_log_paging.py tests for real.
FAKE_API = """
(() => {
  const TOTAL = 412;
  globalThis.__asked = [];
  const entries = n => Array.from({length: n}, (_, i) => ({
    at: new Date(Date.UTC(2026, 0, 1) + (TOTAL - i) * 60000).toISOString(),
    by: 'a@b', text: 'entry ' + (TOTAL - i)}));
  globalThis.fetch = async (url) => {
    const u = new URL(url, location.href);
    if (!u.pathname.endsWith('/log')) return new Response('[]', {status: 200});
    globalThis.__asked.push(u.search);
    const limit = Math.min(+(u.searchParams.get('limit') || 60), 500);
    return new Response(JSON.stringify(entries(Math.min(limit, TOTAL))), {
      status: 200,
      headers: {'Content-Type': 'application/json', 'X-Log-Total': String(TOTAL)},
    });
  };
})()
"""


def ask(page, script: str):
    """Evaluate a promise-returning script; a timeout is a failed check, not a crash."""
    try:
        return page.evaluate(script)
    except Exception as exc:  # playwright TimeoutError, or the page rejecting
        return {"error": str(exc).splitlines()[0]}


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        pid = page.evaluate("[...PROJECTS.keys()][0]")
        page.evaluate(f"openProject({pid!r}, 'setup')")
        page.wait_for_timeout(300)

        print("LocalStore keeps every entry (it used to delete past 100)")
        before = page.evaluate("(STORE.d.logs[CUR] || []).length")
        page.evaluate(
            "(async () => { for (let i = 0; i < 150; i++)"
            " await STORE.log(CUR,"
            " {at: new Date().toISOString(), by: 'a', text: 'n' + i}); })()"
        )
        page.wait_for_timeout(500)
        check(
            "150 more entries are all still stored, past the old limit of 100",
            page.evaluate("STORE.d.logs[CUR].length") == before + 150,
            f"{before} before, {page.evaluate('STORE.d.logs[CUR].length')} after",
        )
        page.evaluate("go('changelog')")
        page.wait_for_timeout(300)
        check(
            "the changelog shows them all and claims no window",
            page.evaluate("LOG.length") >= 150
            and "newest" not in page.evaluate("changelogHTML()").lower(),
        )

        print("When storage is full, the user is told")
        page.evaluate(
            "(() => { const real = Storage.prototype.setItem;"
            " Storage.prototype.setItem = function(k, v) {"
            "   if (k === STORE.k)"
            "     throw new DOMException('quota', 'QuotaExceededError');"
            "   return real.call(this, k, v); }; })()"
        )
        page.evaluate("STORE.log(CUR, {at: 'x', by: 'a', text: 'one more'})")
        page.wait_for_timeout(200)
        toast = page.evaluate("document.getElementById('toast').textContent")
        check(
            "a full browser store says so instead of failing silently",
            "storage is full" in toast.lower(),
            toast,
        )
        page.close()

        print("A window is disclosed wherever the history is shown")
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        pid = page.evaluate("[...PROJECTS.keys()][0]")
        page.evaluate(f"openProject({pid!r}, 'setup')")
        page.wait_for_timeout(300)
        page.evaluate(
            "LOG = Array.from({length: 60}, (_, i) => ({at: '2026-01-01T00:00:00Z',"
            " by: 'a@b', text: 'entry ' + i})); LOG_TOTAL = 412;"
        )
        window = "newest 60 of 412"
        check(
            "the changelog says 'newest 60 of 412'",
            window in page.evaluate("changelogHTML()"),
        )
        check("the markdown export says it", window in page.evaluate("exportMD()"))
        check(
            "the printable report says it",
            window in page.evaluate("reportBody(false)"),
        )

        check(
            "browser-only mode offers no 'older' button it cannot support",
            "log-older" not in page.evaluate("changelogHTML()"),
        )
        # With a store that can go deeper, the button is there and it works.
        page.evaluate(
            "globalThis.__older = []; STORE = Object.assign(Object.create(STORE),"
            " {showOlderLog: id => { __older.push(id); return Promise.resolve(); }});"
            " go('changelog')"
        )
        page.wait_for_timeout(300)
        check(
            "an API-backed changelog offers 'Show older entries'",
            page.locator('[data-act="log-older"]').count() == 1,
        )
        page.click('[data-act="log-older"]')
        page.wait_for_timeout(200)
        check(
            "clicking it asks the store for this project's older entries",
            page.evaluate("__older.length") == 1
            and page.evaluate("__older[0] === CUR"),
            str(page.evaluate("__older")),
        )
        page.evaluate(
            "LOG_TOTAL = 900; LOG = Array.from({length: 500},"
            " (_, i) => ({at: 'x', by: 'a', text: 'e' + i}))"
        )
        html = page.evaluate("changelogHTML()")
        check(
            "past the cap it points at the API rather than a dead button",
            "log-older" not in html and "before=" in html,
        )

        page.evaluate("LOG_TOTAL = 60; LOG = LOG.slice(0, 60)")
        check(
            "a complete history claims no window",
            window not in page.evaluate("changelogHTML()")
            and "newest"
            not in page.evaluate("exportMD()").lower().split("sign-off")[1],
        )
        page.evaluate("LOG_TOTAL = null; LOG = LOG.slice(0, 10)")
        check(
            "a short history of unknown length claims no window",
            "newest" not in page.evaluate("changelogHTML()").lower(),
        )
        page.evaluate(
            "LOG = Array.from({length: 60}, (_, i) => ({at: '2026-01-01T00:00:00Z',"
            " by: 'a@b', text: 'entry ' + i})); LOG_TOTAL = null;"
        )
        check(
            "a full page of unknown length says older entries may exist",
            "may exist" in page.evaluate("changelogHTML()"),
        )
        page.close()

        print("The real ApiStore reads the total and can go further back")
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        page.set_default_timeout(4000)  # a missing feature fails fast, not for minutes
        page.goto(APP.as_uri())
        page.wait_for_function("typeof ApiStore !== 'undefined'", timeout=15000)
        page.evaluate(FAKE_API)
        got = ask(
            page,
            """
            new Promise(resolve => {
              const store = new ApiStore('/api');
              const stop = store.subscribeLog('p1', (rows, meta) => {
                resolve({n: rows.length, total: meta && meta.total,
                         first: rows[0].text});
              });
            })
            """,
        )
        check("the first page is the newest 60", got.get("n") == 60, str(got))
        check("the total reaches the caller", got.get("total") == 412, str(got))

        deeper = ask(
            page,
            """
            new Promise(resolve => {
              const store = new ApiStore('/api');
              let calls = 0;
              store.subscribeLog('p1', (rows, meta) => {
                calls++;
                if (calls === 1) store.showOlderLog('p1');
                else resolve({n: rows.length, total: meta.total, asked: __asked});
              });
            })
            """,
        )
        check(
            "asking for older entries fetches a deeper page",
            deeper.get("n") == 120,
            str(deeper),
        )
        check(
            "and does it with an explicit limit, not by guessing",
            any("limit=120" in a for a in deeper.get("asked", [])),
            str(deeper),
        )
        capped = ask(
            page,
            """
            new Promise(resolve => {
              const store = new ApiStore('/api');
              store.subscribeLog('p1', () => {});
              for (let i = 0; i < 20; i++) store.showOlderLog('p1');
              setTimeout(() => resolve(__asked.map(
                a => +new URLSearchParams(a).get('limit'))), 300);
            })
            """,
        )
        check(
            "the depth stops at the server's cap of 500",
            isinstance(capped, list)
            and max(capped) == 500
            and all(x <= 500 for x in capped if x),
            str(capped),
        )
        check("no page errors", not errors, "; ".join(errors[:2]))
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("log window checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
