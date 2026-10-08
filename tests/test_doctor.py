#!/usr/bin/env python3
"""scripts/doctor.py: the role checks added for the two-role split (#48).

`make doctor` is what an operator runs when the stack is up and misbehaving, and
what a deployment that skipped the role split needs in order to find out. The
append-only triggers bind a role only if it cannot disable them, and a stack where
the API serves as the owner works perfectly while having guarantees that constrain
the application's bugs and not the application.

doctor drives `docker compose`, so what is under test is how it reads docker's
answers. A stand-in `docker` on PATH gives scripted answers and records the
calls; the checks are on doctor's verdicts and on what it asked.

    pixi run test-doctor
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCTOR = ROOT / "scripts" / "doctor.py"

failures: list[str] = []

ENV = (
    "POSTGRES_PASSWORD=owner-password-0123456789\n"
    "APP_POSTGRES_PASSWORD=app-password-0123456789\n"
    "IDENTITY_ID_SOURCE={http.request.header.X-Forwarded-User}\n"
)

SERVICES = [
    {"Service": name, "State": "running", "Health": "healthy"}
    for name in ("db", "api", "proxy")
]

# The stand-in. SCENARIO is JSON in the environment: what each question gets.
STUB = r"""#!/usr/bin/env python3
import json, os, sys
sc = json.loads(os.environ["SCENARIO"])
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as f:
    record = {"argv": args, "pgpassword": os.environ.get("PGPASSWORD")}
    f.write(json.dumps(record) + "\n")
joined = " ".join(args)
if "ps --format json" in joined or "ps --format" in joined:
    print("\n".join(json.dumps(r) for r in sc["services"]))
elif "psql" in joined:
    user = args[args.index("-U") + 1]
    ok = sc["logins"].get(user, False)
    if ok:
        print("1")
    else:
        msg = 'FATAL: password authentication failed for user "%s"' % user
        print(msg, file=sys.stderr)
        sys.exit(2)
elif "wget" in joined and "/api/health" in joined:
    print(sc["health"])
elif "wget" in joined:
    print("<!doctype html><html></html>")
"""

HEALTH = {
    "restricted": '{"status":"ok","db_role":"restricted"}',
    "owner": '{"status":"ok","db_role":"owner"}',
    "unknown": '{"status":"ok"}',
}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def doctor(health: str, logins: dict[str, bool], env_text: str = ENV):
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / ".env").write_text(env_text)
        bindir = work / "bin"
        bindir.mkdir()
        stub = bindir / "docker"
        stub.write_text(STUB)
        stub.chmod(0o755)
        calls = work / "calls.jsonl"
        done = subprocess.run(
            [sys.executable, str(DOCTOR)],
            capture_output=True,
            text=True,
            cwd=work,
            env={
                **os.environ,
                "PATH": f"{bindir}:{os.environ['PATH']}",
                "SCENARIO": json.dumps(
                    {"services": SERVICES, "health": health, "logins": logins}
                ),
                "CALLS": str(calls),
            },
        )
        recorded = (
            [json.loads(x) for x in calls.read_text().splitlines()]
            if (calls.exists())
            else []
        )
    return done, recorded


def main() -> int:
    print("The API serves as a restricted role")
    done, calls = doctor(HEALTH["restricted"], {"chai": True, "chai_app": True})
    check("doctor reports nothing wrong", done.returncode == 0, done.stdout[-400:])
    check(
        "and says the API's role is restricted",
        "restricted database role" in done.stdout,
    )
    check(
        "and that the restricted login works",
        "accepts APP_POSTGRES_PASSWORD" in done.stdout,
        done.stdout[-400:],
    )

    print("The API serves as the owner: the guarantees bind bugs only")
    done, _ = doctor(HEALTH["owner"], {"chai": True, "chai_app": True})
    check("doctor fails", done.returncode == 1, done.stdout[-300:])
    check(
        "and says why in terms of the triggers",
        "table owner or a superuser" in done.stdout
        and "append-only triggers" in done.stdout,
        done.stdout[-500:],
    )
    check(
        "and says what to run",
        "force-recreate migrate api" in done.stdout
        and "APP_POSTGRES_PASSWORD" in done.stdout,
    )

    print("A health answer that does not say is a warning, not a pass")
    done, _ = doctor(HEALTH["unknown"], {"chai": True, "chai_app": True})
    check(
        "doctor does not claim the role is restricted",
        "restricted database role" not in done.stdout
        and "did not report" in done.stdout,
        done.stdout[-300:],
    )

    print("The restricted role's password")
    done, calls = doctor(HEALTH["restricted"], {"chai": True, "chai_app": False})
    check("a rejected login fails doctor", done.returncode == 1)
    check(
        "and says to run migrate again, which re-applies the password",
        "force-recreate migrate api" in done.stdout
        and "rejects APP_POSTGRES_PASSWORD" in done.stdout,
        done.stdout[-500:],
    )
    app_logins = [c for c in calls if "chai_app" in c["argv"]]
    check(
        "it tried the app role with the app password, from the environment",
        bool(app_logins)
        and app_logins[0]["pgpassword"] == "app-password-0123456789"
        and not any("app-password-0123456789" in a for a in app_logins[0]["argv"]),
        str(app_logins),
    )

    done, _ = doctor(
        HEALTH["restricted"],
        {"chai": True, "chai_app": True},
        ENV.replace("APP_POSTGRES_PASSWORD=app-password-0123456789\n", ""),
    )
    check(
        "an empty APP_POSTGRES_PASSWORD fails and points at preflight",
        done.returncode == 1 and "APP_POSTGRES_PASSWORD is empty" in done.stdout,
        done.stdout[-300:],
    )

    done, calls = doctor(
        HEALTH["restricted"],
        {"chai": True},
        ENV + "APP_DATABASE_URL=postgresql://api@managed/db\n",
    )
    check(
        "with a managed APP_DATABASE_URL it does not try a local login",
        not [c for c in calls if "chai_app" in c["argv"]],
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("doctor checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
