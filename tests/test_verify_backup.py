#!/usr/bin/env python3
"""A backup that has never been restored is a hypothesis (#52).

`make backup` writes an encrypted dump, and nothing ever read one back: the restore path
was assumed. 45 CFR 164.308(a)(7) makes a data backup plan required and testing it
addressable, and the dump holds the evidence that a clinical AI deployment was reviewed,
which cannot be reconstructed by re-entry.

`make verify-backup` (scripts/verify_backup.py) restores a dump into a throwaway
PostgreSQL of the same major version as production and checks that what the dump is
FOR survived: the tables, the rows, and the append-only triggers (a dump that
restores into a database without them has quietly lost the guarantee the history's
value rests on).

Real everything: a source PostgreSQL in Docker with the real migrations and real rows, a
real encrypted dump, and the real script. Needs Docker, gpg and make.

    pixi run test-verify-backup
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_backup.py"
CRYPTO = ROOT / "scripts" / "backup_crypto.sh"
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))
PASSPHRASE = "verify-backup-test-passphrase-0123456789"

spec = importlib.util.spec_from_file_location("verify_backup", SCRIPT)
vb = importlib.util.module_from_spec(spec)
sys.modules["verify_backup"] = vb
spec.loader.exec_module(vb)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def docker(*args: str, stdin: bytes | None = None, check_rc: bool = False):
    return subprocess.run(
        ["docker", *args], input=stdin, capture_output=True, check=check_rc
    )


def leftovers() -> list[str]:
    out = docker("ps", "-a", "--format", "{{.Names}}", "--filter", "name=chai-verify-")
    return [n for n in out.stdout.decode().split() if n]


def start_source() -> str:
    """A PostgreSQL with the real migrations applied and some real rows."""
    name = f"chai-vb-src-{secrets.token_hex(3)}"
    docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "POSTGRES_USER=chai", "-e", "POSTGRES_DB=chai",
        "-e", f"POSTGRES_PASSWORD={secrets.token_hex(8)}",
        "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
        vb.production_image(),
        check_rc=True,
    )  # fmt: skip
    for _ in range(60):
        if (
            docker("exec", name, "pg_isready", "-U", "chai", "-d", "chai").returncode
            == 0
        ):
            # initdb restarts once; wait for the second ready
            import time

            time.sleep(1.0)
            if (
                docker(
                    "exec", name, "pg_isready", "-U", "chai", "-d", "chai"
                ).returncode
                == 0
            ):
                break
        import time

        time.sleep(0.5)
    psql(
        name,
        "CREATE TABLE schema_migrations (version text PRIMARY KEY, "
        "applied_at timestamptz NOT NULL DEFAULT now())",
    )
    for migration in sorted((ROOT / "server" / "migrations").glob("*.sql")):
        done = docker(
            "exec", "-i", name, "psql", "-U", "chai", "-d", "chai",
            "-v", "ON_ERROR_STOP=1", "-q", "-f", "-",
            stdin=migration.read_bytes(),
        )  # fmt: skip
        assert done.returncode == 0, done.stderr.decode()[-400:]
        psql(
            name, f"INSERT INTO schema_migrations (version) VALUES ('{migration.name}')"
        )
    psql(
        name,
        "INSERT INTO projects (id, doc, created_by, updated_by) VALUES "
        "('p1', '{\"meta\":{\"solution\":\"One\"}}', 'a@x', 'a@x'), "
        "('p2', '{\"meta\":{\"solution\":\"Two\"}}', 'a@x', 'a@x')",
    )
    psql(
        name,
        "INSERT INTO project_log (project_id, by_id, entry) VALUES "
        "('p1', 'a@x', '{\"text\":\"one\"}'), ('p1', 'a@x', '{\"text\":\"two\"}'), "
        "('p2', 'a@x', '{\"text\":\"three\"}')",
    )
    return name


def psql(container: str, sql: str) -> str:
    done = docker("exec", container, "psql", "-U", "chai", "-d", "chai", "-tAc", sql)
    assert done.returncode == 0, done.stderr.decode()[-300:]
    return done.stdout.decode().strip()


def make_dump(source: str, target: Path, *, strip: str | None = None) -> Path:
    dump = docker(
        "exec", source, "pg_dump", "-U", "chai", "-d", "chai", "--clean", "--if-exists"
    ).stdout
    if strip:
        dump = b"\n".join(
            line for line in dump.split(b"\n") if strip.encode() not in line
        )
    gz = subprocess.run(["gzip", "-c"], input=dump, capture_output=True).stdout
    subprocess.run(
        [str(CRYPTO), "encrypt", str(target)],
        input=gz,
        env={**os.environ, "BACKUP_PASSPHRASE": PASSPHRASE},
        check=True,
    )
    return target


IDENTITY = (
    "SELECT cluster || ':' || database || ':' || history FROM retirement_ack_database()"
)
HISTORY = "SELECT json_agg(r ORDER BY id)::text FROM retirement_rule_change r"


def psql_in(container: str, database: str, sql: str) -> str:
    done = docker(
        "exec", container, "psql", "-U", "chai", "-d", database, "-v",
        "ON_ERROR_STOP=1", "-tAc", sql,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode()[-300:]
    return done.stdout.decode().strip()


def dump_into(source: str, target: str, database: str) -> None:
    """pg_dump --clean of the source's database, restored with psql into
    `database` of `target`: what `make backup` and `make restore` do."""
    dump = docker(
        "exec", source, "pg_dump", "-U", "chai", "-d", "chai", "--clean", "--if-exists"
    ).stdout
    done = docker(
        "exec", "-i", target, "psql", "-U", "chai", "-d", database, "-q",
        "-v", "ON_ERROR_STOP=1", "-f", "-",
        stdin=dump,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode()[-400:]


def identity_checks(source: str) -> None:
    """A retirement-rule acknowledgment binds the database's identity (012, D-76),
    so that a value printed for one database is refused by a copy made from its
    dump. Shown here with a real pg_dump, as `make backup` makes it, restored into
    another database of the same cluster, over the same database in place, and into
    another cluster. server/tests/test_retention.py shows the refusal itself."""
    print("A dump does not carry the database's identity (D-76)")
    original = psql_in(source, "chai", IDENTITY)
    history = psql_in(source, "chai", HISTORY)
    cluster, database, table = original.split(":")

    psql_in(source, "chai", "CREATE DATABASE chai_copy")
    dump_into(source, source, "chai_copy")
    copy = psql_in(source, "chai_copy", IDENTITY).split(":")
    check(
        "restored into another database of the same cluster: same history, "
        "another database OID",
        psql_in(source, "chai_copy", HISTORY) == history
        and copy[0] == cluster
        and copy[1] != database,
        f"{original} -> {':'.join(copy)}",
    )

    dump_into(source, source, "chai")
    in_place = psql_in(source, "chai", IDENTITY).split(":")
    check(
        "restored over the same database in place (make restore): same history "
        "and database, a new history table",
        psql_in(source, "chai", HISTORY) == history
        and in_place[:2] == [cluster, database]
        and in_place[2] != table,
        f"{original} -> {':'.join(in_place)}",
    )

    other = start_source()
    try:
        dump_into(source, other, "chai")
        elsewhere = psql_in(other, "chai", IDENTITY).split(":")
        check(
            "restored into another cluster: same history, another cluster",
            psql_in(other, "chai", HISTORY) == history and elsewhere[0] != cluster,
            f"{original} -> {':'.join(elsewhere)}",
        )
    finally:
        docker("rm", "-f", other)


def verify(*args: str, passphrase: str = PASSPHRASE):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "BACKUP_PASSPHRASE": passphrase},
        timeout=300,
    )


def main() -> int:
    if (
        not shutil.which("docker")
        or not shutil.which("gpg")
        or docker("info").returncode != 0
    ):
        print("docker or gpg unavailable; skipping verify-backup checks")
        return 1 if REQUIRE_TESTS else 0

    print("The decision, as pure functions")
    good = vb.Report(
        counts={
            "projects": 2,
            "project_log": 3,
            "project_version": 0,
            "schema_migrations": 5,
        },
        triggers={"project_log": 1, "project_version": 1},
        migrations=["001_init.sql"],
    )
    check(
        "a restored database with its tables and triggers has no problems",
        vb.problems_for(good) == [],
        str(vb.problems_for(good)),
    )
    check(
        "a missing table is a problem",
        bool(vb.problems_for(vb.Report({"projects": 1}, good.triggers, []))),
    )
    check(
        "a dump that lost the append-only triggers is a problem, not a pass",
        any("trigger" in p for p in vb.problems_for(vb.Report(good.counts, {}, []))),
    )
    check(
        "an empty portfolio is worth saying but is not a failure",
        vb.problems_for(vb.Report({**good.counts, "projects": 0}, good.triggers, []))
        == [],
    )
    # The retirement rules (D-76): required from the migration that made them a table.
    ruled = [*good.migrations, vb.RULES_MIGRATION]
    with_rules = {**good.counts, vb.RULES_TABLE: 4, vb.RULES_HISTORY: 1}
    ruled_triggers = {**good.triggers, vb.RULES_HISTORY: 1}
    seed = [("chai", "A", "Stop"), ("chai", "B", "Stop"), ("chai", "C", "Stop"),
            ("chai", "D", "Retire")]  # fmt: skip

    def rules_report(rules=seed, latest=seed, triggers=None, disabled=None):
        return vb.Report(
            with_rules,
            ruled_triggers if triggers is None else triggers,
            ruled,
            rules=list(rules),
            latest_rules=None if latest is None else list(latest),
            disabled_triggers=disabled or {},
        )

    check(
        "a restored database with its retirement rules has no problems",
        vb.problems_for(rules_report()) == [],
        str(vb.problems_for(rules_report())),
    )
    drifted = vb.problems_for(rules_report(rules=[*seed, ("chai", "B", "Shelve")]))
    check(
        "rules that are not the ones their history last recorded are a problem",
        any("last recorded" in p for p in drifted),
        str(drifted),
    )
    fewer = vb.problems_for(rules_report(rules=seed[:3]))
    check(
        "and so is a rule missing from them",
        any("last recorded" in p for p in fewer),
        str(fewer),
    )
    # The same number of rules, one of them another: a comparison of counts alone
    # would pass this.
    swapped = [*seed[:3], ("chai", "D", "Keep")]
    substituted = vb.problems_for(rules_report(rules=swapped))
    check(
        "and so is one rule swapped for another, with the count unchanged",
        len(swapped) == len(seed)
        and any(
            "last recorded" in p
            and "chai: checkpoint D decided 'Keep' (not in the history)" in p
            and "chai: checkpoint D decided 'Retire' (recorded, not in the table)" in p
            for p in substituted
        ),
        str(substituted),
    )
    unread = vb.problems_for(rules_report(latest=None))
    check(
        "a history whose latest change cannot be read is a problem",
        any("last recorded" in p for p in unread),
        str(unread),
    )
    off = vb.problems_for(
        rules_report(triggers=good.triggers, disabled={vb.RULES_HISTORY: 1})
    )
    check(
        "the rules' history restored with its trigger disabled is a problem",
        any(vb.RULES_HISTORY in p and "DISABLED" in p for p in off),
        str(off),
    )
    log_off = vb.problems_for(
        vb.Report(good.counts, {"project_version": 1}, [],
                  disabled_triggers={"project_log": 1})
    )  # fmt: skip
    check(
        "and so is a history table's trigger, disabled",
        any("project_log" in p and "DISABLED" in p for p in log_off),
        str(log_off),
    )
    check(
        "the rules' history restored without its append-only trigger is a problem",
        any(
            vb.RULES_HISTORY in p and "trigger" in p
            for p in vb.problems_for(rules_report(triggers=good.triggers))
        ),
        str(vb.problems_for(rules_report(triggers=good.triggers))),
    )
    check(
        "the rules' history missing after its migration is a problem",
        any(
            vb.RULES_HISTORY in p and "missing" in p
            for p in vb.problems_for(
                vb.Report(
                    {k: v for k, v in with_rules.items() if k != vb.RULES_HISTORY},
                    ruled_triggers,
                    ruled,
                )
            )
        ),
    )
    check(
        "the rules table missing after its migration is a problem",
        any(
            vb.RULES_TABLE in p
            for p in vb.problems_for(vb.Report(good.counts, good.triggers, ruled))
        ),
    )
    check(
        "an empty rules table is a problem: nothing would ever come due",
        any(
            "empty" in p
            for p in vb.problems_for(
                vb.Report({**with_rules, vb.RULES_TABLE: 0}, ruled_triggers, ruled)
            )
        ),
    )
    check(
        "a dump from before that migration needs no rules table",
        vb.problems_for(good) == [] and vb.RULES_MIGRATION not in good.migrations,
    )
    check(
        "the throwaway database is the production major version",
        vb.production_image().startswith("postgres:17"),
        vb.production_image(),
    )

    work = Path(tempfile.mkdtemp(prefix="chai-vb-"))
    source = None
    try:
        print("A real backup, restored for real")
        source = start_source()
        dump = make_dump(source, work / "20260101T000000Z.sql.gz.gpg")
        done = verify(str(dump))
        check(
            "a good encrypted dump verifies",
            done.returncode == 0,
            done.stdout[-500:] + done.stderr[-500:],
        )
        check(
            "and reports what was restored",
            "projects" in done.stdout
            and "2" in done.stdout
            and "project_log" in done.stdout,
            done.stdout,
        )
        check(
            "and the retirement rules it restored (D-76)",
            "retires on         chai: checkpoint D decided 'Retire'" in done.stdout
            and "retirement_rule           4 row(s)" in done.stdout,
            done.stdout,
        )
        check(
            "which are the rules their history last recorded",
            "as last recorded   retirement_rule_change #1" in done.stdout,
            done.stdout,
        )
        check(
            "and how many records belong to a framework with no rules (none here)",
            "no rules for              0 record(s)" in done.stdout,
            done.stdout,
        )
        check("the throwaway container is gone", leftovers() == [], str(leftovers()))

        # Every data row of the rules (and of their history) starts or holds
        # "chai<TAB>"; nothing else in this dump does.
        no_rules = make_dump(source, work / "no-rules.sql.gz.gpg", strip="chai\t")
        empty = verify(str(no_rules))
        check(
            "a dump whose retirement rules came back empty fails",
            empty.returncode != 0 and "retirement_rule is empty" in empty.stdout,
            empty.stdout[-400:],
        )
        check("and leaves nothing running", leftovers() == [], str(leftovers()))

        # The rules' history, restored without its append-only trigger, fails. The
        # source also gains a record of a framework with no rules, which the report
        # counts.
        psql(
            source,
            "INSERT INTO projects (id, doc, created_by, updated_by) VALUES ('p3', "
            '\'{"meta":{"framework":{"id":"acme"}}}\', \'a@x\', \'a@x\')',
        )
        untriggered = make_dump(
            source,
            work / "no-trigger.sql.gz.gpg",
            strip="retirement_rule_change_no_change",
        )
        lost = verify(str(untriggered))
        check(
            "a dump whose rules' history lost its append-only trigger fails",
            lost.returncode != 0
            and "retirement_rule_change was restored WITHOUT its append-only trigger"
            in lost.stdout,
            lost.stdout[-600:],
        )
        check(
            "and the report counts the record whose framework has no rules",
            "1 record(s) (acme: 1): never retired, so never due" in lost.stdout,
            lost.stdout[-600:],
        )
        check("and leaves nothing running", leftovers() == [], str(leftovers()))

        # A rule the owner wrote straight into the table, with no history row: the
        # restored rules are not the ones their history says were set.
        shelve = "('chai', 'B', 'Shelve')"
        psql(source, f"INSERT INTO retirement_rule VALUES {shelve}")
        drifted = verify(str(make_dump(source, work / "drift.sql.gz.gpg")))
        psql(
            source,
            "DELETE FROM retirement_rule WHERE (framework_id, gate_id, decision)"
            f" = {shelve}",
        )
        check(
            "a dump whose rules differ from their history's last change fails",
            drifted.returncode != 0
            and "retirement_rule does not hold the rules" in drifted.stdout
            and "chai: checkpoint B decided 'Shelve' (not in the history)"
            in drifted.stdout,
            drifted.stdout[-600:],
        )
        check("and leaves nothing running", leftovers() == [], str(leftovers()))

        # The history's trigger present but disabled: as good as absent, and pg_dump
        # carries the disabled state into the dump.
        trigger = "retirement_rule_change_no_change"
        psql(source, f"ALTER TABLE retirement_rule_change DISABLE TRIGGER {trigger}")
        disabled = verify(str(make_dump(source, work / "disabled.sql.gz.gpg")))
        psql(source, f"ALTER TABLE retirement_rule_change ENABLE TRIGGER {trigger}")
        check(
            "a dump whose rules' history trigger is disabled fails",
            disabled.returncode != 0
            and "retirement_rule_change was restored with its append-only trigger "
            "DISABLED"
            in disabled.stdout,
            disabled.stdout[-600:],
        )
        check("and leaves nothing running", leftovers() == [], str(leftovers()))

        # Enabled only for replication (tgenabled R): it fires only in a session whose
        # session_replication_role is "replica", which neither the API nor the owner
        # sets, so it is as good as disabled, and pg_dump carries the state too.
        psql(
            source,
            f"ALTER TABLE retirement_rule_change ENABLE REPLICA TRIGGER {trigger}",
        )
        replica_report = vb.inspect(source)
        check(
            "a trigger enabled only for replication counts as not enabled",
            vb.RULES_HISTORY in replica_report.disabled_triggers
            and vb.RULES_HISTORY not in replica_report.triggers,
            f"{replica_report.triggers} {replica_report.disabled_triggers}",
        )
        replica = verify(str(make_dump(source, work / "replica.sql.gz.gpg")))
        check(
            "a dump whose rules' history trigger fires only on a replica fails",
            replica.returncode != 0
            and "retirement_rule_change was restored with its append-only trigger "
            "DISABLED"
            in replica.stdout,
            replica.stdout[-600:],
        )
        check("and leaves nothing running", leftovers() == [], str(leftovers()))
        # Mutation: count R as firing, and the same source shows no problem.
        saved = vb.FIRING
        vb.FIRING = (*saved, "R")
        try:
            mutated = vb.inspect(source)
        finally:
            vb.FIRING = saved
        check(
            "mutation: with R counted as firing, the replica-only trigger would pass",
            vb.RULES_HISTORY in mutated.triggers
            and not any(vb.RULES_HISTORY in p for p in vb.problems_for(mutated)),
            str(vb.problems_for(mutated)),
        )
        psql(source, f"ALTER TABLE retirement_rule_change ENABLE TRIGGER {trigger}")
        recheck = verify(str(make_dump(source, work / "again.sql.gz.gpg")))
        check(
            "and the same source, set right again, verifies",
            recheck.returncode == 0,
            recheck.stdout[-600:],
        )

        identity_checks(source)

        print("Failures are failures")
        wrong = verify(str(dump), passphrase="not-the-passphrase")
        check(
            "the wrong passphrase fails",
            wrong.returncode != 0
            and "decrypt" in (wrong.stdout + wrong.stderr).lower(),
            wrong.stdout[-300:] + wrong.stderr[-300:],
        )
        check("and leaves nothing running", leftovers() == [], str(leftovers()))

        truncated = work / "truncated.sql.gz.gpg"
        truncated.write_bytes(dump.read_bytes()[: dump.stat().st_size // 2])
        cut = verify(str(truncated))
        check("a truncated dump fails", cut.returncode != 0, cut.stdout[-300:])
        check("and leaves nothing running", leftovers() == [], str(leftovers()))

        no_triggers = make_dump(
            source, work / "no-triggers.sql.gz.gpg", strip="CREATE TRIGGER"
        )
        lost = verify(str(no_triggers))
        check(
            "a dump that restores without the append-only triggers fails",
            lost.returncode != 0 and "trigger" in (lost.stdout + lost.stderr).lower(),
            lost.stdout[-400:],
        )
        check("and leaves nothing running", leftovers() == [], str(leftovers()))

        missing = verify(str(work / "nope.sql.gz.gpg"))
        check("a file that does not exist fails", missing.returncode != 0)

        print("The newest dump is the default, which is what `make verify-backup` runs")
        newest = work / "backups"
        newest.mkdir()
        shutil.copy(dump, newest / "20260101T000000Z.sql.gz.gpg")
        (newest / "20240101T000000Z.sql.gz.gpg").write_bytes(b"older and corrupt")
        make = subprocess.run(
            ["make", "verify-backup", f"BACKUP_DIR={newest}"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env={**os.environ, "BACKUP_PASSPHRASE": PASSPHRASE},
            timeout=300,
        )
        check(
            "make verify-backup picks the newest and passes",
            make.returncode == 0,
            make.stdout[-400:] + make.stderr[-400:],
        )
        empty = work / "empty"
        empty.mkdir()
        none = subprocess.run(
            ["make", "verify-backup", f"BACKUP_DIR={empty}"],
            capture_output=True, text=True, cwd=ROOT,
            env={**os.environ, "BACKUP_PASSPHRASE": PASSPHRASE},
        )  # fmt: skip
        check(
            "with no backups at all it fails rather than passing on nothing",
            none.returncode != 0,
        )
    finally:
        if source:
            docker("rm", "-f", source)
        shutil.rmtree(work, ignore_errors=True)

    print("make restore asks before overwriting a live database")
    sink = Path(tempfile.mkdtemp(prefix="chai-sink-")) / "sink.sh"
    sink.write_text('#!/bin/sh\ncat > /dev/null\necho "CALLED $*" >> "$SINK_LOG"\n')
    sink.chmod(0o755)
    log = sink.parent / "calls.log"
    plain = sink.parent / "d.sql.gz"
    plain.write_bytes(
        subprocess.run(["gzip", "-c"], input=b"select 1;", capture_output=True).stdout
    )

    def restore(stdin: str = "", *extra: str):
        log.write_text("")
        done = subprocess.run(
            ["make", "restore", f"FILE={plain}", f"COMPOSE={sink}",
             f"BACKUP_DIR={sink.parent}", *extra],
            input=stdin, capture_output=True, text=True, cwd=ROOT,
            env={**os.environ, "SINK_LOG": str(log)},
        )  # fmt: skip
        # A restore reads the live database's purges first (#116), then restores, then
        # reports what is past its retention period (#57): three calls. The ledger it
        # read is empty, so there is nothing to re-apply.
        return done, log.read_text().count("CALLED")

    done, calls = restore("")
    check(
        "with no answer it aborts and touches nothing",
        done.returncode != 0 and calls == 0,
        f"exit {done.returncode}, calls {calls}",
    )
    done, calls = restore("no\n")
    check("any answer but YES aborts", done.returncode != 0 and calls == 0)
    check(
        "and the prompt names what is at stake",
        "OVERWRITE" in (done.stdout + done.stderr).upper(),
    )
    done, calls = restore("YES\n")
    check(
        "typing YES proceeds",
        done.returncode == 0 and calls == 3,
        f"exit {done.returncode}, calls {calls}: {done.stderr[-200:]}",
    )
    last = (log.read_text().splitlines() or [""])[-1]
    check(
        "and ends by reporting what is due for disposal",
        "-A" in last.split() and "-t" in last.split(),
        last,
    )
    check(
        "a report that cannot run does not fail the restore, and says so",
        "Could not report it" in done.stderr,
        done.stderr[-200:],
    )
    first = (log.read_text().splitlines() or [""])[0]
    check(
        "and reads the purges before it overwrites anything",
        "-A" in first.split() and "-t" in first.split(),
        first,
    )
    done, calls = restore("", "CONFIRM=YES")
    check(
        "CONFIRM=YES proceeds for automation, without a prompt",
        done.returncode == 0 and calls == 3,
    )
    shutil.rmtree(sink.parent, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("verify-backup checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
