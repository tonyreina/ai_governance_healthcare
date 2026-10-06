#!/usr/bin/env python3
"""The changelog and the record fingerprint.

The property that matters most here is coalescing. edit() runs on every
keystroke, so a naive implementation writes one entry per character and buries
the record it was meant to document. Typing a sentence must produce one entry.

    pixi run test-changelog
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"
PHRASE = "the vendor confirmed this in writing"


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

        print("Fingerprint")
        for text, expected in [
            ("", hashlib.md5(b"").hexdigest()),
            ("abc", hashlib.md5(b"abc").hexdigest()),
            ("x" * 64, hashlib.md5(b"x" * 64).hexdigest()),
        ]:
            check(
                f"md5({text[:6] or '(empty)'!r}) matches hashlib",
                page.evaluate("s => md5(s)", text) == expected,
            )

        check(
            "key order does not change the hash",
            page.evaluate("contentHash({a:1,b:2}) === contentHash({b:2,a:1})"),
        )
        check(
            "volatile fields are excluded",
            page.evaluate(
                "contentHash({a:1}) === "
                "contentHash({a:1,updatedAt:'2026-01-01',updatedBy:'x'})"
            ),
        )
        check(
            "real changes move the hash",
            page.evaluate("contentHash({a:1}) !== contentHash({a:2})"),
        )

        print("\nCoalescing")
        pid = page.evaluate("[...PROJECTS.keys()][0]")
        page.evaluate(f"openProject({pid!r}, 's1')")
        page.wait_for_timeout(400)
        page.click('[data-toggle="s1-1"]')
        page.wait_for_timeout(300)

        before = page.evaluate("LOG.length")
        page.click('[data-bind="items.s1-1.evidence"]')
        page.keyboard.type(PHRASE, delay=15)
        page.wait_for_timeout(2500)
        added = page.evaluate("LOG.length") - before

        check(
            f"typing {len(PHRASE)} characters adds one entry, not one per key",
            added == 1,
            f"added {added}",
        )
        latest = page.evaluate("LOG[0]")
        check(
            "the entry records the whole edit",
            PHRASE in latest["text"] and "empty" in latest["text"],
            latest["text"][:90],
        )
        check(
            "the entry carries the structured change",
            latest.get("change", {}).get("path") == "items.s1-1.evidence",
        )
        check("the entry carries a fingerprint", bool(latest.get("hash")))

        print("\nReadability")
        check(
            "paths are described in the user's terms",
            "criterion" not in latest["text"].lower() or "s1-1" not in latest["text"],
        )
        page.evaluate("edit('gates.A.decision','Proceed with conditions')")
        page.wait_for_timeout(1500)
        check(
            "checkpoints are named, not pathed",
            "Checkpoint A" in page.evaluate("LOG[0].text"),
            page.evaluate("LOG[0].text")[:80],
        )

        page.evaluate("go('changelog')")
        page.wait_for_timeout(600)
        body = page.inner_text("#main")
        check("changelog view renders entries", PHRASE in body)
        check("it states what the hash does not prove", "not tampering" in body)

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
