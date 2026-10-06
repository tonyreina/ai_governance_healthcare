#!/usr/bin/env python3
"""Refuse to start a production-shaped stack on settings that are not safe.

``compose.yaml`` can express "this variable must be set" -- ``${VAR:?...}`` --
and nothing more. It cannot say "and not *that* value". That gap is how a
sample password reaches production: ``POSTGRES_PASSWORD=replace-me`` is a
non-empty value, so the guard passes and the database comes up with a password
published in a public repository.

So this runs before ``make up`` and checks the things compose cannot:

* the database password is present, not a known placeholder, and not trivial;
* the identity sources are either unset (the proxy then rejects every request,
  which is a loud, safe failure) or Caddy placeholders -- never literals, which
  would stamp every visitor as the same person;
* the stack is not published to a non-loopback address while speaking plain
  HTTP.

Exits non-zero with an explanation. ``make up FORCE=1`` overrides, for the
genuine case of a reverse proxy terminating TLS somewhere this cannot see.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_FILE = Path(".env")

# Values that look set but mean "I have not done this yet". Compared casefolded.
PLACEHOLDERS = {
    "replace-me-before-first-run",
    "replace-me",
    "changeme",
    "change-me",
    "password",
    "postgres",
    "secret",
    "chai",
    "dev-only-not-a-secret",
    "test",
}


def read_env(path: Path) -> dict[str, str]:
    """Parse the subset of dotenv syntax compose itself accepts."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def check(env: dict[str, str]) -> list[str]:
    problems: list[str] = []

    password = env.get("POSTGRES_PASSWORD", "")
    database_url = env.get("DATABASE_URL", "")
    if not database_url:
        if not password:
            problems.append(
                "POSTGRES_PASSWORD is empty. Generate one:\n"
                "      openssl rand -base64 32"
            )
        elif password.casefold() in PLACEHOLDERS:
            problems.append(
                f"POSTGRES_PASSWORD is the placeholder {password!r}. It is a real\n"
                "    password as far as compose is concerned, and it is published in\n"
                "    this repository. Generate one:  openssl rand -base64 32"
            )
        elif len(password) < 16:
            problems.append(
                f"POSTGRES_PASSWORD is {len(password)} characters. Use at least 16:\n"
                "      openssl rand -base64 32"
            )

    # An identity source is safe when it is empty (the proxy 401s every request)
    # or a Caddy placeholder (the value comes from the SSO front door per
    # request). A literal makes every visitor the same person.
    for name in ("IDENTITY_ID_SOURCE", "IDENTITY_EMAIL_SOURCE"):
        value = env.get(name, "")
        if value and not value.startswith("{"):
            problems.append(
                f"{name}={value!r} is a literal, not a Caddy placeholder.\n"
                "    Every request would be stamped as that one identity:\n"
                "    anyone who reaches the port becomes them and owns every\n"
                "    project, and nothing in the UI says so.\n"
                "    Use a placeholder naming the header your SSO front door\n"
                "    sets -- see the blocks in .env.example -- or run the local\n"
                "    stack with `make dev`, which supplies a dev identity safely."
            )

    bind = env.get("HTTP_BIND", "127.0.0.1")
    site = env.get("SITE_ADDRESS", "http://:80")
    serves_plain_http = site.startswith("http://")
    if bind not in ("127.0.0.1", "::1", "localhost") and serves_plain_http:
        problems.append(
            f"HTTP_BIND={bind} publishes the stack to the network while\n"
            f"    SITE_ADDRESS={site} serves plain HTTP. Either set SITE_ADDRESS to a\n"
            "    hostname so Caddy gets a certificate, or leave HTTP_BIND on loopback\n"
            "    and terminate TLS in front. Override with `make up FORCE=1` if\n"
            "    something this cannot see already terminates TLS."
        )

    return problems


def main() -> int:
    if os.environ.get("FORCE"):
        print("preflight: skipped (FORCE=1)")
        return 0

    problems = check(read_env(ENV_FILE))
    if not problems:
        print("preflight: ok")
        return 0

    print(f"\n  Refusing to start. {len(problems)} problem(s) in {ENV_FILE}:\n")
    for i, problem in enumerate(problems, 1):
        print(f"  {i}. {problem}\n")
    print("  Fix these, or run `make up FORCE=1` if you are certain.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
