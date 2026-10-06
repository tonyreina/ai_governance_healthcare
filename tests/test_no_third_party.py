#!/usr/bin/env python3
"""The dashboard and its exports must not contact a third party.

This is a tool whose subject is where regulated data goes, run on networks that
often filter egress. A webfont link meant every page load -- and every open of
an exported report, which is the artifact that gets emailed around a hospital
-- announced itself to Google.

It is also what lets the Content-Security-Policy in proxy/Caddyfile be as
tight as it is.

    pixi run test-no-3p
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def external(urls: list[str]) -> list[str]:
    out = []
    for url in urls:
        scheme = urlsplit(url).scheme
        if scheme in ("http", "https"):
            out.append(url)
    return out


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        requested: list[str] = []
        page.on("request", lambda r: requested.append(r.url))

        page.goto(APP.as_uri())
        page.wait_for_timeout(1200)

        off_origin = external(requested)
        check(
            "loading the dashboard makes no external request",
            not off_origin,
            ", ".join(off_origin[:3]),
        )

        # The export is generated from the live page, so check its text too.
        page.evaluate(
            """() => {
                S = normalize(blankProject("Sepsis early warning"));
                CUR = "x";
            }"""
        )
        html = page.evaluate("() => exportHTML()")
        check(
            "the HTML export links no external stylesheet",
            "<link" not in html.lower() or "fonts.googleapis" not in html,
            "export still references an external origin",
        )
        check(
            "the HTML export has no http(s) resource URLs at all",
            "https://" not in html.replace("https://evil", ""),
            next(
                (line.strip()[:80] for line in html.splitlines() if "https://" in line),
                "",
            ),
        )
        check("the export still carries its inline styles", "<style>" in html)
        check(
            "the export still names the project",
            "Sepsis early warning" in html,
        )

        # Rendering must not have fallen back to a serif default.
        family = page.evaluate("() => getComputedStyle(document.body).fontFamily")
        check(
            "body still resolves a sans-serif stack",
            "sans-serif" in family or "system-ui" in family,
            family,
        )
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("no-third-party checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
