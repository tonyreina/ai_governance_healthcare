#!/usr/bin/env python3
"""A restore does not undo a purge (#116, #57).

A purge destroys the content of a project's revisions and redacts its audit log. A dump
taken before it still holds that content, so restoring the dump used to bring it back,
silently. `make restore` now captures the live database's purges first and re-applies
them after (`scripts/purge_ledger.py`); when the live database is gone, the ledger can
be rebuilt from the security log.

Everything here is real: a PostgreSQL with the real migrations and the real triggers, a
real `pg_dump` taken before a purge and restored after it, and the real script. The
triggers are what make the re-apply safe: they permit only the purge transition, so a
ledger that tried anything else would fail. Needs Docker.

    pixi run test-purge-ledger
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pl = load("purge_ledger", ROOT / "scripts" / "purge_ledger.py")
vb = load("verify_backup", ROOT / "scripts" / "verify_backup.py")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def docker(*args: str, stdin: bytes | None = None):
    return subprocess.run(["docker", *args], input=stdin, capture_output=True)


def start() -> str:
    name = f"chai-ledger-{secrets.token_hex(3)}"
    done = docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "POSTGRES_USER=chai", "-e", "POSTGRES_DB=chai",
        "-e", f"POSTGRES_PASSWORD={secrets.token_hex(8)}",
        "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
        vb.production_image(),
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode()[-300:]
    streak = 0
    for _ in range(120):
        ready = docker("exec", name, "pg_isready", "-U", "chai", "-d", "chai")
        streak = streak + 1 if ready.returncode == 0 else 0
        if streak >= 2:
            break
        time.sleep(0.6)
    for migration in sorted((ROOT / "server" / "migrations").glob("*.sql")):
        done = docker(
            "exec", "-i", name, "psql", "-U", "chai", "-d", "chai",
            "-v", "ON_ERROR_STOP=1", "-q", "-f", "-",
            stdin=migration.read_bytes(),
        )  # fmt: skip
        assert done.returncode == 0, done.stderr.decode()[-400:]
    return name


def psql(name: str, sql: str) -> str:
    done = docker(
        "exec", "-i", name, "psql", "-U", "chai", "-d", "chai",
        "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-",
        stdin=sql.encode(),
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode()[-400:]
    return done.stdout.decode().strip()


SEED = """
INSERT INTO projects (id, doc, incarnation) VALUES
  ('p1', '{"meta":{"solution":"One"}}', '11111111-1111-1111-1111-111111111111'),
  ('p2', '{"meta":{"solution":"Two"}}', '22222222-2222-2222-2222-222222222222');
INSERT INTO project_version (project_id, rev, doc, content_md5, incarnation, changed_by,
                             changed_at)
VALUES
  ('p1', 1, '{"secret":"entered by mistake"}', 'a',
   '11111111-1111-1111-1111-111111111111', 'w@h', now() - interval '3 days'),
  ('p1', 2, '{"secret":"entered by mistake"}', 'b',
   '11111111-1111-1111-1111-111111111111', 'w@h', now() - interval '2 days'),
  ('p2', 1, '{"meta":{"solution":"Two"}}', 'c',
   '22222222-2222-2222-2222-222222222222', 'w@h', now() - interval '2 days'),
  ('gone', 1, '{"secret":"in a deleted project"}', 'd',
   '33333333-3333-3333-3333-333333333333', 'w@h', now() - interval '2 days');
INSERT INTO project_log (project_id, at, by_id, entry) VALUES
  ('p1', now() - interval '2 days', 'w@h', '{"text":"Changed it to the mistake"}'),
  ('p1', now() - interval '2 days', 'w@h', '{"text":"and again"}'),
  ('p2', now() - interval '2 days', 'w@h', '{"text":"untouched"}');
"""

# What DELETE /api/projects/{id}/versions does (server/app/routes.py), at a fixed time.
PURGE = """
UPDATE project_version SET doc = '{{}}'::jsonb, purged_at = '{at}', purged_by = 'dpo@h'
 WHERE project_id = '{project}' AND incarnation = '{incarnation}' AND purged_at IS NULL;
UPDATE project_log SET entry = project_log_redacted(entry), purged_at = '{at}',
       purged_by = 'dpo@h'
 WHERE project_id = '{project}' AND purged_at IS NULL AND NOT is_system;
"""


def run(prefix: list[str], *args: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = pl.main(["--psql", " ".join(prefix), *args])
    return code, out.getvalue() + err.getvalue()


def unit() -> None:
    print("The ledger, without a database")
    good = {
        "project": "p", "incarnation": "u", "purged_at": "t", "purged_by": "b",
        "through_rev": 3, "through_seq": None,
    }  # fmt: skip
    check("a purge with a revision bound is kept", pl.normalize(good) is not None)
    check(
        "a revision bound without an incarnation is refused",
        pl.normalize({**good, "incarnation": None}) is None,
    )
    check(
        "a purge that reached nothing is dropped",
        pl.normalize({**good, "through_rev": None}) is None,
    )
    check("the same purge twice is one", len(pl.merge([good], [dict(good)])) == 1)
    tag = pl.dollar_literal("$ledger_x$ and ' quotes")
    check(
        "the literal's tag never occurs inside it",
        tag.count(tag.split("$")[1]) == 2,
        tag,
    )
    lines = [
        'api-1  | {"event": "versions.purged", "actor": "dpo@h", "project": "p1",'
        ' "incarnation": "u1", "purged_at": "2026-01-01T00:00:00+00:00",'
        ' "through_rev": 2, "through_seq": 7, "revisions": 2, "log_entries": 2}',
        '{"event": "versions.purged", "actor": "dpo@h", "project": "old",'
        ' "revisions": 3, "log_entries": 1}',
        '{"event": "project.deleted", "project": "p9"}',
        "not json at all",
    ]
    ledger, unusable = pl.from_log_lines(lines)
    check(
        "the security log yields the purge, with its bounds",
        ledger
        == [
            {
                "project": "p1", "incarnation": "u1",
                "purged_at": "2026-01-01T00:00:00+00:00", "purged_by": "dpo@h",
                "through_rev": 2, "through_seq": 7,
            }
        ],
        str(ledger),
    )  # fmt: skip
    check("and counts an event too old to re-apply", unusable == 1)
    # The script runs on the host's Python and cannot import the server's enum, so
    # the event name is pinned to it here instead.
    source = (ROOT / "server" / "app" / "securitylog.py").read_text(encoding="utf-8")
    check(
        "the event it reads is the one the server writes",
        f'VERSIONS_PURGED = "{pl.PURGE_EVENT}"' in source,
    )


def integration() -> None:
    print("A real dump, a real purge, a real restore")
    if not shutil.which("docker"):
        if REQUIRE_TESTS:
            check("docker is available", False, "REQUIRE_TESTS is set")
        else:
            print("  skip  docker unavailable: the restore is not checked")
        return
    name = start()
    prefix = ["docker", "exec", "-i", name, "psql", "-U", "chai", "-d", "chai"]
    tmp = Path(tempfile.mkdtemp(prefix="chai-ledger-"))
    try:
        psql(name, SEED)
        dump = docker(
            "exec", name, "pg_dump", "-U", "chai", "-d", "chai",
            "--clean", "--if-exists",
        ).stdout  # fmt: skip
        # Written after the dump and purged with the rest: the restored sequence will
        # hand its number to the next entry, which the purge never saw.
        psql(
            name,
            "INSERT INTO project_log (project_id, at, by_id, entry) VALUES ('p1',"
            " now() - interval '1 hour', 'w@h',"
            ' \'{"text":"mistake, after the dump"}\')',
        )
        # The purge happens now, after every seeded row was written.
        at = psql(
            name,
            "SELECT to_char(now() AT TIME ZONE 'UTC',"
            ' \'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"\')',
        )
        psql(
            name,
            PURGE.format(
                at=at, project="p1", incarnation="11111111-1111-1111-1111-111111111111"
            )
            + PURGE.format(
                at=at,
                project="gone",
                incarnation="33333333-3333-3333-3333-333333333333",
            ),
        )

        ledger_path = tmp / "ledger.json"
        code, text = run(prefix, "capture", "--out", str(ledger_path))
        captured = json.loads(ledger_path.read_text())["purges"]
        check("capture reads both purges", code == 0 and len(captured) == 2, text)
        p1 = next((e for e in captured if e["project"] == "p1"), {})
        check(
            "with the bounds a re-apply needs",
            p1.get("through_rev") == 2
            and p1.get("through_seq") is not None
            and p1.get("incarnation") == "11111111-1111-1111-1111-111111111111"
            and p1.get("purged_by") == "dpo@h",
            str(p1),
        )
        check(
            "the ledger file is readable by its owner only",
            oct(ledger_path.stat().st_mode & 0o777) == "0o600",
            oct(ledger_path.stat().st_mode & 0o777),
        )

        # The problem: restoring the older dump brings the content back.
        restored = docker(
            "exec", "-i", name, "psql", "-U", "chai", "-d", "chai", "-q",
            "-v", "ON_ERROR_STOP=1", "-f", "-", stdin=dump,
        )  # fmt: skip
        assert restored.returncode == 0, restored.stderr.decode()[-300:]
        back = psql(
            name,
            "SELECT count(*) FROM project_version WHERE doc::text LIKE '%mistake%'",
        )
        check(
            "restoring a dump from before the purge brings the content back",
            back == "2",
        )

        # Work done after the restore is never part of the old purge.
        psql(
            name,
            "INSERT INTO project_version"
            " (project_id, rev, doc, content_md5, incarnation)"
            " VALUES ('p1', 3, '{\"meta\":{\"solution\":\"new work\"}}', 'e',"
            " '11111111-1111-1111-1111-111111111111');"
            " INSERT INTO project_log (project_id, by_id, entry)"
            " VALUES ('p1', 'w@h', '{\"text\":\"new work after the restore\"}');",
        )

        reused = psql(
            name,
            "SELECT seq FROM project_log WHERE entry::text LIKE '%new work%'",
        )
        check(
            "the new entry reuses a number the purge covered (the case under test)",
            int(reused) <= int(p1["through_seq"]),
            f"{reused} vs {p1['through_seq']}",
        )
        # Mutation: without the time guard, the re-apply redacts work it never saw.
        unguarded = pl.reapply_sql(pl.merge(captured)).replace(
            "AND x.at <= l.purged_at", ""
        )
        probe = psql(name, unguarded.replace("COMMIT;", "ROLLBACK;"))
        lost = psql(
            name,
            "SELECT count(*) FROM project_log WHERE entry::text LIKE '%new work%'",
        )
        check(
            "without the time guard it would destroy that new entry (mutation)",
            json.loads(probe.splitlines()[-1])["entries"] == 3 and lost == "1",
            probe,
        )

        code, text = run(prefix, "reapply", str(ledger_path))
        check("re-apply runs", code == 0, text)
        check(
            "the mistaken content is gone again",
            psql(
                name,
                "SELECT count(*) FROM project_version WHERE doc::text LIKE '%mistake%'",
            )
            == "0",
        )
        check(
            "with the original time and person",
            psql(
                name,
                "SELECT count(*) FROM project_version WHERE project_id = 'p1'"
                f" AND purged_at = '{at}' AND purged_by = 'dpo@h'",
            )
            == "2",
        )
        check(
            "the audit log is redacted again",
            psql(
                name,
                "SELECT count(*) FROM project_log WHERE project_id = 'p1'"
                " AND NOT is_system AND entry::text LIKE '%mistake%'",
            )
            == "0",
        )
        check(
            "a deleted project's surviving history is purged again too",
            psql(
                name,
                "SELECT count(*) FROM project_version WHERE project_id = 'gone'"
                " AND purged_at IS NOT NULL",
            )
            == "1",
        )
        check(
            "work written after the restore is untouched",
            psql(
                name,
                "SELECT count(*) FROM project_version WHERE project_id = 'p1'"
                " AND rev = 3 AND purged_at IS NULL",
            )
            == "1"
            and psql(
                name,
                "SELECT count(*) FROM project_log WHERE entry::text LIKE '%new work%'"
                " AND purged_at IS NULL",
            )
            == "1",
        )
        check(
            "another project is untouched",
            psql(name, "SELECT count(*) FROM project_version WHERE project_id = 'p2'"
                 " AND purged_at IS NULL") == "1",
        )  # fmt: skip
        notes = psql(
            name,
            "SELECT count(*) FROM project_log WHERE is_system"
            " AND entry->>'event' = 'purge.reapplied'",
        )
        check("the project's audit log says it was re-applied", notes == "1", notes)

        code, text = run(prefix, "reapply", str(ledger_path))
        check(
            "running it again changes nothing",
            code == 0 and "0 revision(s) and 0 audit" in text,
            text,
        )
        check(
            "and writes no second note",
            psql(
                name,
                "SELECT count(*) FROM project_log"
                " WHERE entry->>'event' = 'purge.reapplied'",
            )
            == "1",
        )

        hostile = tmp / "hostile.json"
        pl.write_ledger(
            hostile,
            [
                {
                    "project": "x'); DROP TABLE projects; --$ledger_$",
                    "incarnation": "44444444-4444-4444-4444-444444444444",
                    "purged_at": at, "purged_by": "o'brien", "through_rev": 9,
                    "through_seq": 9,
                }
            ],
            "test",
        )  # fmt: skip
        code, text = run(prefix, "reapply", str(hostile))
        check(
            "a hostile ledger is only data",
            code == 0 and psql(name, "SELECT count(*) FROM projects") == "2",
            text,
        )

        empty = tmp / "empty.json"
        pl.write_ledger(empty, [], "test")
        code, text = run(["false"], "reapply", str(empty))
        check("an empty ledger does not touch the database", code == 0, text)
    finally:
        docker("rm", "-f", name)
        shutil.rmtree(tmp, ignore_errors=True)


def wiring() -> None:
    print("make restore captures before it overwrites, and re-applies after")
    plan = subprocess.run(
        ["make", "-n", "restore", "FILE=x.sql.gz", "CONFIRM=YES"],
        capture_output=True, text=True, cwd=ROOT,
    ).stdout  # fmt: skip
    capture = plan.find("purge_ledger.py")
    restore = plan.find("gunzip -c")
    reapply = plan.rfind("reapply")
    check(
        "capture, then the restore, then reapply",
        -1 < capture < restore < reapply,
        f"{capture} {restore} {reapply}",
    )
    check(
        "and it warns, not stops, when the live database cannot be read",
        "WARNING" in plan and "NOT be re-applied" in plan,
    )


def main() -> int:
    unit()
    integration()
    wiring()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("purge ledger checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
