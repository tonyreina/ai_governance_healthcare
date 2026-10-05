"""Summarize a project export from the CHAI governance review tool.

Usage:
    python examples/load_export.py my-project-chai-review.json

Needs only the standard library. If pandas is installed, also prints the open
gaps as a DataFrame.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "chai-review/2":
        raise ValueError(f"{path} is not a chai-review/2 project export")
    return data


def open_gaps(export: dict) -> list[dict]:
    """Checklist items that are not met, partial, or unanswered."""
    return [
        c for c in export["checklist"] if c["status"] in (None, "notmet", "partial")
    ]


def summarize(export: dict) -> str:
    meta = export["meta"]
    counts = Counter(c["status"] or "unanswered" for c in export["checklist"])
    lines = [
        f"{meta.get('solution') or 'Untitled AI solution'}",
        f"  status:      {export.get('status')}  ({export.get('phase')})",
        f"  next review: {export.get('next_review') or '-'}",
        f"  readiness:   {export['scores']['overall']}%  "
        + "  ".join(f"{k}={export['scores'][k]}%" for k in "UFSTP"),
        "  checklist:   " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
    ]
    for f in export.get("flags", []):
        lines.append(f"  [{f['sev']:>5}] {f['text']}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    export = load(argv[1])
    print(summarize(export))
    try:
        import pandas as pd
    except ImportError:
        return 0
    gaps = pd.DataFrame(open_gaps(export))
    if not gaps.empty:
        print("\nOpen gaps:")
        print(
            gaps[
                ["stage", "principle", "status", "owner", "due", "criterion"]
            ].to_string(index=False)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
