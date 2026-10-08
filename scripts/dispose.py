#!/usr/bin/env python3
"""Dispose of records past their retention period (#57, R-54, R-56).

    dispose.py                    # report what is due; changes nothing
    dispose.py --apply --by NAME  # dispose of it, recorded as run by NAME

The rules are in the database (server/migrations/008_retention.sql), so this only asks
it. `retention_due()` lists the projects past their period: a retired project whose
last change or retirement date is longer ago than the policy's `record_years`, or the
history of a deleted one. `read_trail_due()` counts the read-trail rows older than
`read_trail_years`, and `principals_due()` the people not seen for that long whom no
retained record names. A project under a litigation hold is listed and kept.

`--apply` calls `dispose_due()`, which in one transaction deletes each due project's
live record (leaving a tombstone), purges its revisions (leaving who, when and the
hash), deletes the due read-trail rows and principals, and writes a `disposal_run` row
naming NAME.
It must run as the database owner; the API's role cannot.

Prints names and dates, never content. It runs on the host's Python, so it keeps to
what 3.10 has.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from purge_ledger import default_psql, run_psql

REPORT_SQL = """
SELECT json_build_object(
  'policy', (SELECT json_build_object('record_years', record_years,
                                      'read_trail_years', read_trail_years,
                                      'changed_at', changed_at,
                                      'changed_by', changed_by)
               FROM retention_policy),
  'projects', coalesce((SELECT json_agg(d) FROM retention_due() d), '[]'::json),
  'read_trail', (SELECT row_to_json(r) FROM read_trail_due() r),
  'principals', (SELECT count(*) FROM principals_due()))::text;
"""

APPLY_SQL = "SELECT row_to_json(r)::text FROM dispose_due({by}) r;"


def quote(value: str) -> str:
    """A SQL string literal, dollar-quoted so nothing in it can end it."""
    tag = "$by$"
    if tag in value:
        raise ValueError("--by may not contain $by$")
    return f"{tag}{value}{tag}"


def day(value: str | None) -> str:
    return (value or "")[:10]


def render(report: dict[str, Any]) -> str:
    policy = report["policy"]
    trail = report["read_trail"]
    projects = report["projects"]
    lines = [
        f"Retention policy: a retired project's record for {policy['record_years']} "
        f"year(s) after retirement; the read trail for {policy['read_trail_years']} "
        f"year(s). Set {day(policy['changed_at'])} by {policy['changed_by']}.",
        "",
    ]
    due = [p for p in projects if not p["held"]]
    held = [p for p in projects if p["held"]]
    if not projects:
        lines.append("No project is past its retention period.")
    for title, group in (("Due for disposal", due), ("Kept: litigation hold", held)):
        if not group:
            continue
        lines.append(f"{title} ({len(group)}):")
        lines += [
            f"  {p['project_id']}  {p['kind']} since {day(p['clock_start'])}, "
            f"due {day(p['due'])}  [{p['incarnation']}]"
            for p in group
        ]
    lines += [
        "",
        f"Read trail: {trail['events']} row(s) older than "
        f"{day(trail['cutoff'])} are due; {trail['held']} more are kept under a hold.",
        f"Staff names and emails: {report['principals']} person(s) not seen since "
        f"{day(trail['cutoff'])} and named by no retained record are due.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    top = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    top.add_argument(
        "--psql",
        type=shlex.split,
        default=None,
        help="the psql command to run (default: docker compose exec -T db psql ...)",
    )
    top.add_argument("--apply", action="store_true", help="dispose of what is due")
    top.add_argument("--by", default="", help="who is running it (required to apply)")
    args = top.parse_args(argv)
    psql = args.psql or default_psql()
    if args.apply and not args.by.strip():
        print(
            "dispose: --apply needs --by NAME, the person running it", file=sys.stderr
        )
        return 2
    try:
        report = json.loads(run_psql(psql, REPORT_SQL))
        print(render(report))
        if not args.apply:
            print("\nNothing was changed. Run with --apply to dispose of what is due.")
            return 0
        run = json.loads(run_psql(psql, APPLY_SQL.format(by=quote(args.by.strip()))))
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"dispose: {exc}", file=sys.stderr)
        return 1
    print(
        f"\nDisposed of {run['projects']} project(s) ({run['revisions']} revision(s)), "
        f"{run['read_events']} read-trail row(s) and {run['principals']} person(s)' "
        f"name and email. Recorded as disposal run {run['id']}, by {run['run_by']}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
