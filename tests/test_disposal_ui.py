#!/usr/bin/env python3
"""The delete dialog: honest about what deleting does, and a way to destroy history.

The dialog used to say deleting "destroys the review for everyone: ... and the
audit log. It cannot be undone." In the server-backed mode that was untrue: every
earlier revision stays in the version history. And the path that WOULD destroy
that history, `DELETE /api/projects/{id}/versions`, existed only as a curl command
(#36), so an operator answering an erasure request had nothing in the app to use.

So this drives the real dialog against a mocked API and records what it does:

* in the server-backed mode it says the history is KEPT, and offers, as a separate
  explicit choice, to destroy it;
* without that choice it makes ONE request (delete the project); with it, two, in
  the order that fails safe (destroy the history, then delete the project);
* if the destroy step fails the project is NOT deleted and the user is told;
* in the modes that have no version history (browser-only, artifact) the choice is
  not offered, because there is nothing to destroy, and the wording stays accurate.

    pixi run test-disposal-ui
"""

from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from test_boot_storage import DOCS, HEALTH_OK, serve

ME = "owner@hospital.example"
PID = "p1"
NAME = "Sepsis early warning"
PROJECT = {
    "id": PID,
    "meta": {"solution": NAME},
    "access": {"owners": [ME], "writers": [], "readers": []},
}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def mock_api(page, calls: list[str], *, purge_status: int = 204) -> None:
    """A tiny server that remembers whether the project has been deleted."""
    state = {"deleted": False}

    def handle(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method
        if path == "/api/events":
            return route.abort()
        calls.append(f"{method} {path}")
        json_ok = {"content_type": "application/json"}
        if path == "/api/health":
            return route.fulfill(status=200, body=HEALTH_OK, **json_ok)
        if path == "/api/me":
            body = json.dumps({"id": ME, "name": "Owner", "email": ME, "dev": False})
            return route.fulfill(status=200, body=body, **json_ok)
        if path == "/api/projects" and method == "GET":
            rows = [] if state["deleted"] else [PROJECT]
            return route.fulfill(status=200, body=json.dumps(rows), **json_ok)
        if path == f"/api/projects/{PID}/versions" and method == "DELETE":
            return route.fulfill(status=purge_status, body="", **json_ok)
        if path == f"/api/projects/{PID}" and method == "DELETE":
            state["deleted"] = True
            return route.fulfill(status=204, body="", **json_ok)
        return route.fulfill(status=200, body="[]", **json_ok)

    page.route("**/api/**", handle)


def open_dialog(page) -> None:
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    page.wait_for_function("PROJECTS && PROJECTS.size >= 1", timeout=15000)
    page.evaluate(f"openProject({PID!r}, 'setup')")
    page.wait_for_selector('[data-act="delete"]', timeout=10000)
    page.click('[data-act="delete"]')
    page.wait_for_selector(".modal", timeout=5000)


def confirm(page) -> None:
    page.fill("#delName", NAME)
    page.wait_for_timeout(150)
    page.click("[data-del-go]")
    page.wait_for_timeout(700)


def requests_of(calls: list[str]) -> list[str]:
    """Just the writes the dialog caused, in order."""
    return [c for c in calls if c.startswith("DELETE")]


def main() -> int:
    with serve(DOCS) as base, sync_playwright() as p:
        browser = p.chromium.launch()

        print("Server-backed mode: what the dialog says")
        page = browser.new_page()
        calls: list[str] = []
        mock_api(page, calls)
        page.goto(base + "/app/index.html")
        open_dialog(page)
        text = page.inner_text(".modal")
        check("the dialog names the project", NAME in text)
        check(
            "it says the version history is KEPT",
            "history is kept" in text.lower(),
            text[:300],
        )
        check(
            "it no longer claims to destroy everything forever",
            "forever" not in page.inner_text("#delTitle").lower()
            and "cannot be undone. archive" not in text.lower(),
        )
        check(
            "destroying the history is a separate, unticked choice",
            page.locator("#delPurge").count() == 1 and not page.is_checked("#delPurge"),
        )
        check(
            "the choice says what is kept and what is not",
            "who changed what" in text.lower() and "backups" in text.lower(),
            text[-400:],
        )
        check(
            "the button says plain 'Delete' until the choice is made",
            "destroy" not in page.inner_text("[data-del-go]").lower(),
        )
        page.check("#delPurge")
        check(
            "ticking the choice makes the button say what it will do",
            "destroy" in page.inner_text("[data-del-go]").lower(),
        )
        page.uncheck("#delPurge")
        check(
            "unticking it puts the button back",
            "destroy" not in page.inner_text("[data-del-go]").lower(),
        )
        page.close()

        print("Server-backed mode: delete only")
        page = browser.new_page()
        calls = []
        mock_api(page, calls)
        page.goto(base + "/app/index.html")
        open_dialog(page)
        confirm(page)
        check(
            "exactly one write: delete the project",
            requests_of(calls) == [f"DELETE /api/projects/{PID}"],
            str(requests_of(calls)),
        )
        check(
            "the history was NOT touched",
            not any(c.endswith("/versions") for c in calls),
        )
        page.close()

        print("Server-backed mode: delete and destroy history")
        page = browser.new_page()
        calls = []
        mock_api(page, calls)
        page.goto(base + "/app/index.html")
        open_dialog(page)
        page.check("#delPurge")
        confirm(page)
        check(
            "history first, then the project, in that order",
            requests_of(calls)
            == [f"DELETE /api/projects/{PID}/versions", f"DELETE /api/projects/{PID}"],
            str(requests_of(calls)),
        )
        check(
            "the user is told both happened",
            "destroyed" in page.inner_text("body").lower(),
        )
        page.close()

        print("Server-backed mode: the destroy step fails")
        page = browser.new_page()
        calls = []
        mock_api(page, calls, purge_status=500)
        page.goto(base + "/app/index.html")
        open_dialog(page)
        page.check("#delPurge")
        confirm(page)
        check(
            "the project is NOT deleted if its history could not be destroyed",
            f"DELETE /api/projects/{PID}" not in requests_of(calls),
            str(requests_of(calls)),
        )
        check(
            "and the user is told, not left guessing",
            "not deleted" in page.inner_text("body").lower()
            or "was not deleted" in page.inner_text("body").lower(),
            page.inner_text("body")[-300:],
        )
        page.close()

        print("A mode with no version history")
        page = browser.new_page()
        page.route("**/api/health", lambda r: r.fulfill(status=404, body=""))
        page.goto(base + "/app/index.html")
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 1", timeout=15000)
        page.evaluate("ME.id = null")
        first = page.evaluate("[...PROJECTS.keys()][0]")
        page.evaluate(f"openProject({first!r}, 'setup')")
        page.wait_for_selector('[data-act="delete"]', timeout=10000)
        page.click('[data-act="delete"]')
        page.wait_for_selector(".modal", timeout=5000)
        check(
            "browser-only mode does not offer to destroy a history it lacks",
            page.locator("#delPurge").count() == 0,
        )
        check(
            "and its wording is still the plain, accurate one",
            "cannot be undone" in page.inner_text(".modal").lower(),
        )
        page.close()

        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("disposal UI checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
