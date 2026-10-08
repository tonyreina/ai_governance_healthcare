#!/usr/bin/env python3
"""The litigation hold on the setup page (#57, R-56, D-62).

The owner chose holds an owner places and lifts, with a reason. The API is tested
against a real PostgreSQL in server/tests/test_holds.py; this drives the real
dashboard against a mocked API that keeps the hold's state, and records what the
page sends and shows:

* an owner, in the server-backed mode, sees whether the project is held, and its
  history, with each reason;
* placing a hold asks for a reason and will not send without one; it sends the
  action and the reason, and the page then says the project is held;
* lifting it works the same way;
* someone who is not an owner, and the browser-only mode, see no hold section.

    pixi run test-holds-ui
"""

from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from test_boot_storage import DOCS, HEALTH_OK, serve

ME = "owner@hospital.example"
PID = "p1"
PROJECT = {
    "id": PID,
    "meta": {"solution": "Sepsis early warning"},
    "access": {"owners": [ME], "writers": ["w@hospital.example"], "readers": []},
}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def mock_api(page, sent: list[dict], me: str = ME) -> None:
    history: list[dict] = []

    def state() -> str:
        held = bool(history) and history[0]["action"] == "place"
        return json.dumps({"held": held, "history": history})

    def handle(route):
        request = route.request
        path = urlparse(request.url).path
        json_ok = {"content_type": "application/json"}
        if path == "/api/events":
            return route.abort()
        if path == "/api/health":
            return route.fulfill(status=200, body=HEALTH_OK, **json_ok)
        if path == "/api/me":
            body = json.dumps({"id": me, "name": me, "email": me, "dev": False})
            return route.fulfill(status=200, body=body, **json_ok)
        if path == "/api/projects" and request.method == "GET":
            return route.fulfill(status=200, body=json.dumps([PROJECT]), **json_ok)
        if path == f"/api/projects/{PID}/hold":
            if request.method == "POST":
                body = json.loads(request.post_data or "{}")
                sent.append(body)
                history.insert(0, {"at": "2026-10-08T12:00:00+00:00", "by": me,
                                   "action": body["action"],
                                   "reason": body["reason"]})  # fmt: skip
            return route.fulfill(status=200, body=state(), **json_ok)
        return route.fulfill(status=200, body="[]", **json_ok)

    page.route("**/api/**", handle)


def open_setup(page) -> None:
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    page.wait_for_function("PROJECTS && PROJECTS.size >= 1", timeout=15000)
    page.evaluate(f"openProject({PID!r}, 'setup')")
    page.wait_for_timeout(500)


def main() -> int:
    with serve(DOCS) as base, sync_playwright() as p:
        browser = p.chromium.launch()

        print("An owner, in the server-backed mode")
        page = browser.new_page()
        sent: list[dict] = []
        mock_api(page, sent)
        page.goto(base + "/app/index.html")
        open_setup(page)
        section = page.locator("#holdHost")
        check("the setup page has a hold section", section.count() == 1)
        check(
            "it says the project is not held",
            page.evaluate("t('hold.off')") in section.inner_text(),
            section.inner_text()[:200],
        )

        print("Placing a hold")
        page.click('[data-hold-action="place"]')
        page.wait_for_selector(".modal", timeout=5000)
        go = page.locator("[data-hold-go]")
        check("it asks for a reason and will not send without one", go.is_disabled())
        page.fill("#holdReason", "   ")
        check("whitespace is not a reason", go.is_disabled())
        page.fill("#holdReason", "Smith v. Hospital")
        go.click()
        page.wait_for_timeout(500)
        check(
            "it sends the action and the reason",
            sent == [{"action": "place", "reason": "Smith v. Hospital"}],
            str(sent),
        )
        text = section.inner_text()
        check(
            "and then says the project is held, with the reason in its history",
            page.evaluate("t('hold.on')") in text and "Smith v. Hospital" in text,
            text[:300],
        )
        check(
            "the button now lifts it",
            page.locator('[data-hold-action="lift"]').count() == 1,
        )

        print("Lifting it")
        page.click('[data-hold-action="lift"]')
        page.wait_for_selector(".modal", timeout=5000)
        page.fill("#holdReason", "Case settled")
        page.click("[data-hold-go]")
        page.wait_for_timeout(500)
        check(
            "it sends a lift with its reason",
            sent[-1] == {"action": "lift", "reason": "Case settled"},
            str(sent),
        )
        check(
            "and the page says it is no longer held",
            page.evaluate("t('hold.off')") in section.inner_text(),
        )
        page.close()

        print("Someone who is not an owner")
        page = browser.new_page()
        mock_api(page, [], me="w@hospital.example")
        page.goto(base + "/app/index.html")
        open_setup(page)
        check("sees no hold section", page.locator("#holdHost").count() == 0)
        page.close()

        print("The browser-only mode")
        page = browser.new_page()
        page.route("**/api/health", lambda r: r.fulfill(status=404, body=""))
        page.goto(base + "/app/index.html")
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("openProject([...PROJECTS.keys()][0], 'setup')")
        page.wait_for_timeout(300)
        check(
            "has no hold section, because nothing is ever disposed of there",
            page.locator("#holdHost").count() == 0,
        )
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("hold UI checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
