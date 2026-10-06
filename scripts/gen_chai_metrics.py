#!/usr/bin/env python3
"""Extract CHAI's consensus Testing & Evaluation metrics into structured data.

CHAI publishes, per use case, a consensus-defined set of methods and metrics for
evaluating a health AI solution responsibly. Its own guidance is to consult them
when completing the Applied Model Card -- which is exactly the moment this tool
asks a user to record key metrics. Left as prose on another website, they do not
reach the person filling the form.

So this pulls them from CHAI's content repository into
``data/chai_te_metrics.json``, which feeds both the app's metric picker and the
published reference page.

Licensing: the source repository is CC BY 4.0, which permits reproduction with
attribution, so metric names and benchmarks are kept verbatim rather than
paraphrased. Attribution travels with the data file and appears on every surface
that renders it. Long prose descriptions are deliberately NOT copied: they would
bloat a single-file app, and sending the reader to CHAI for the full text is
both lighter and more honest.

    pixi run gen-chai-metrics
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DATA = ROOT / "data" / "chai_te_metrics.json"
OUT_JS = ROOT / "app" / "js" / "10-frameworks" / "10-chai" / "05-te-metrics.js"

REPO = "coalition-for-health-ai/responsible-ai-content"
CONTENT = "responsible-ai-content"

USE_CASES = {
    "Ambient-AI": "Ambient documentation",
    "agentic": "Agentic AI",
    "clinical-decision-support": "Clinical decision support",
    "clinical-trials": "Clinical trials",
    "electronic-health-record-information-retrieval": "EHR information retrieval",
    "general-health-advice-chatbot": "General health advice chatbot",
    "mental-health": "Mental health",
    "patient-discharge-summarization": "Discharge summarization",
    "prior-authorization-ai-supported-criteria-matching": "Prior authorization",
    "sepsis-risk-prediction": "Sepsis risk prediction",
}

# Rendered page paths are inconsistent upstream: most use "t&e-framework",
# two use "te". Recorded per use case so links do not 404.
DOC_BASE = "https://rai-content.chai.org/en/latest"

METRIC_RE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*$")
FIELD_RE = re.compile(r"^\s+-\s+([A-Z][^:]{2,60}?):\s*(.*)$")

# The tool groups metrics into three categories. CHAI names more principles than
# that, so they are folded in -- usability and efficacy sit with usefulness,
# and anything about bias or equity sits with fairness.
CATEGORY = {
    "usefulness": "Usefulness, usability & efficacy",
    "usability": "Usefulness, usability & efficacy",
    "efficacy": "Usefulness, usability & efficacy",
    "fairness": "Fairness & equity",
    "equity": "Fairness & equity",
    "bias": "Fairness & equity",
    "safety": "Safety & reliability",
    "reliability": "Safety & reliability",
    "transparency": "Safety & reliability",
    "security": "Safety & reliability",
    "privacy": "Safety & reliability",
}


def gh_file(use_case: str) -> str | None:
    for name in ("t&e-framework.rst", "te.rst"):
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{REPO}/contents/{CONTENT}/{use_case}/{name}",
                "-q",
                ".content",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            import base64

            return base64.b64decode(result.stdout.replace("\n", "")).decode("utf-8")
    return None


def categorize(principle: str, section: str) -> str:
    haystack = f"{principle} {section}".lower()
    for key, value in CATEGORY.items():
        if key in haystack:
            return value
    return "Usefulness, usability & efficacy"


def clean(text: str) -> str:
    """Strip reStructuredText link markup down to its visible text."""
    text = re.sub(r"`([^<`]+?)\s*<[^>]+>`__", r"\1", text)
    text = text.replace("``", "").replace("\\", "")
    return re.sub(r"\s+", " ", text).strip()


def parse(rst: str) -> list[dict]:
    metrics: list[dict] = []
    section = ""
    current: dict | None = None
    field: str | None = None

    for line in rst.split("\n"):
        # Section headings are underlined; track the most recent one as context.
        if re.match(r"^[~^=-]{4,}\s*$", line) and metrics is not None:
            pass
        if line and not line.startswith((" ", "-", "*")) and len(line) < 80:
            section = line.strip()

        m = METRIC_RE.match(line)
        if m:
            if current:
                metrics.append(current)
            current = {"name": clean(m.group(1)), "section": section}
            field = None
            continue

        if current is None:
            continue

        f = FIELD_RE.match(line)
        if f:
            field = f.group(1).strip().lower()
            current[field] = clean(f.group(2))
        elif field and line.strip() and line.startswith("    "):
            current[field] = (current.get(field, "") + " " + clean(line)).strip()

    if current:
        metrics.append(current)
    return metrics


def normalize(raw: list[dict], use_case: str) -> list[dict]:
    out = []
    seen = set()
    for item in raw:
        name = item.get("name", "")
        if not name or len(name) > 120 or name.lower() in seen:
            continue
        seen.add(name.lower())

        principle = item.get("responsible ai principle", "")
        stage = item.get("pre- or post-implementation (or both)", "")
        persona = item.get("persona (developer, implementer, or both)", "")
        benchmark = item.get("benchmark", "")
        if benchmark.lower().startswith("no specific"):
            benchmark = ""

        out.append(
            {
                "name": name,
                "cat": categorize(principle, item.get("section", "")),
                "principle": principle,
                # "Both" is the common case; recording it as "" keeps the data terse
                # without losing anything, since the UI treats blank as "both".
                "when": "" if stage.lower() == "both" else stage,
                "who": "" if persona.lower() == "both" else persona,
                "benchmark": benchmark,
                "description": item.get("description", ""),
                "intended_use": item.get("intended use", ""),
            }
        )
    return out


def main() -> int:
    data = {
        "_source": {
            "repo": f"https://github.com/{REPO}",
            "docs": DOC_BASE,
            "license": "CC BY 4.0",
            "copyright": "Copyright (c) 2025 Coalition for Health AI, Inc.",
            "note": (
                "Metric names and benchmarks are reproduced from CHAI's "
                "consensus Testing & Evaluation Frameworks under CC BY 4.0. "
                "Descriptions are not reproduced; follow the link for full text."
            ),
        },
        "use_cases": [],
    }

    total = 0
    for slug, label in USE_CASES.items():
        rst = gh_file(slug)
        if rst is None:
            print(f"warning: no T&E file for {slug}", file=sys.stderr)
            continue
        metrics = normalize(parse(rst), slug)
        doc_file = (
            "te"
            if slug in {"patient-discharge-summarization", "sepsis-risk-prediction"}
            else "t%26e-framework"
        )
        data["use_cases"].append(
            {
                "slug": slug,
                "label": label,
                "url": f"{DOC_BASE}/{slug}/{doc_file}.html",
                "metrics": metrics,
            }
        )
        total += len(metrics)
        print(f"  {len(metrics):3d}  {label}")

    if total < 50:
        print(
            f"error: only {total} metrics parsed; the upstream format probably changed",
            file=sys.stderr,
        )
        return 1

    OUT_DATA.write_text(
        json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # The app carries the full record -- description, intended use and
    # benchmark included -- so a reviewer choosing a metric can see what it
    # means and what good looks like without leaving the page. Empty fields are
    # dropped rather than serialized as "".
    compact = json.dumps(
        {
            u["slug"]: {
                "label": u["label"],
                "url": u["url"],
                "metrics": [{k: v for k, v in m.items() if v} for m in u["metrics"]],
            }
            for u in data["use_cases"]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    OUT_JS.write_text(
        "/* ============================================================\n"
        "   CHAI Testing & Evaluation metrics\n"
        "   GENERATED by scripts/gen_chai_metrics.py from CHAI's content\n"
        "   repository -- do not edit by hand.\n\n"
        "   CHAI's guidance is to consult the use-case T&E framework when\n"
        "   completing the Applied Model Card. This is that list, offered at\n"
        "   the point where the tool asks for key metrics.\n\n"
        "   Reproduced under CC BY 4.0.\n"
        "   Copyright (c) 2025 Coalition for Health AI, Inc.\n"
        "   ============================================================ */\n"
        f"const CHAI_TE = {compact};\n",
        encoding="utf-8",
    )
    print(f"\n{total} metrics across {len(data['use_cases'])} use cases")
    print(f"  {OUT_DATA.relative_to(ROOT)}")
    print(f"  {OUT_JS.relative_to(ROOT)} ({len(compact):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
