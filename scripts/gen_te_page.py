#!/usr/bin/env python3
"""Generate docs/frameworks/chai-metrics.md from data/chai_te_metrics.json.

Publishes CHAI's consensus Testing & Evaluation metrics as a browsable
reference, so the same list the app offers at stage 4 is readable without
opening the app.

Run via: pixi run gen-docs
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "chai_te_metrics.json"
OUT = ROOT / "docs" / "frameworks" / "chai-metrics.md"


def cell(text: str, limit: int = 400) -> str:
    text = (text or "").replace("|", "\\|").replace("\n", " ").strip()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text or "—"


def main() -> int:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    src = data["_source"]
    use_cases = data["use_cases"]
    total = sum(len(u["metrics"]) for u in use_cases)
    if total < 50:
        print(
            f"error: only {total} metrics; regenerate the data first", file=sys.stderr
        )
        return 1

    lines = [
        "# CHAI metrics",
        "",
        textwrap.fill(
            f"CHAI publishes a consensus set of methods and metrics for each use "
            f"case, to be consulted when completing the Applied Model Card. All "
            f"{total} of them are reproduced here, and the same list is offered "
            f"inside the tool at stage 4 when you record key metrics.",
            width=78,
        ),
        "",
        '!!! info "Reproduced from CHAI under CC BY 4.0"',
        "",
        f"    {src['copyright']}, from",
        f"    [responsible-ai-content]({src['repo']}), licensed CC BY 4.0.",
        "",
        "    Benchmarks and descriptions are CHAI's own words. Where a metric's",
        "    category differs from CHAI's principle name, it is because this tool",
        "    groups metrics into three categories and CHAI names more; the",
        "    original principle is listed alongside.",
        "",
        "## Use cases",
        "",
        "| Use case | Metrics | CHAI's framework |",
        "|---|---:|---|",
    ]
    for u in use_cases:
        anchor = u["label"].lower().replace(" ", "-").replace("&", "")
        lines.append(
            f"| [{u['label']}](#{anchor}) | {len(u['metrics'])} "
            f"| [T&E framework]({u['url']}) |"
        )

    for u in use_cases:
        lines += [
            "",
            f"## {u['label']}",
            "",
            textwrap.fill(
                f"{len(u['metrics'])} methods and metrics, with supporting "
                f"literature and the full text of each entry in",
                width=78,
            ),
            f"[CHAI's {u['label']} T&E framework]({u['url']}).",
            "",
            "| Metric | Category | CHAI principle | When | Who | Benchmark |",
            "|---|---|---|---|---|---|",
        ]
        for m in u["metrics"]:
            lines.append(
                f"| **{cell(m['name'], 120)}** | {cell(m['cat'], 40)} "
                f"| {cell(m.get('principle', ''), 60)} "
                f"| {cell(m.get('when') or 'Both', 30)} "
                f"| {cell(m.get('who') or 'Both', 30)} "
                f"| {cell(m.get('benchmark', ''), 300)} |"
            )

    lines += [
        "",
        "---",
        "",
        f"**{total} metrics across {len(use_cases)} use cases.**",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"wrote {OUT.relative_to(ROOT)} ({total} metrics, {len(use_cases)} use cases)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
