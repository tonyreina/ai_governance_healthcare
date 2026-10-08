#!/usr/bin/env python3
"""The dashboard tells the server when it produces an export (#33).

Exports are built in the browser from data it already fetched, so the server never saw
one happen: "did account X export any records?" had no answer. The reads that fetched
the data are now recorded server-side (server/tests/test_access_audit.py); this is the
other half, a beacon from the dashboard when a download or print is produced.

It is a record of ordinary use, not a control: a client can omit it. So these tests are
about the honest cases: it is sent for each export format, with the right project and
format, in the server-backed mode only; and when it cannot be sent the user is told, not
left believing it was recorded. The real ApiStore runs, against a stand-in for the
network.

    pixi run test-export-beacon
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []

FAKE_NETWORK = """
(() => {
  globalThis.__posts = [];
  globalThis.__fail = false;
  globalThis.fetch = async (url, opts) => {
    const u = new URL(url, location.href);
    if ((opts && opts.method) === 'POST' && /\\/exports$/.test(u.pathname)) {
      globalThis.__posts.push({path: u.pathname, body: JSON.parse(opts.body)});
      if (globalThis.__fail) return new Response('{}', {status: 500});
      return new Response(null, {status: 204});
    }
    return new Response('[]', {
      status: 200, headers: {'Content-Type': 'application/json'}});
  };
})()
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def fresh(browser, api: bool):
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    page.set_default_timeout(6000)
    page.goto(APP.as_uri())
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    page.evaluate("loadSamples()")
    page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
    page.evaluate("openProject([...PROJECTS.keys()][0], 'report')")
    page.wait_for_timeout(300)
    if api:
        page.evaluate(FAKE_NETWORK)
        page.evaluate("MODE = Mode.API; STORE = new ApiStore('/api')")
    return page


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        print("In the server-backed mode every export is reported")
        page = fresh(browser, api=True)
        pid = page.evaluate("CUR")
        for act, fmt in (
            ("dl-md", "md"),
            ("dl-html", "html"),
            ("dl-json", "json"),
        ):
            page.evaluate("__posts.length = 0")
            page.click(f'[data-act="{act}"]')
            page.wait_for_timeout(400)
            posts = page.evaluate("__posts")
            check(
                f"{act} is reported as {fmt!r} for this project",
                posts
                == [{"path": f"/api/projects/{pid}/exports", "body": {"format": fmt}}],
                str(posts),
            )

        page.evaluate("__posts.length = 0; window.print = () => {}")
        page.click('[data-act="dl-pdf"]') if page.locator(
            '[data-act="dl-pdf"]'
        ).count() else None
        page.wait_for_timeout(500)
        pdf = [p for p in page.evaluate("__posts")]
        check(
            "the PDF export is reported",
            pdf
            == [{"path": f"/api/projects/{pid}/exports", "body": {"format": "pdf"}}],
            str(pdf),
        )

        page.evaluate("__posts.length = 0")
        page.evaluate("goHome()")
        page.wait_for_timeout(300)
        page.click('[data-act="dl-csv"]')
        page.wait_for_timeout(400)
        check(
            "the portfolio CSV is reported at the portfolio endpoint",
            page.evaluate("__posts")
            == [{"path": "/api/exports", "body": {"format": "csv"}}],
            str(page.evaluate("__posts")),
        )
        page.close()

        print("When it cannot be reported, the user is told")
        page = fresh(browser, api=True)
        page.evaluate("__fail = true")
        page.click('[data-act="dl-md"]')
        page.wait_for_timeout(500)
        toast = page.evaluate("document.getElementById('toast').textContent")
        check(
            "a failed report says the export was not recorded",
            "could not be recorded" in toast.lower() and "access log" in toast.lower(),
            toast,
        )
        page.close()

        print("Other modes have no server to tell")
        page = fresh(browser, api=False)
        page.evaluate(FAKE_NETWORK)
        page.click('[data-act="dl-md"]')
        page.wait_for_timeout(400)
        check(
            "browser-only mode sends nothing",
            page.evaluate("__posts.length") == 0,
            str(page.evaluate("__posts")),
        )
        check(
            "and says nothing about a record that does not exist",
            "recorded"
            not in page.evaluate("document.getElementById('toast').textContent").lower()
            or "saved"
            in page.evaluate("document.getElementById('toast').textContent").lower(),
        )
        page.close()
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("export beacon checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
