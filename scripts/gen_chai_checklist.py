#!/usr/bin/env python3
"""Generate docs/frameworks/chai-checklist.md from the app's own STAGES data.

The checklist lives in docs/app/index.html so the dashboard stays a single
self-contained file. Rather than maintain a second copy by hand in the docs,
this script reads it back out, which means the published checklist cannot
silently drift from the one the tool actually enforces.

Run via: pixi run gen-docs
"""

import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
OUT = ROOT / "docs" / "frameworks" / "chai-checklist.md"

PRINCIPLE_RE = re.compile(r'(\w):\{name:"(.*?)"\}')
# Stage 4 carries a trailing `metrics:true` after its items array, so the
# closing brace is not always adjacent to the array.
STAGE_RE = re.compile(
    r'\{id:"(s\d)",n:(\d),title:"(.*?)",blurb:"(.*?)",items:\[(.*?)\]'
    r"(?:\s*,\s*metrics:true)?\s*\}",
    re.S,
)
ITEM_RE = re.compile(r'\["(\w)","(.*?)"\]')


def main() -> int:
    html = APP.read_text(encoding="utf-8")

    principles = dict(
        PRINCIPLE_RE.findall(
            html[html.index("const PRINCIPLES") : html.index("const STAGES")]
        )
    )
    stages_src = html[html.index("const STAGES") : html.index("const GATES")]
    stages = STAGE_RE.findall(stages_src)

    if len(stages) != 6:
        print(f"error: expected 6 stages, found {len(stages)}", file=sys.stderr)
        return 1

    lines = [
        "# CHAI checklist",
        "",
        "The 41 criteria this tool tracks, in the order the dashboard presents",
        "them. Each is tagged with the CHAI principle it serves.",
        "",
        '!!! info "Generated file"',
        "",
        "    This page is generated from the app by `scripts/gen_chai_checklist.py`",
        "    (`pixi run gen-docs`), so it cannot drift from the checklist the tool",
        "    actually enforces. Edit the criteria in `docs/app/index.html`, not here.",
        "",
        "    These criteria are original summaries written for this project. They",
        "    are not the text of CHAI's Responsible AI Checklist — see",
        "    [Notice & license](../notice.md).",
        "",
        "## Principles",
        "",
        "| Tag | Principle |",
        "|---|---|",
    ]
    lines += [f"| **{k}** | {v} |" for k, v in principles.items()]

    total = 0
    for _sid, n, title, blurb, items_src in stages:
        items = ITEM_RE.findall(items_src)
        total += len(items)
        lines += [
            "",
            f"## Stage {n}: {title}",
            "",
            # Wrapped to the repo's 80-column prose style so the generated file
            # passes the same rumdl check as the hand-written pages.
            textwrap.fill(blurb, width=78),
            "",
            f"*{len(items)} criteria.*",
            "",
            "| | Criterion | Principle |",
            "|---|---|---|",
        ]
        for i, (p, text) in enumerate(items, 1):
            lines.append(f"| {n}.{i} | {text} | **{p}** |")

    lines += ["", "---", "", f"**{total} criteria in total.**", ""]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({total} criteria, {len(stages)} stages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
