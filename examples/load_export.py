"""Summarize a project export from the CHAI governance review tool.

Usage:
    python examples/load_export.py my-project-chai-review.json

Needs only the standard library. If pandas is installed, also prints the open
gaps as a DataFrame.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "chai-review/2":
        raise ValueError(f"{path} is not a chai-review/2 project export")
    return data


# Left out of the fingerprint at every depth: touched by every save, or the
# fingerprint's own container (the dashboard's CANON_SKIP, app/js/00-core/12-hash.js).
CANON_SKIP = {
    "updatedAt",
    "updatedBy",
    "cardUpdatedAt",
    "_state",
    "contentHash",
    "generated",
}


def _canonical(value):
    """Keys sorted at every level, volatile fields dropped. JavaScript sorts keys by
    UTF-16 code unit, which differs from Python's code-point order for characters
    outside the Basic Multilingual Plane, so sort by the UTF-16 bytes to match."""
    if isinstance(value, dict):
        return {
            k: _canonical(value[k])
            for k in sorted(value, key=lambda key: key.encode("utf-16-be"))
            if k not in CANON_SKIP
        }
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def fingerprint(export: dict) -> dict:
    """The MD5 and SHA-256 the dashboard computes over this record, recomputed from
    the file alone: the project (`_state` plus its id) as compact canonical JSON in
    UTF-8. Written from the rule, not from the dashboard's code."""
    record = dict(export["_state"])
    if export.get("project_id") is not None:
        record["id"] = export["project_id"]
    text = json.dumps(_canonical(record), ensure_ascii=False, separators=(",", ":"))
    data = text.encode("utf-8")
    return {
        "md5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def verify_fingerprint(export: dict) -> bool | None:
    """True if the export's fingerprint matches its record, False if it does not,
    None if the export carries none (an older one)."""
    claimed = export.get("fingerprint")
    if not claimed:
        return None
    got = fingerprint(export)
    return claimed.get("md5") == got["md5"] and claimed.get("sha256") == got["sha256"]


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
    verified = verify_fingerprint(export)
    if verified is None:
        lines.append("  fingerprint: none (an export from before they were added)")
    else:
        sha = export["fingerprint"]["sha256"]
        lines.append(
            f"  fingerprint: SHA-256 {sha[:16]}...  "
            + ("matches the record" if verified else "DOES NOT MATCH THE RECORD")
        )
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
