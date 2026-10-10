#!/usr/bin/env python3
"""Watch CHAI's published content for changes and alert the developer.

This project paraphrases CHAI's lifecycle, mirrors the Applied Model Card's
field names, and crosswalks all of it against OPTICA. When CHAI changes its
published material, those derivations can silently fall out of date -- and a
governance tool that quietly describes last year's framework is worse than one
that admits it is stale.

So this compares the upstream state against a committed snapshot and, when they
differ, opens or updates a GitHub issue naming exactly what moved.

What it watches, and why only this:

* ``coalition-for-health-ai/responsible-ai-content`` -- the only CHAI material
  published in a form that can be watched mechanically. It is CC BY 4.0, so it
  can also be quoted here with attribution.
* Per use case, the Testing & Evaluation framework file, so a change can be
  attributed to a use case rather than reported as "something changed".

The Assurance Standards Guide and the Applied Model Card template are PDFs
behind a CDN with no version feed. They are listed in the issue as things a
human still has to check; pretending otherwise would be worse than saying so.

    pixi run check-chai            # compare, print, exit 1 if changed
    pixi run check-chai -- --write # update the snapshot
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "chai-upstream.json"

REPO = "coalition-for-health-ai/responsible-ai-content"
CONTENT_DIR = "responsible-ai-content"

# Use cases are listed explicitly rather than discovered, so a use case
# DISAPPEARING is a reported change rather than a silently shorter list.
USE_CASES = [
    "Ambient-AI",
    "agentic",
    "clinical-decision-support",
    "clinical-trials",
    "electronic-health-record-information-retrieval",
    "general-health-advice-chatbot",
    "mental-health",
    "patient-discharge-summarization",
    "prior-authorization-ai-supported-criteria-matching",
    "sepsis-risk-prediction",
]


def gh(path: str) -> Any:
    """Call the GitHub API via the gh CLI, which handles auth in CI and locally."""
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {result.stderr.strip()[:200]}")
    return json.loads(result.stdout)


def fetch_upstream() -> dict[str, Any]:
    head = gh(f"repos/{REPO}/commits?per_page=1")[0]
    state: dict[str, Any] = {
        "repo": REPO,
        "head_sha": head["sha"],
        "head_date": head["commit"]["author"]["date"],
        "head_message": head["commit"]["message"].split("\n")[0][:200],
        "use_cases": {},
    }

    for use_case in USE_CASES:
        try:
            entries = gh(f"repos/{REPO}/contents/{CONTENT_DIR}/{use_case}")
        except RuntimeError:
            state["use_cases"][use_case] = {"missing": True}
            continue
        # The T&E file is named inconsistently upstream: most use
        # "t&e-framework.rst", two use "te.rst". Match on either.
        files = {
            e["name"]: e.get("sha")
            for e in entries
            if e["type"] == "file"
            and ("framework" in e["name"] or e["name"] == "te.rst")
        }
        state["use_cases"][use_case] = {"files": files} if files else {"missing": True}

    return state


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    changes: list[str] = []

    if not old:
        return ["No snapshot recorded yet; this run establishes the baseline."]

    if old.get("head_sha") != new.get("head_sha"):
        changes.append(
            f"New commits on `{REPO}`.\n"
            f"  was `{str(old.get('head_sha'))[:8]}` ({old.get('head_date')})\n"
            f"  now `{str(new.get('head_sha'))[:8]}` ({new.get('head_date')})\n"
            f"  latest: {new.get('head_message')}"
        )

    old_cases = old.get("use_cases", {})
    new_cases = new.get("use_cases", {})

    for use_case in sorted(set(old_cases) | set(new_cases)):
        before = old_cases.get(use_case, {})
        after = new_cases.get(use_case, {})

        if use_case not in old_cases:
            changes.append(f"New use case published: **{use_case}**")
            continue
        if use_case not in new_cases:
            changes.append(f"Use case no longer listed: **{use_case}**")
            continue
        if after.get("missing") and not before.get("missing"):
            changes.append(f"T&E framework disappeared for **{use_case}**")
            continue
        if before.get("missing") and not after.get("missing"):
            changes.append(f"T&E framework now published for **{use_case}**")
            continue

        before_files = before.get("files", {})
        after_files = after.get("files", {})
        for name in sorted(set(before_files) | set(after_files)):
            if name not in before_files:
                changes.append(f"**{use_case}**: new file `{name}`")
            elif name not in after_files:
                changes.append(f"**{use_case}**: `{name}` removed")
            elif before_files[name] != after_files[name]:
                changes.append(f"**{use_case}**: `{name}` changed")

    return changes


def issue_body(changes: list[str], new: dict[str, Any]) -> str:
    bullets = "\n".join(f"- {c}" for c in changes)
    return f"""CHAI's published content has changed since this project last
recorded it.

## What changed

{bullets}

[Compare on GitHub](https://github.com/{REPO}/commits/main)

## What to check here

This project derives several things from CHAI, and none of them update
themselves:

- [ ] `app/frameworks/chai/framework.json` — the 41 paraphrased criteria and
      the six stages. Until the engine reads it (#168), the app's own copy in
      `app/js/10-frameworks/10-chai/00-definition.js` must change with it
- [ ] `app/frameworks/optica/framework.json` — the OPTICA crosswalk cites CHAI
      criteria by canonical id, so a renumbering breaks it (and, until #168's
      engine, the app's copy in `app/js/10-frameworks/20-optica/00-definition.js`)
- [ ] `docs/crosswalk.md` — coverage counts are stated as facts and will be
      wrong if CHAI's criteria changed
- [ ] `docs/frameworks/chai.md` — the use case list and the T&E description
- [ ] `NOTICE.md` and `docs/notice.md` — attribution and license terms

After changing any of them, run `pixi run gen-docs` so the generated pages and
the dashboard are rebuilt, and `pixi run test-framework-docs`, which fails if the
app's copy and the definitions disagree.

## Not covered by this check

The Assurance Standards Guide and the Applied Model Card template are PDFs with
no machine-readable version feed, so they are **not** watched. Check them by
hand when this fires:

- <https://chai.org>
- The model card's license was last verified as CC BY-ND 4.0.

---

Snapshot now at `{str(new.get("head_sha"))[:8]}`. This issue was opened by
`.github/workflows/chai-updates.yml`; it updates in place rather than opening
a new one each week.
"""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="update the snapshot file")
    parser.add_argument(
        "--body", type=Path, help="write the issue body here if changed"
    )
    args = parser.parse_args(argv)

    old = json.loads(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else {}

    try:
        new = fetch_upstream()
    except Exception as exc:
        print(f"error: could not read upstream: {exc}", file=sys.stderr)
        return 2

    changes = diff(old, new)

    if args.write:
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(
            json.dumps(new, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"snapshot written: {SNAPSHOT.relative_to(ROOT)}")

    if not changes:
        print(f"no change; CHAI content still at {new['head_sha'][:8]}")
        return 0

    print(f"{len(changes)} change(s) upstream:")
    for change in changes:
        print("  " + change.replace("\n", "\n  "))

    if args.body:
        args.body.write_text(issue_body(changes, new), encoding="utf-8")
        print(f"issue body written: {args.body}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
