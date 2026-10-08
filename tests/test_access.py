#!/usr/bin/env python3
"""Per-project roles and the type-to-confirm delete dialog.

Covers the properties that matter: owners alone can delete or archive, a
reader cannot edit, legacy projects without an access list stay usable, the
last owner cannot be removed, and deletion requires the project's name typed
exactly.

    pixi run test-access
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
        if not ok:
            failures.append(name)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)

        print("Roles")
        # Without an identity nothing can be enforced, and the tool must say so
        # rather than imply a control it does not have.
        check(
            "no identity -> roles not enforced",
            page.evaluate("identityKnown() === false"),
        )
        check(
            "no identity -> everything permitted",
            page.evaluate(
                "canWrite({access:{owners:['someone'],writers:[],readers:[]}}) === true"
            ),
        )

        page.evaluate("ME.id = 'ann@hospital.example'")

        owned = "{access:{owners:['ann@hospital.example'],writers:[],readers:[]}}"
        wrote = (
            "{access:{owners:['bob@x'],writers:['ann@hospital.example'],readers:[]}}"
        )
        read = "{access:{owners:['bob@x'],writers:[],readers:['ann@hospital.example']}}"
        none = "{access:{owners:['bob@x'],writers:[],readers:[]}}"
        legacy = "{access:{owners:[],writers:[],readers:[]}}"

        check("owner can own", page.evaluate(f"canOwn({owned})"))
        check("writer can write", page.evaluate(f"canWrite({wrote})"))
        check("writer cannot own", page.evaluate(f"canOwn({wrote}) === false"))
        check("reader can read", page.evaluate(f"canRead({read})"))
        check("reader cannot write", page.evaluate(f"canWrite({read}) === false"))
        check(
            "unlisted user has no access", page.evaluate(f"canRead({none}) === false")
        )
        check("legacy project stays open", page.evaluate(f"canOwn({legacy})"))
        check(
            "most powerful role wins",
            page.evaluate(
                "roleOf({access:{owners:['ann@hospital.example'],"
                "writers:['ann@hospital.example'],readers:[]}}) === 'owner'"
            ),
        )

        print("\nGuards")
        check(
            "last owner cannot be removed",
            page.evaluate(f"wouldOrphan({owned}, 'ann@hospital.example', '')"),
        )
        check(
            "owner can be demoted when another exists",
            page.evaluate(
                "wouldOrphan({access:{owners:['a','b'],writers:[],readers:[]}},"
                "'a','') === false"
            ),
        )
        check(
            "granting one role clears the others",
            page.evaluate(
                "JSON.stringify(accessPatch("
                "{access:{owners:[],writers:['x'],readers:['x']}},'x','owner')) "
                "=== JSON.stringify({owners:['x'],writers:[],readers:[]})"
            ),
        )

        print("\nDelete dialog")
        page.evaluate("ME.id = null")  # unrestricted, so the button is reachable
        pid = page.evaluate("[...PROJECTS.keys()][0]")
        page.evaluate(f"openProject({pid!r}, 'setup')")
        page.wait_for_timeout(400)
        name = page.evaluate("S.meta.solution")

        page.click('[data-act="delete"]')
        page.wait_for_timeout(300)
        check("dialog opens", page.locator(".modal").count() == 1)
        check("delete starts disabled", page.locator("[data-del-go]").is_disabled())
        check("dialog names the project", name in page.inner_text(".modal"))
        check(
            "offers archiving instead", page.locator("[data-del-archive]").count() == 1
        )

        page.fill("#delName", name[:-2])
        page.wait_for_timeout(200)
        check("a near-miss stays disabled", page.locator("[data-del-go]").is_disabled())

        page.fill("#delName", name)
        page.wait_for_timeout(200)
        check(
            "exact name enables delete", not page.locator("[data-del-go]").is_disabled()
        )

        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        check(
            "Escape closes without deleting",
            page.locator(".modal").count() == 0
            and page.evaluate("PROJECTS.size") >= 10,
        )

        page.click('[data-act="delete"]')
        page.wait_for_timeout(300)
        before = page.evaluate("PROJECTS.size")
        page.fill("#delName", name)
        page.wait_for_timeout(200)
        page.click("[data-del-go]")
        page.wait_for_timeout(900)
        check(
            "typing the name deletes",
            page.evaluate("PROJECTS.size") == before - 1,
            f"{page.evaluate('PROJECTS.size')} vs {before - 1}",
        )

        print("\nSample top-up")
        # The samples button used to exist only on the empty state, so anyone
        # who loaded them once could never get the ones added later.
        page.evaluate("goHome()")
        page.wait_for_timeout(400)
        check(
            "samples button is on the dashboard, not just the empty state",
            page.locator('[data-act="samples"]').is_visible(),
        )
        page.locator('[data-act="samples"]').click()
        page.wait_for_timeout(2500)
        check(
            "top-up restores every sample",
            page.evaluate("PROJECTS.size") == page.evaluate("SAMPLES.length"),
            f"{page.evaluate('PROJECTS.size')} vs {page.evaluate('SAMPLES.length')}",
        )
        check(
            "button re-enables after use",
            not page.locator('[data-act="samples"]').is_disabled(),
        )
        again = page.evaluate("PROJECTS.size")
        page.locator('[data-act="samples"]').click()
        page.wait_for_timeout(1500)
        check(
            "pressing again adds no duplicates", page.evaluate("PROJECTS.size") == again
        )

        print("A sole owner is warned (#42)")
        pid = page.evaluate("[...PROJECTS.keys()][0]")
        page.evaluate(f"openProject({pid!r}, 'setup')")
        page.wait_for_timeout(300)

        def access_html(owners: str, me: str = "ann@hospital.example") -> str:
            page.evaluate(
                f"ME.id = {me!r}; "
                f"S.access = {{owners: {owners}, writers: [], readers: []}}"
            )
            return " ".join(page.evaluate("accessHTML()").split())

        warned = access_html("['ann@hospital.example']")
        check(
            "the only owner is told nobody can reach the record if they leave",
            "only owner" in warned and "second owner" in warned,
            warned[:200],
        )
        check(
            "and the warning says why it matters",
            "disabled" in warned and "unreachable" in warned.lower(),
        )
        check(
            "two owners: no warning",
            "only owner" not in access_html("['ann@hospital.example','bob@x']"),
        )
        check(
            "a writer is not nagged about something only an owner can fix",
            "only owner" not in access_html("['bob@x']"),
        )
        check(
            "an unclaimed project has its own message, not this one",
            "only owner" not in access_html("[]"),
        )

        check("no page errors", not errors, "; ".join(errors[:2]))
        browser.close()

    print()
    if failures:
        print(
            f"{len(failures)} check(s) failed: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
