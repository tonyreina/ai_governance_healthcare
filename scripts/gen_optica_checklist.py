#!/usr/bin/env python3
"""Generate docs/frameworks/optica-checklist.md from data/optica_items.json.

The paraphrases and the CHAI crosswalk live in one committed JSON file so the
published page is reproducible and reviewable, rather than hand-maintained prose
that drifts from the analysis behind it.

Run via: pixi run gen-docs
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "optica_items.json"
OUT = ROOT / "docs" / "frameworks" / "optica-checklist.md"

RELATION_LABEL = {
    "optica-only": "OPTICA only",
    "partial": "partial",
    "equivalent": "equivalent",
}


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    chapters = data["chapters"]
    total = sum(len(c["items"]) for c in chapters)

    if total != 77:
        print(f"error: expected 77 items, found {total}", file=sys.stderr)
        return 1

    src = data["source"]
    lines = [
        "# OPTICA checklist",
        "",
        "All 77 OPTICA items, with what each asks and how far the",
        "[CHAI criteria](chai-checklist.md) reach it.",
        "",
        '!!! warning "These are paraphrases, not the OPTICA checklist"',
        "",
        "    The OPTICA paper is copyrighted and marked *for personal use only*, so",
        "    its item text is **not** reproduced here. Every line below is an",
        "    original summary written for this project, describing what the item",
        "    asks for.",
        "",
        "    They are a navigation aid. Completing a real OPTICA review means",
        "    working from the paper, including Table S1 in its Supplementary",
        "    Appendix — the authors state the checklist should not be completed",
        "    without it. See [Notice & license](../notice.md).",
        "",
        "## How to read the CHAI column",
        "",
        "| Label | Meaning |",
        "|---|---|",
        "| **OPTICA only** | No CHAI criterion asks for any part of this |",
        "| **partial** | CHAI touches it but asks for materially less, or asks a different party |",
        "",
        "There are no *equivalent* rows. No OPTICA item fully discharges a CHAI",
        "criterion — see the [crosswalk](../crosswalk.md) for why that matters.",
        "",
        "**Who answers** is the other column that decides whether evidence can be",
        "shared: `adopter` means only the adopting organization can answer,",
        "`developer` means only the solution's vendor or builder can.",
        "",
    ]

    current_domain = None
    for chapter in chapters:
        if chapter["domain"] != current_domain:
            current_domain = chapter["domain"]
            lines += [
                f"## Domain {current_domain}: {data['domains'][current_domain]}",
                "",
            ]

        items = chapter["items"]
        lines += [f"### Chapter {chapter['number']}: {chapter['title']}", ""]
        if chapter.get("purpose"):
            lines += [textwrap.fill(f"*{chapter['purpose']}*", width=78), ""]

        lines += [
            f"*{len(items)} items.*",
            "",
            "| | What it asks | Who answers | CHAI |",
            "|---|---|---|---|",
        ]
        for item in items:
            chai = RELATION_LABEL.get(item["relation"], item["relation"] or "—")
            if item["chaiIds"]:
                chai = f"{chai} — {', '.join(f'`{c}`' for c in item['chaiIds'])}"
            text = item["paraphrase"].replace("|", "\\|")
            lines.append(
                f"| **{item['id']}** | {text} | {item['producer'] or '—'} | {chai} |"
            )
        lines.append("")

    lines += [
        "## Source",
        "",
        textwrap.fill(
            f"Dagan N, Devons-Sberro S, Paz Z, et al. *{src['title']}.* "
            f"{src['journal']} {src['year']};1(9). "
            f"[DOI: {src['doi']}](https://doi.org/{src['doi']})",
            width=78,
        ),
        "",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({total} items, {len(chapters)} chapters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
