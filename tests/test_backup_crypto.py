#!/usr/bin/env python3
"""The backup passphrase must never be in a process's argv (#41).

`make backup` used to run `gpg --passphrase "$(BACKUP_PASSPHRASE)"`. A process's
argv is world-readable on Linux (`ps auxww`, or /proc/<pid>/cmdline, mode 444),
so for the lifetime of the dump every local account could read the key that
decrypts every governance record, audit entry and retained version. Worse, make
expands `$(VAR)` into the recipe text itself, so the value was ALSO in the argv
of the `sh -c` that ran the recipe, even on lines that never mention gpg.

Three things are tested, each against the real tool:

1. `make -n backup` prints the recipe make would hand to the shell. If the
   passphrase is in that text, it is in `sh -c` argv. Same for `restore`.
2. A real gpg run, with the process table scanned WHILE gpg is running, finds the
   passphrase nowhere in any argv.
3. The encryption still works: a round trip returns the data, a wrong passphrase
   fails, and no key file is left behind.

The scanner is shown able to find a leak, by running the old command shape.

    pixi run test-backup-crypto   (needs gpg and make; fails under REQUIRE_TESTS)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "backup_crypto.sh"
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))
SECRET = "Zq7-needle-passphrase-8841"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def argv_with(needle: str) -> list[str]:
    """Every live process whose argv contains `needle`, read as any user could."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (
                (entry / "cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", "replace")
            )
        except OSError:
            continue
        if needle in argv and entry.name != str(os.getpid()):
            found.append(f"{entry.name}: {argv[:120]}")
    return found


def watch_argv(needle: str, until: threading.Event) -> list[str]:
    """Poll the process table until `until` is set; return every sighting."""
    seen: list[str] = []
    while not until.is_set():
        seen += argv_with(needle)
        time.sleep(0.01)
    return seen


class Slow:
    """Feeds `data` to a process a chunk at a time, so it stays alive to be seen."""

    def __init__(self, data: bytes, seconds: float) -> None:
        self.data, self.seconds = data, seconds

    def feed(self, stdin) -> None:
        step = max(len(self.data) // 20, 1)
        for i in range(0, len(self.data), step):
            stdin.write(self.data[i : i + step])
            stdin.flush()
            time.sleep(self.seconds / 20)
        stdin.close()


def scan_while(argv: list[str], env: dict, data: bytes) -> tuple[int, list[str]]:
    stop = threading.Event()
    sightings: list[str] = []
    watcher = threading.Thread(
        target=lambda: sightings.extend(watch_argv(SECRET, stop)), daemon=True
    )
    watcher.start()
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    Slow(data, 0.6).feed(proc.stdin)
    proc.stdout.read()
    code = proc.wait()
    stop.set()
    watcher.join()
    return code, sightings


def check_doctor_keeps_the_database_password_out_of_argv() -> None:
    """`make doctor` passed `-e PGPASSWORD=<value>` to `docker compose exec`.

    That is argv of the host `docker` process, readable by any local account for
    as long as it runs. What is under test is how doctor INVOKES docker, so a
    recording stand-in on PATH is the right instrument: it notes the argv and the
    environment it was given and answers like a database that accepts the login.
    """
    print("scripts/doctor.py")
    password = "doctor-needle-pw-5521"
    workdir = Path(tempfile.mkdtemp(prefix="chai-doctor-"))
    try:
        log = workdir / "calls.log"
        stub = workdir / "bin" / "docker"
        stub.parent.mkdir()
        stub.write_text(
            "#!/bin/sh\n"
            f'printf "ARGV: %s\\n" "$*" >> {log}\n'
            f'printf "ENV_PGPASSWORD: %s\\n" "${{PGPASSWORD:-}}" >> {log}\n'
            'case "$*" in *"select 1"*) echo 1 ;; esac\n'
        )
        stub.chmod(0o755)
        script = (
            "import importlib.util, sys; "
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
            "s = importlib.util.spec_from_file_location("
            f"'doctor', {str(ROOT / 'scripts' / 'doctor.py')!r}); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "m.Doctor().check_password("
            f"{{'POSTGRES_PASSWORD': {password!r}}}, {{'db': {{'State': 'running'}}}})"
        )
        done = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": f"{stub.parent}:{os.environ['PATH']}"},
        )
        calls = log.read_text() if log.exists() else ""
        check(
            "doctor ran its login check through docker",
            "select 1" in calls,
            (done.stdout + done.stderr)[-300:],
        )
        argv_lines = [line for line in calls.splitlines() if line.startswith("ARGV")]
        check(
            "the database password is not in docker's argv",
            argv_lines != [] and not any(password in line for line in argv_lines),
            "; ".join(argv_lines),
        )
        check(
            "it reaches docker through the environment instead",
            f"ENV_PGPASSWORD: {password}" in calls,
            calls[-200:],
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def check_restore_status_follows_the_whole_pipeline() -> None:
    """A restore that decrypted nothing must not exit 0.

    `restore` is `gpg | gunzip | psql`. Without pipefail its status was psql's,
    and psql given an empty stream succeeds, so a wrong passphrase reported a
    successful restore. The database is a sink here (`cat > /dev/null`), because
    what is under test is the Makefile's pipeline, not PostgreSQL.
    """
    print("A restore's exit status")
    workdir = Path(tempfile.mkdtemp(prefix="chai-restore-"))
    try:
        sink = workdir / "sink.sh"
        sink.write_text("#!/bin/sh\ncat > /dev/null\n")
        sink.chmod(0o755)
        dump = workdir / "ok.sql.gz.gpg"
        env = {**os.environ, "BACKUP_PASSPHRASE": SECRET}
        gz = subprocess.run(["gzip", "-c"], input=b"select 1;\n", capture_output=True)
        subprocess.run(
            [str(SCRIPT), "encrypt", str(dump)], input=gz.stdout, env=env, check=True
        )

        def restore(passphrase: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["make", "restore", f"FILE={dump}", f"COMPOSE={sink}"],
                capture_output=True,
                text=True,
                cwd=ROOT,
                env={**env, "BACKUP_PASSPHRASE": passphrase},
            )

        good = restore(SECRET)
        check(
            "a restore with the right passphrase exits 0",
            good.returncode == 0,
            good.stderr[-200:],
        )
        # And a backup whose database command fails must not leave a file behind
        # or report success: an empty "encrypted" dump is the worst kind.
        out_dir = workdir / "backups"
        failing = subprocess.run(
            ["make", "backup", "COMPOSE=false", f"BACKUP_DIR={out_dir}"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
        )
        check(
            "a backup whose pg_dump fails exits non-zero",
            failing.returncode != 0,
            f"exit {failing.returncode}: {failing.stdout[-200:]}",
        )
        check(
            "and keeps no file",
            not list(out_dir.glob("*")),
            str(list(out_dir.glob("*"))),
        )
        bad = restore("not-the-passphrase")
        check(
            "a restore with the wrong passphrase exits non-zero",
            bad.returncode != 0,
            f"exit {bad.returncode}: it reported success having restored nothing",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    if not shutil.which("gpg") or not shutil.which("make"):
        print("gpg or make unavailable; skipping backup crypto checks")
        return 1 if REQUIRE_TESTS else 0

    print("The recipe text make hands to the shell")
    for target, extra in (("backup", []), ("restore", ["FILE=backups/x.sql.gz.gpg"])):
        done = subprocess.run(
            ["make", "-n", target, f"BACKUP_PASSPHRASE={SECRET}", *extra],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        check(
            f"`make -n {target}` does not expand the passphrase into the recipe",
            SECRET not in done.stdout,
            "the value is in the text passed to `sh -c`, so it is in its argv",
        )

    print("The guards: no passphrase, no dump")
    clean = {k: v for k, v in os.environ.items() if k != "BACKUP_PASSPHRASE"}
    existed = (ROOT / "backups").exists()
    refused = subprocess.run(
        ["make", "backup"], capture_output=True, text=True, cwd=ROOT, env=clean
    )
    check(
        "make backup with no passphrase is refused",
        refused.returncode != 0 and "BACKUP_PASSPHRASE is not set" in refused.stdout,
        f"exit {refused.returncode}: {refused.stdout[-200:]}",
    )
    check(
        "and writes nothing, not even an empty file",
        (ROOT / "backups").exists() == existed
        and not list((ROOT / "backups").glob("*"))
        if existed
        else not (ROOT / "backups").exists(),
        "a backups/ directory or file appeared",
    )
    plain = subprocess.run(
        ["make", "backup-plaintext"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=clean,
    )
    check(
        "a plaintext dump needs PLAINTEXT=1 and is refused without it",
        plain.returncode != 0 and "PLAINTEXT=1" in plain.stdout,
        f"exit {plain.returncode}: {plain.stdout[-200:]}",
    )
    needs = subprocess.run(
        ["make", "restore", "FILE=backups/x.sql.gz.gpg"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=clean,
    )
    check(
        "restoring an encrypted dump with no passphrase is refused",
        needs.returncode != 0 and "BACKUP_PASSPHRASE is needed" in needs.stderr,
        f"exit {needs.returncode}: {needs.stdout[-200:]} {needs.stderr[-200:]}",
    )

    check_restore_status_follows_the_whole_pipeline()

    print("The scanner can see a leak (the old command shape)")
    leak = subprocess.Popen(
        [
            "sh",
            "-c",
            f"gpg --batch --symmetric --passphrase '{SECRET}' --output /dev/null",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.2)
    leaked = argv_with(SECRET)
    leak.stdin.close()
    leak.wait()
    check("a passphrase on gpg's command line is found", bool(leaked), str(leaked))

    print("The real script, with the process table watched while gpg runs")
    workdir = Path(tempfile.mkdtemp(prefix="chai-backup-"))
    try:
        data = os.urandom(200_000) + b"every governance record " * 4000
        out = workdir / "dump.gpg"
        env = {**os.environ, "BACKUP_PASSPHRASE": SECRET, "TMPDIR": str(workdir)}

        code, seen = scan_while([str(SCRIPT), "encrypt", str(out)], env, data)
        check("encrypt succeeds", code == 0 and out.exists(), f"exit {code}")
        check(
            "the passphrase is in no process's argv while encrypting",
            not seen,
            "; ".join(seen[:3]),
        )
        check(
            "the dump is not plaintext",
            b"every governance record" not in out.read_bytes(),
        )

        stop = threading.Event()
        sightings: list[str] = []
        watcher = threading.Thread(
            target=lambda: sightings.extend(watch_argv(SECRET, stop)), daemon=True
        )
        watcher.start()
        slow = subprocess.run(
            ["sh", "-c", f'"{SCRIPT}" decrypt "{out}" | (sleep 0.4; cat)'],
            capture_output=True,
            env=env,
        )
        stop.set()
        watcher.join()
        check("a round trip returns exactly what went in", slow.stdout == data)
        check(
            "the passphrase is in no process's argv while decrypting",
            not sightings,
            "; ".join(sightings[:3]),
        )

        wrong = subprocess.run(
            [str(SCRIPT), "decrypt", str(out)],
            capture_output=True,
            env={**env, "BACKUP_PASSPHRASE": "not-the-passphrase"},
        )
        check(
            "a wrong passphrase fails and yields no plaintext",
            wrong.returncode != 0 and b"governance" not in wrong.stdout,
            f"exit {wrong.returncode}",
        )
        for mode in ("encrypt", "decrypt"):
            blank = subprocess.run(
                [str(SCRIPT), mode, str(out)],
                capture_output=True,
                env={k: v for k, v in env.items() if k != "BACKUP_PASSPHRASE"},
                input=b"",
            )
            check(
                f"{mode} with no passphrase is refused",
                blank.returncode != 0,
                f"exit {blank.returncode}",
            )
        left = [p.name for p in workdir.iterdir() if p.name != "dump.gpg"]
        check("no key file is left behind", not left, ", ".join(left))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    check_doctor_keeps_the_database_password_out_of_argv()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("backup crypto checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
