#!/usr/bin/env python3
"""Diagnose a stack that is up but not working.

``preflight.py`` runs before ``make up`` and inspects ``.env`` alone. It cannot
see the one failure that ``.env`` causes and ``.env`` cannot explain:

PostgreSQL reads ``POSTGRES_PASSWORD`` **only when it initializes an empty data
directory**. On an existing ``pgdata`` volume the variable is ignored. So
editing it in ``.env`` changes what the API presents without changing what the
database accepts, and the API can no longer reach its own database. Nothing
warns -- and preflight is what sends people there, because it insists the
password be strong and not a placeholder, which is exactly the check that makes
somebody change it.

The symptom points nowhere useful: the API retries ten times and exits, so
``docker compose ps`` shows a crash loop and the dashboard says "cannot reach
the governance server". Nothing says "password".

This needs the stack up, so it is ``make doctor`` rather than a gate on
``make up``. It changes nothing; it only looks and tells you what to run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preflight import ENV_FILE, read_env

COMPOSE = ["docker", "compose"]
VOLUME = "chai-governance_pgdata"

OK, WARN, BAD = "ok", "warn", "FAIL"


def run(
    args: list[str], stdin: str | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, capture_output=True, text=True, input=stdin, timeout=60, env=env
    )


def say(level: str, title: str, *lines: str) -> None:
    print(f"  {level:<4}  {title}")
    for line in lines:
        print(f"        {line}" if line else "")


class Doctor:
    def __init__(self) -> None:
        self.problems = 0

    def fail(self, title: str, *lines: str) -> None:
        self.problems += 1
        say(BAD, title, *lines)

    # -- the checks ---------------------------------------------------------

    def services(self) -> dict[str, dict]:
        """What compose thinks is running, by service name."""
        result = run([*COMPOSE, "ps", "--format", "json", "--all"])
        if result.returncode != 0:
            self.fail(
                "docker compose is not usable here",
                result.stderr.strip().splitlines()[-1] if result.stderr else "",
            )
            return {}
        # `compose ps --format json` emits one object per line on v2, and a
        # single array on some builds. Accept both.
        text = result.stdout.strip()
        if not text:
            return {}
        if text.startswith("["):
            rows = json.loads(text)
        else:
            rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        return {row["Service"]: row for row in rows}

    def check_running(self, services: dict[str, dict]) -> None:
        if not services:
            self.fail(
                "nothing is running",
                "Start the stack first:  make up",
            )
            return
        for name in ("db", "api", "proxy"):
            row = services.get(name)
            if row is None:
                self.fail(f"service {name!r} does not exist", "Run `make up`.")
                continue
            state = row.get("State", "?")
            health = row.get("Health") or ""
            detail = f"{state}{f' ({health})' if health else ''}"
            if state == "running" and health not in ("unhealthy", "starting"):
                say(OK, f"{name} is {detail}")
            elif state == "restarting":
                self.fail(
                    f"{name} is {detail}",
                    "A crash loop. The password check below is the usual cause.",
                )
            else:
                self.fail(f"{name} is {detail}", f"docker compose logs {name}")

    def check_password(self, env: dict[str, str], services: dict[str, dict]) -> None:
        """The reason this script exists.

        Ask the running database whether it accepts the password the API is
        being handed -- over the same path the API takes, which is the only
        path that tests anything. `initdb` writes a pg_hba.conf that trusts
        both the Unix socket and loopback:

            local   all   all                      trust
            host    all   all   127.0.0.1/32       trust
            host    all   all   ::1/128            trust
            host    all   all   all                scram-sha-256   <- appended

        Only that last line, which the postgres image appends, asks for a
        password. So `psql` with no -h, or with -h 127.0.0.1, succeeds with any
        password at all and this check would always pass. `-h db` resolves
        through Docker DNS to the container's bridge address, falls through to
        the scram line, and is exactly what the API's DATABASE_URL does.
        """
        if env.get("DATABASE_URL"):
            say(
                WARN,
                "DATABASE_URL is set, so this stack's `db` service is not in use",
                "Nothing here can test a managed instance's credentials.",
                "Rotate those with your provider, then update DATABASE_URL.",
            )
            return

        if "db" not in services or services["db"].get("State") != "running":
            say(WARN, "db is not running, so its password cannot be tested")
            return

        user = env.get("POSTGRES_USER", "chai")
        database = env.get("POSTGRES_DB", "chai")
        password = env.get("POSTGRES_PASSWORD", "")
        if not password:
            self.fail(
                "POSTGRES_PASSWORD is empty in .env",
                "Run `make preflight` -- it explains this one.",
            )
            return

        result = run(
            [
                *COMPOSE,
                "exec",
                "-T",
                # The NAME only: docker takes the value from this process's
                # environment, so the password is not in `docker`'s argv, where
                # any local account could read it.
                "-e",
                "PGPASSWORD",
                "db",
                "psql",
                "-h",
                "db",
                "-U",
                user,
                "-d",
                database,
                "-tAc",
                "select 1",
            ],
            env={**os.environ, "PGPASSWORD": password},
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            say(OK, "the database accepts the password in .env")
            return

        error = (result.stderr or result.stdout).strip()
        if "password authentication failed" not in error.casefold():
            self.fail(
                "the database did not answer",
                error.splitlines()[-1] if error else "(no output)",
                "",
                "This is not the password: the server refused or never replied.",
                "  docker compose logs db",
            )
            return

        self.fail(
            f"the database rejects the POSTGRES_PASSWORD in {ENV_FILE}",
            "",
            "PostgreSQL applied POSTGRES_PASSWORD once, when it initialized the",
            f"{VOLUME} volume. Editing it afterwards changed what the API",
            "presents and not what the database accepts, so the API cannot reach",
            "its own database and retries until it exits.",
            "",
            "Rotate it in PostgreSQL, which keeps every record:",
            "",
            "  docker compose exec db \\",
            f"    psql -U {user} -d {database} \\",
            f"    -c \"ALTER ROLE {user} WITH PASSWORD '<the value in .env>';\"",
            "",
            "  docker compose up -d --force-recreate api",
            "",
            "That psql has no -h, so it goes over the container's Unix socket,",
            "which pg_hba.conf trusts -- it needs no password, which is handy",
            "here and is also why the check above had to connect to -h db.",
            "",
            "Or discard the database and start again. THIS DELETES EVERY",
            "RECORD, AUDIT ENTRY AND RETAINED VERSION:",
            "",
            "  make backup      # first, if there is anything worth keeping",
            "  make prune",
        )

    def check_app_password(
        self, env: dict[str, str], services: dict[str, dict]
    ) -> None:
        """Can the API's restricted role log in with the password in .env?

        Unlike the owner's, this one is re-applied by the `migrate` job on every
        start, so a mismatch is fixed by running it again, not by an ALTER ROLE.
        """
        if env.get("DATABASE_URL") or env.get("APP_DATABASE_URL"):
            return  # a managed instance: nothing here can test its credentials
        state = services.get("db", {}).get("State")
        if state != "running":  # enum-ok: docker compose's container state name
            return
        password = env.get("APP_POSTGRES_PASSWORD", "")
        if not password:
            self.fail(
                "APP_POSTGRES_PASSWORD is empty in .env",
                "Run `make preflight` -- it explains this one.",
            )
            return
        user = env.get("APP_POSTGRES_USER", "chai_app")
        result = run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "-e",
                "PGPASSWORD",
                "db",
                "psql",
                "-h",
                "db",
                "-U",
                user,
                "-d",
                env.get("POSTGRES_DB", "chai"),
                "-tAc",
                "select 1",
            ],
            env={**os.environ, "PGPASSWORD": password},
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            say(OK, f"the restricted role {user!r} accepts APP_POSTGRES_PASSWORD")
            return
        self.fail(
            f"the restricted role {user!r} rejects APP_POSTGRES_PASSWORD",
            "The API connects as this role, so it cannot reach its database.",
            "The migrate job creates the role and re-applies this password on",
            "every start, so run it again:",
            "  docker compose up -d --force-recreate migrate api",
        )

    def check_reachable(self, env: dict[str, str]) -> None:
        """Is the API alive, and is the dashboard being served?

        The API is asked from inside the proxy container, which is on the
        `edge` network with it. That deliberately goes around Caddy's identity
        layer: /api/* answers 401 without the header the SSO front door sets,
        and this is a diagnostic, not an authorization test. `make
        check-isolation` is what asserts nobody else can take this path.
        """
        port = env.get("HTTP_PORT", "8080")

        health = self.wget("http://api:8000/api/health")
        if '"ok"' in health:
            say(OK, "the API answers /api/health")
        else:
            self.fail(
                "the API does not answer",
                (health.strip().splitlines() or ["(no response)"])[-1],
                "",
                "If the password check above failed, that is why.",
                "  docker compose logs api",
            )

        self.check_role(health)

        dashboard = self.wget("http://127.0.0.1:80/")
        if "<" in dashboard:
            say(OK, f"the dashboard is served at http://localhost:{port}/")
        else:
            self.fail(
                "the proxy serves nothing at /",
                "docs/app/index.html is mounted from the host and is built there:",
                "  pixi run build-app",
            )

    def check_role(self, health: str) -> None:
        """Is the API serving as a role that cannot undo the append-only triggers?

        The audit log and version history are append-only because of triggers, and
        a table's owner (or a superuser) can switch a trigger off in one statement.
        /api/health says which the API connected as (#48). A deployment that skipped
        the role split works, and silently has guarantees that bind its bugs only,
        so this says so.
        """
        if '"db_role":"restricted"' in health.replace(" ", ""):
            say(OK, "the API serves as a restricted database role")
        elif '"db_role":"owner"' in health.replace(" ", ""):
            self.fail(
                "the API serves as the table owner or a superuser",
                "The append-only triggers on the audit log and version history",
                "constrain the application's bugs, not the application, and not",
                "anything holding its credential: the owner can disable them.",
                "",
                "Set APP_POSTGRES_PASSWORD in .env (a different value from",
                "POSTGRES_PASSWORD), then:",
                "  docker compose up -d --force-recreate migrate api",
                "`migrate` creates the restricted role; the API then serves as it.",
            )
        else:
            say(WARN, "the API did not report which database role it uses")

    def wget(self, url: str) -> str:
        """Fetch a URL from inside the proxy container. Caddy's image has wget."""
        result = run([*COMPOSE, "exec", "-T", "proxy", "wget", "-q", "-O", "-", url])
        return result.stdout + result.stderr


def main() -> int:
    env = read_env(ENV_FILE)
    if not ENV_FILE.exists():
        print(f"\n  There is no {ENV_FILE}. Run `make env` first.\n")
        return 1

    print(f"\n  Checking the running stack against {ENV_FILE}:\n")
    doctor = Doctor()
    services = doctor.services()
    doctor.check_running(services)
    doctor.check_password(env, services)
    doctor.check_app_password(env, services)
    if services.get("proxy", {}).get("State") == "running":
        doctor.check_reachable(env)
    print()

    if doctor.problems:
        plural = "" if doctor.problems == 1 else "s"
        print(f"  {doctor.problems} problem{plural} found.\n")
        return 1
    print("  Nothing wrong here.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
