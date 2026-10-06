#!/usr/bin/env python3
"""The app must not silently fall back to browser-local storage.

This covers the boot decision in app/js/20-app/80-boot.js, which used to treat
every failure of /api/health as "no server here, use localStorage". Three
situations were collapsed into one, and two of them are harmful:

  * a genuinely static host      -> localStorage is correct
  * a server that is DOWN        -> falling back strands work in a browser
  * a server that said NO (401)  -> falling back hands a denied user a
                                    working private workspace

Each case is driven by intercepting /api/health in a real browser.

    pixi run test-boot
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parent.parent / "docs"


@contextlib.contextmanager
def serve(directory: Path):
    """Serve `directory` on a free localhost port for the duration.

    The app must be loaded over http://, not file://. On a file:// origin a
    fetch of /api/health resolves to file:///api/health and fails before
    Playwright's route interception sees it, so EVERY case would look like
    "no API here" and the test would pass without testing anything.
    """

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass  # one line per request is noise

    handler = functools.partial(Quiet, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        httpd.allow_reuse_address = True
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()


HEALTH_OK = (
    '{"status":"ok","version":"test","database":"up","auth_mode":"proxy-header:proxy"}'
)

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def boot(page, base, health, *, me=None, seen_origin=None):
    """Load the app with /api/health answering however `health` says.

    `health` is either an int status, or a (status, body) pair. `seen_origin`
    seeds the "this origin has served an API before" marker.
    """
    status, body = health if isinstance(health, tuple) else (health, "")

    def handle_health(route):
        if status == 0:
            route.abort("failed")
        else:
            route.fulfill(status=status, body=body, content_type="application/json")

    page.route("**/api/health", handle_health)
    page.route(
        "**/api/me",
        lambda r: r.fulfill(
            status=200,
            body=me or '{"id":"a@b","name":"A B","email":"a@b","dev":false}',
            content_type="application/json",
        ),
    )
    page.route(
        "**/api/projects",
        lambda r: r.fulfill(status=200, body="[]", content_type="application/json"),
    )
    page.route("**/api/events", lambda r: r.abort())

    if seen_origin is not None:
        page.add_init_script(
            "try{localStorage.setItem('chai-api-origin-seen',"
            f"{seen_origin!r})}}catch(e){{}}"
        )
    page.goto(base + "/app/index.html")
    page.wait_for_timeout(600)


def main() -> int:
    with serve(DOCS) as base, sync_playwright() as p:
        browser = p.chromium.launch()

        # 1. A healthy API: shared workspace, no warning banner.
        page = browser.new_page()
        boot(page, base, (200, HEALTH_OK))
        check(
            "healthy API -> shared workspace",
            page.locator("#mode").inner_text().strip() == "Shared workspace",
            page.locator("#mode").inner_text(),
        )
        check(
            "healthy API -> no local-storage warning",
            page.locator("#storageWarning").count() == 0,
        )
        check(
            "healthy API -> origin is remembered",
            page.evaluate("localStorage.getItem('chai-api-origin-seen')")
            == page.evaluate("location.origin"),
        )
        page.close()

        # 2. The API says NO. This must never become a usable workspace.
        for status in (401, 403):
            page = browser.new_page()
            boot(page, base, status)
            body = page.locator("#main").inner_text()
            check(
                f"{status} -> blocking error, not a workspace",
                "do not have access" in body.lower(),
                body[:120],
            )
            check(
                f"{status} -> no store was created",
                page.evaluate("typeof STORE === 'undefined' || STORE === null"),
            )
            check(
                f"{status} -> nothing written to localStorage",
                page.evaluate(
                    "localStorage.getItem('chai-portfolio-local-v1') === null"
                ),
            )
            page.close()

        # 3. The API is erroring. Same: stop, do not fall back.
        page = browser.new_page()
        boot(page, base, 503)
        check(
            "503 -> blocking error",
            "cannot reach" in page.locator("#main").inner_text().lower(),
        )
        check(
            "503 -> no local store",
            page.evaluate("localStorage.getItem('chai-portfolio-local-v1') === null"),
        )
        page.close()

        # 4. Network failure, but this origin has served an API before.
        page = browser.new_page()
        boot(page, base, 0, seen_origin=base)
        origin = page.evaluate("location.origin")
        if origin == "null":
            # file:// origins serialize as "null"; seed it correctly and retry.
            page.close()
            page = browser.new_page()
            boot(page, 0, seen_origin="null")
        check(
            "network failure on a known-API origin -> blocking error",
            "cannot reach" in page.locator("#main").inner_text().lower(),
            page.locator("#main").inner_text()[:120],
        )
        page.close()

        # 5. A genuinely static host, never seen an API: localStorage IS right,
        #    and it must say so in the layout.
        page = browser.new_page()
        boot(page, base, 404)
        check(
            "static host -> browser-only mode",
            page.locator("#mode").inner_text().strip() == "This browser only",
        )
        check(
            "static host -> standing warning is shown",
            page.locator("#storageWarning").count() == 1,
        )
        warning = (
            page.locator("#storageWarning").inner_text()
            if page.locator("#storageWarning").count()
            else ""
        )
        check(
            "static host -> warning names the risk",
            "patient-identifiable" in warning.lower(),
            warning[:120],
        )
        check(
            "static host -> dashboard is usable",
            page.locator("[data-act='new']").count() > 0,
        )
        page.close()

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("boot storage checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
