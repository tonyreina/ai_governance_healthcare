#!/usr/bin/env python3
"""Find every place one person's identifier is stored (#57).

A subject access request (GDPR Art. 15) asks for the personal data held about one
person. Here that identifier is in at least six places: who created or last changed a
project, the audit log, every frozen revision, the access lists inside them, the
deletion record, the read trail and the principals table. This turns finding them from
a half-day of hand-written SQL into a command.

    python3 scripts/subject_access.py ceo@hospital.org
    make subject-access WHO=ceo@hospital.org

It only reads, through the running database container, and reports where the
identifier appears and how many rows, not the contents: the privacy office decides
what is produced. A match in a jsonb column is a place to look, not a finding.

It does not erase anything. What can be erased, and what cannot, is in docs/privacy.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preflight import ENV_FILE, read_env

SQL = Path(__file__).resolve().parent / "subject_access.sql"


def query(psql: list[str], subject: str) -> dict:
    """Run the report through `psql` (a command prefix); parse its JSON row."""
    command = [
        *psql, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
        "-v", f"subject={subject}", "-f", "-",
    ]  # fmt: skip
    done = subprocess.run(
        command,
        input=SQL.read_text(encoding="utf-8"),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:] or "psql failed")
    return json.loads(done.stdout.strip())


def render(report: dict) -> str:
    lines = [f"subject-access: {report['subject']}"]
    principal = report.get("principal")
    if principal:
        lines.append(
            f"  principal: {principal['name'] or '(no name)'} <{principal['email']}>, "
            f"first seen {principal['first_seen']}, last seen {principal['last_seen']}"
        )
    if not report["locations"]:
        lines.append("  no match in any table.")
    for loc in report["locations"]:
        projects = ", ".join(loc["projects"][:8]) + (
            f" and {len(loc['projects']) - 8} more" if len(loc["projects"]) > 8 else ""
        )
        lines.append(
            f"  {loc['location']:<28} {loc['rows']:>6} row(s)"
            + (f"  in {projects}" if projects else "")
        )
    lines.append(
        "A match in a jsonb column (doc, entry, access, detail) is a place to look. "
        "This lists locations; it does not erase. See docs/privacy.md."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    as_json = "--json" in args
    positional = [a for a in args if not a.startswith("--")]
    if len(positional) != 1 or not positional[0].strip():
        print("usage: subject_access.py [--json] IDENTIFIER", file=sys.stderr)
        return 2
    env = read_env(ENV_FILE)
    psql = [
        "docker", "compose", "exec", "-T", "db", "psql",
        "-U", env.get("POSTGRES_USER", "chai"),
        "-d", env.get("POSTGRES_DB", "chai"),
    ]  # fmt: skip
    try:
        report = query(psql, positional[0].strip())
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"subject-access: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2) if as_json else render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
