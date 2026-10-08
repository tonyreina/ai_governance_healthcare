#!/usr/bin/env python3
"""An export says which storage mode produced it (#93).

A filed PDF could not carry its own provenance: a reader could not tell a record that
was access-controlled and audited on the self-hosted server from one typed into a single
browser, and the three differ on what a sign-off means, on version snapshots and on
audit. So every export now states, in its own header or footer, the mode that produced
it, in the same words the live header uses (MODE_LABEL), so the two cannot drift.

Per mode and per format, in a real browser: the printable HTML (which is also what
the PDF prints), Markdown, JSON and the portfolio CSV. The Croissant record is built
from the JSON, so it is checked too. R-04: one mode's label is never another's. The data
scope is the same in every mode (R-49), so the text says where the record was kept,
never that a place is approved for any class of data.

    pixi run test-export-provenance
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
CROISSANT = ROOT / "examples" / "croissant_export.py"

failures: list[str] = []

MODES = ("LOCAL", "API", "ARTIFACT")


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def produce(page, mode: str) -> dict:
    return page.evaluate(
        """(m) => {
          MODE = Mode[m];
          return {
            label: MODE_LABEL[Mode[m]].text,
            html: exportHTML(),
            md: exportMD(),
            json: JSON.stringify(projectJSON(S)),
            csv: exportCSV(),
          };
        }""",
        mode,
    )


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1300, "height": 1000})
        page.set_default_timeout(6000)
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("openProject([...PROJECTS.keys()][0], 'report')")
        page.wait_for_timeout(300)

        made = {m: produce(page, m) for m in MODES}
        labels = {made[m]["label"] for m in MODES}
        check(
            "the three modes have three different labels", len(labels) == 3, str(labels)
        )

        for m in MODES:
            out = made[m]
            label = out["label"]
            print(f"{m}: {label}")
            check("the HTML report states the mode", label in out["html"])
            check("the Markdown report states the mode", label in out["md"])
            storage = json.loads(out["json"]).get("storage") or {}
            check(
                "the JSON export states the mode",
                storage.get("label") == label,
                str(storage),
            )
            check(
                "and a stable machine value for it",
                storage.get("mode") == m.lower(),
                str(storage),
            )
            check("the portfolio CSV states the mode", label in out["csv"])
            for other in MODES:
                if other == m:
                    continue
                other_label = made[other]["label"]
                check(
                    f"{m} never carries {other}'s label",
                    other_label not in out["html"] and other_label not in out["md"],
                )

        local = made["LOCAL"]
        check(
            "browser-only exports say sign-offs are self-asserted",
            "self-asserted" in local["html"] and "self-asserted" in local["md"],
        )
        check(
            "and the server's do not say that",
            "self-asserted" not in made["API"]["html"]
            and "self-asserted" not in made["API"]["md"],
        )
        for m in MODES:
            check(
                f"{m}: no claim that the place is approved for any data class",
                not any(
                    w in (made[m]["html"] + made[m]["md"]).lower()
                    for w in ("approved for", "hipaa-compliant", "phi-safe")
                ),
            )

        page.close()
        browser.close()

    print("The Croissant record")
    base = {
        "schema": "chai-review/2",
        "meta": {"solution": "Sepsis early warning", "org": "Mercy General"},
        "model_card": {"name": "Sepsis early warning", "summary": "Predicts sepsis."},
        "_state": {"updatedAt": "2026-01-01T00:00:00Z"},
    }

    def croissant(data: dict) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "export.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            done = subprocess.run(
                [sys.executable, str(CROISSANT), str(path)],
                capture_output=True,
                text=True,
            )
        assert done.returncode == 0, done.stderr[-400:]
        return json.loads(done.stdout)["description"]

    stated = croissant(
        {
            **base,
            "storage": {"mode": "local", "label": "This browser only", "note": "x"},
        }
    )
    check(
        "it carries where the source record was kept",
        "This browser only" in stated,
        stated,
    )
    check("an older export without the field still builds", bool(croissant(base)))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("export provenance checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
