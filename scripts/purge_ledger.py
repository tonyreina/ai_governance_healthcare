#!/usr/bin/env python3
"""Put purges back after a restore (#116, #57).

A purge destroys the content of a project's revisions and redacts its audit log, for
example to remove a value entered by mistake. A dump taken before the purge still holds
that content, so restoring it silently undid the purge. This keeps a ledger of purges
outside the dump and re-applies it:

    purge_ledger.py capture --out LEDGER         # the purges in the live database
    purge_ledger.py from-log LOG... --out LEDGER # the purges in the security log
    purge_ledger.py reapply LEDGER...            # re-apply them to the database

`make restore` runs `capture` before it overwrites the database and `reapply` after, so
an ordinary restore keeps every purge the live database had. When the live database is
gone, the security log still has each purge (`versions.purged`, with `incarnation`,
`purged_at`, `through_rev` and `through_seq`), and `from-log` rebuilds the ledger from
it.

A ledger holds no content: which project, which incarnation, when, by whom, and the last
revision and audit entry the purge reached. Re-applying is the same change the purge
made (the database's own triggers allow exactly that and nothing else), with the
original time and person, and it writes a system entry in each project's audit log
saying it was re-applied. Running it twice changes nothing the second time.

It runs on the host's Python, so it keeps to what 3.10 has.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preflight import ENV_FILE, read_env

LEDGER_VERSION = 1
FIELDS = (
    "project",
    "incarnation",
    "purged_at",
    "purged_by",
    "through_rev",
    "through_seq",
)
# SecurityEvent.VERSIONS_PURGED as it appears in the log. The server's enum needs
# Python 3.11; this runs on the host's. tests/test_purge_ledger.py pins the two.
PURGE_EVENT = "versions.purged"

CAPTURE_SQL = """
SELECT json_build_object(
         'project', coalesce(v.project_id, l.project_id),
         'incarnation', v.incarnation,
         'purged_at', coalesce(v.purged_at, l.purged_at),
         'purged_by', coalesce(v.purged_by, l.purged_by),
         'through_rev', v.through_rev,
         'through_seq', l.through_seq)::text
  FROM (SELECT project_id, incarnation, purged_at, min(purged_by) AS purged_by,
               max(rev) AS through_rev
          FROM project_version WHERE purged_at IS NOT NULL
         GROUP BY project_id, incarnation, purged_at) v
  FULL JOIN
       (SELECT project_id, purged_at, min(purged_by) AS purged_by,
               max(seq) AS through_seq
          FROM project_log WHERE purged_at IS NOT NULL
         GROUP BY project_id, purged_at) l
    ON v.project_id = l.project_id AND v.purged_at = l.purged_at
 ORDER BY 1;
"""

# Applied in one transaction. Each revision and entry is purged by the EARLIEST ledger
# entry that reaches it, so the time and person recorded are the original ones. A row
# written after a purge was never part of it, whatever its number: a restored sequence
# can hand out a number the purge once covered.
REAPPLY_SQL = """
BEGIN;
CREATE TEMP TABLE ledger ON COMMIT DROP AS
SELECT * FROM jsonb_to_recordset({literal}::jsonb)
    AS l(project text, incarnation uuid, purged_at timestamptz, purged_by text,
         through_rev integer, through_seq bigint);
CREATE TEMP TABLE done (project text, purged_at timestamptz, revisions bigint,
                        entries bigint) ON COMMIT DROP;
WITH pick AS (
    SELECT DISTINCT ON (v.project_id, v.rev) v.project_id, v.rev, l.purged_at,
           l.purged_by
      FROM project_version v
      JOIN ledger l ON l.project = v.project_id AND l.incarnation = v.incarnation
                   AND v.rev <= l.through_rev AND v.changed_at <= l.purged_at
     WHERE v.purged_at IS NULL
     ORDER BY v.project_id, v.rev, l.purged_at
), changed AS (
    UPDATE project_version v
       SET doc = '{{}}'::jsonb, purged_at = p.purged_at, purged_by = p.purged_by
      FROM pick p
     WHERE v.project_id = p.project_id AND v.rev = p.rev
 RETURNING v.project_id, v.purged_at
)
INSERT INTO done SELECT project_id, purged_at, count(*), 0 FROM changed
 GROUP BY project_id, purged_at;
WITH pick AS (
    SELECT DISTINCT ON (x.seq) x.seq, l.purged_at, l.purged_by
      FROM project_log x
      JOIN ledger l ON l.project = x.project_id AND x.seq <= l.through_seq
                   AND x.at <= l.purged_at
     WHERE x.purged_at IS NULL AND NOT x.is_system
     ORDER BY x.seq, l.purged_at
), changed AS (
    UPDATE project_log x
       SET entry = project_log_redacted(x.entry), purged_at = p.purged_at,
           purged_by = p.purged_by
      FROM pick p
     WHERE x.seq = p.seq
 RETURNING x.project_id, x.purged_at
)
INSERT INTO done SELECT project_id, purged_at, 0, count(*) FROM changed
 GROUP BY project_id, purged_at;
INSERT INTO project_log (project_id, at, by_id, entry, is_system)
SELECT d.project, now(), NULL,
       jsonb_build_object(
           'at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
           'event', 'purge.reapplied',
           'text', format(
               'Re-applied after a restore: the purge made %s by %s. The content of '
               '%s revision(s) and %s audit-log entries, which the restored backup '
               'still held, was destroyed again.',
               to_char(d.purged_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI "UTC"'),
               coalesce(l.purged_by, 'someone'), d.revisions, d.entries)),
       true
  FROM (SELECT project, purged_at, sum(revisions) AS revisions,
               sum(entries) AS entries
          FROM done GROUP BY project, purged_at) d
  JOIN (SELECT DISTINCT ON (project, purged_at) project, purged_at, purged_by
          FROM ledger ORDER BY project, purged_at) l
    ON l.project = d.project AND l.purged_at = d.purged_at
 WHERE EXISTS (SELECT 1 FROM projects WHERE id = d.project);
SELECT json_build_object(
         'revisions', coalesce(sum(revisions), 0),
         'entries', coalesce(sum(entries), 0),
         'projects', count(DISTINCT project))::text
  FROM done;
COMMIT;
"""


def default_psql() -> list[str]:
    env = read_env(ENV_FILE)
    return [
        "docker", "compose", "exec", "-T", "db", "psql",
        "-U", env.get("POSTGRES_USER", "chai"),
        "-d", env.get("POSTGRES_DB", "chai"),
    ]  # fmt: skip


def run_psql(psql: list[str], sql: str) -> str:
    command = [*psql, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"]
    done = subprocess.run(
        command, input=sql, capture_output=True, text=True, timeout=600
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:] or "psql failed")
    return done.stdout


def normalize(entry: dict[str, Any]) -> dict[str, Any] | None:
    """One purge, with exactly the ledger's fields, or None if it cannot be applied."""
    out = {key: entry.get(key) for key in FIELDS}
    if not out["project"] or not out["purged_at"]:
        return None
    if out["through_rev"] is None and out["through_seq"] is None:
        return None
    if out["through_rev"] is not None and not out["incarnation"]:
        return None
    return out


def merge(*ledgers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The union, one entry per purge (project and moment), oldest first."""
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for ledger in ledgers:
        for entry in ledger:
            clean = normalize(entry)
            if clean is not None:
                seen.setdefault((clean["project"], clean["purged_at"]), clean)
    return sorted(seen.values(), key=lambda e: (e["purged_at"], e["project"]))


def from_capture(output: str) -> list[dict[str, Any]]:
    return merge([json.loads(line) for line in output.splitlines() if line.strip()])


def from_log_lines(lines: list[str]) -> tuple[list[dict[str, Any]], int]:
    """Purges in a JSON security log, and how many purge events were too old to use.

    A line may carry a prefix (`docker compose logs` writes `api-1  | {...}`); the JSON
    object is everything from the first brace.
    """
    found, unusable = [], 0
    for line in lines:
        start = line.find("{")
        if start < 0:
            continue
        try:
            record = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("event") != PURGE_EVENT:
            continue
        entry = {
            "project": record.get("project"),
            "incarnation": record.get("incarnation"),
            "purged_at": record.get("purged_at"),
            "purged_by": record.get("actor"),
            "through_rev": record.get("through_rev"),
            "through_seq": record.get("through_seq"),
        }
        if normalize(entry) is None:
            if record.get("revisions") or record.get("log_entries"):
                unusable += 1
            continue
        found.append(entry)
    return merge(found), unusable


def dollar_literal(text: str) -> str:
    """`text` as a PostgreSQL dollar-quoted literal whose tag cannot occur in it."""
    while True:
        tag = f"$ledger_{secrets.token_hex(8)}$"
        if tag not in text:
            return f"{tag}{text}{tag}"


def reapply_sql(ledger: list[dict[str, Any]]) -> str:
    return REAPPLY_SQL.format(literal=dollar_literal(json.dumps(ledger)))


def write_ledger(path: Path, ledger: list[dict[str, Any]], source: str) -> None:
    """Mode 600: it names who purged what, so it is staff personal data."""
    data = json.dumps(
        {"version": LEDGER_VERSION, "source": source, "purges": ledger}, indent=2
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(data + "\n")


def read_ledger(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != LEDGER_VERSION:
        raise ValueError(f"{path}: not a version {LEDGER_VERSION} purge ledger")
    return list(data.get("purges") or [])


def cmd_capture(args: argparse.Namespace) -> int:
    ledger = from_capture(run_psql(args.psql, CAPTURE_SQL))
    write_ledger(args.out, ledger, "live database")
    print(f"purge-ledger: {len(ledger)} purge(s) in the live database -> {args.out}")
    return 0


def cmd_from_log(args: argparse.Namespace) -> int:
    lines: list[str] = []
    for path in args.logs:
        lines += path.read_text(encoding="utf-8", errors="replace").splitlines()
    ledger, unusable = from_log_lines(lines)
    write_ledger(args.out, ledger, "security log")
    print(f"purge-ledger: {len(ledger)} purge(s) in the security log -> {args.out}")
    if unusable:
        print(
            f"purge-ledger: {unusable} purge event(s) predate the fields a re-apply "
            "needs (before #116) and were skipped; re-apply those by hand.",
            file=sys.stderr,
        )
    return 0


def cmd_reapply(args: argparse.Namespace) -> int:
    ledger = merge(*(read_ledger(path) for path in args.ledgers))
    if not ledger:
        print("purge-ledger: no purges to re-apply.")
        return 0
    out = run_psql(args.psql, reapply_sql(ledger)).strip().splitlines()
    result = json.loads(out[-1]) if out else {}
    print(
        f"purge-ledger: re-applied {len(ledger)} purge(s): "
        f"{result.get('revisions', 0)} revision(s) and {result.get('entries', 0)} "
        f"audit entr(ies) destroyed again in {result.get('projects', 0)} project(s). "
        "Anything already purged was left alone."
    )
    return 0


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    top.add_argument(
        "--psql",
        type=shlex.split,
        default=None,
        help="the psql command to run (default: docker compose exec -T db psql ...)",
    )
    sub = top.add_subparsers(required=True)
    capture = sub.add_parser("capture", help="read the purges in the live database")
    capture.add_argument("--out", type=Path, required=True)
    capture.set_defaults(func=cmd_capture)
    log = sub.add_parser("from-log", help="read the purges in a JSON security log")
    log.add_argument("logs", type=Path, nargs="+")
    log.add_argument("--out", type=Path, required=True)
    log.set_defaults(func=cmd_from_log)
    reapply = sub.add_parser("reapply", help="re-apply the purges in ledger files")
    reapply.add_argument("ledgers", type=Path, nargs="+")
    reapply.set_defaults(func=cmd_reapply)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.psql is None:
        args.psql = default_psql()
    try:
        return args.func(args)
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"purge-ledger: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
