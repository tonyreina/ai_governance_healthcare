#!/usr/bin/env python3
"""The dashboard's session controls: idle lock, sign-out, and a lost stream (#49).

The application has no session of its own; identity comes from the front door on every
request. So the real automatic-logoff control is the front door's session lifetime, and
docs/deploy.md says where to set it. What belongs here is defense in depth on a shared
workstation, and the honest handling of one failure:

* an idle lock that hides the record and asks for a reload, which goes back through the
  front door. Off by default, and it flushes unsaved edits first so locking never loses
  work;
* a sign-out link to wherever the front door ends a session, rendered only if the URL
  is safe;
* a stream the browser loses (a revoked session cannot reconnect) is reported, where
  `es.onerror = () => {}` used to leave the page silently stale.

    pixi run test-session-ui
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
APP = DOCS / "app" / "index.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def fresh(browser):
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    page.set_default_timeout(6000)
    page.goto(APP.as_uri())
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    page.evaluate("loadSamples()")
    page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
    page.evaluate("openProject([...PROJECTS.keys()][0], 'setup')")
    page.wait_for_timeout(300)
    return page


def locked(page) -> bool:
    return page.evaluate("!!document.getElementById('lockScreen')")


@contextlib.contextmanager
def serve(directory: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        httpd.allow_reuse_address = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()


def health(extra: str = "") -> str:
    return (
        '{"status":"ok","version":"t","database":"up","db_role":"restricted",'
        f'"auth_mode":"proxy-header:proxy"{extra}}}'
    )


def boot_api(browser, base: str, extra: str = ""):
    """Boot the real app against a stand-in API whose health says `extra`."""
    page = browser.new_page()
    page.set_default_timeout(6000)
    page.route(
        "**/api/health",
        lambda r: r.fulfill(
            status=200, body=health(extra), content_type="application/json"
        ),
    )
    page.route(
        "**/api/me",
        lambda r: r.fulfill(
            status=200,
            body='{"id":"a@b","name":"A B","email":"a@b","dev":false}',
            content_type="application/json",
        ),
    )
    page.route(
        "**/api/projects",
        lambda r: r.fulfill(status=200, body="[]", content_type="application/json"),
    )
    page.route("**/api/events", lambda r: r.abort())
    page.goto(base + "/app/index.html")
    page.wait_for_timeout(700)
    return page


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        print("The idle lock")
        page = fresh(browser)
        check("off when the setting is 0", page.evaluate("startIdleLock(0)") is False)
        page.wait_for_timeout(1500)
        check("and nothing locks", not locked(page))

        check("on when given minutes", page.evaluate("startIdleLock(0.02)") is True)
        page.wait_for_timeout(500)
        page.keyboard.press("a")  # activity at 0.5s postpones the 1.2s timer
        page.wait_for_timeout(900)  # 1.4s total, but only 0.9s idle
        check("activity postpones it", not locked(page))
        page.wait_for_timeout(1800)
        check("then it locks after the idle time", locked(page))
        check(
            "the lock is a modal dialog",
            page.evaluate(
                "(() => { const l = document.getElementById('lockScreen');"
                " return l.getAttribute('role') === 'dialog' &&"
                " l.getAttribute('aria-modal') === 'true'; })()"
            ),
        )
        check(
            "the record is not readable behind it",
            page.evaluate(
                "document.getElementById('main').getClientRects().length === 0"
            ),
        )
        text = page.evaluate("document.getElementById('lockScreen').textContent")
        check(
            "it says why, and what to do",
            "inactivity" in text.lower() and "reload" in text.lower(),
            text,
        )
        check(
            "and the lock does not stack if triggered again",
            page.evaluate(
                "(lockNow(), lockNow(),"
                " document.querySelectorAll('#lockScreen').length)"
            )
            == 1,
        )
        with page.expect_navigation():
            page.click('[data-act="unlock"]')
        check("the button reloads, which goes back through the front door", True)
        page.close()

        print("Locking never loses work")
        page = fresh(browser)
        page.evaluate(
            "globalThis.__saved = []; const real = STORE.update.bind(STORE);"
            " STORE.update = (id, patch) => {"
            " __saved.push(patch); return real(id, patch); };"
            " undefined"
        )
        page.evaluate("queuePatch(CUR, {meta: {org: 'Unsaved Org'}})")
        page.evaluate("lockNow()")
        page.wait_for_timeout(300)
        check(
            "a pending edit is saved before the screen locks",
            page.evaluate("__saved.some(p => p.meta && p.meta.org === 'Unsaved Org')"),
            str(page.evaluate("__saved")),
        )
        check("and it is locked", locked(page))
        page.close()

        print("Sign out")
        page = fresh(browser)
        check(
            "no link when nothing is configured",
            page.evaluate("renderSignOut('')") is False
            and page.locator("#signOut").count() == 0,
        )
        for good in ("/.auth/logout", "https://idp.example/logout"):
            page.evaluate(f"renderSignOut({good!r})")
            href = page.evaluate(
                "document.getElementById('signOut').getAttribute('href')"
            )
            check(f"{good} becomes a link", href == good, str(href))
        check(
            "once, even if asked again",
            page.evaluate(
                "(renderSignOut('/x'), document.querySelectorAll('#signOut').length)"
            )
            == 1,
        )
        for bad in (
            "javascript:alert(1)",
            "data:text/html,x",
            "//evil.example/",
            "http://plain.example/",
            "logout",
        ):
            page.evaluate("document.getElementById('signOut')?.remove()")
            check(
                f"{bad} is not rendered, even if the server sent it",
                page.evaluate(f"renderSignOut({bad!r})") is False
                and page.locator("#signOut").count() == 0,
            )
        page.close()

        print("A stream the browser loses is reported")
        page = fresh(browser)
        got = page.evaluate(
            """
            (() => {
              const made = [];
              globalThis.EventSource = class {
                constructor(url) {
                  this.url = url; this.readyState = 1; made.push(this);
                }
                addEventListener() {}
                close() { this.readyState = 2; }
              };
              globalThis.__es = made;
              const errors = [];
              globalThis.__errors = errors;
              const store = new ApiStore('/api');
              store.refresh = async () => {};
              store.subscribeAll(() => {}, e => errors.push(e && e.code));
              return made.length;
            })()
            """
        )
        check("the store opened a stream", got == 1)
        page.evaluate("__es[0].readyState = 0; __es[0].onerror()")
        check(
            "a reconnect in progress is not reported",
            page.evaluate("__errors.length") == 0,
        )
        page.evaluate("__es[0].readyState = 2; __es[0].onerror()")
        check(
            "a stream that is closed for good is reported",
            page.evaluate("__errors") == ["stream_closed"],
            str(page.evaluate("__errors")),
        )
        page.close()

        print("The server's settings drive it (real boot, stand-in API)")
        with serve(DOCS) as base:
            page = boot_api(
                browser,
                base,
                ',"idle_lock_minutes":0,"sign_out_url":"/.auth/logout"',
            )
            check(
                "health's sign_out_url becomes the Sign out link",
                page.evaluate(
                    "(document.getElementById('signOut') || {getAttribute: () => null})"
                    ".getAttribute('href')"
                )
                == "/.auth/logout",
            )
            check("no idle timer when it is 0", not locked(page))
            page.close()

            page = boot_api(browser, base, ',"idle_lock_minutes":0,"sign_out_url":""')
            check(
                "no link when none is configured", page.locator("#signOut").count() == 0
            )
            page.close()

            page = boot_api(browser, base, "")
            check(
                "an older server (no such fields) boots cleanly, without either",
                page.locator("#signOut").count() == 0
                and page.evaluate("!!document.getElementById('main')"),
            )
            page.close()

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("session UI checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
