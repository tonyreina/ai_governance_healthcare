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
import re
import sys
from pathlib import Path

ENV_FILE = Path(".env")

# The defaults compose.yaml applies with `${VAR:-default}`. They are repeated here
# because this reads `.env` ALONE and has to decide what compose will do with it.
# tests/test_preflight.py fails if either drifts from compose.yaml.
DEFAULT_BIND = "127.0.0.1"
GOOGLE_PREFIX = "accounts.google.com:"
# HTTP header names are case-insensitive, and Caddy placeholders keep the case
# the operator wrote.
GOOGLE_HEADER = re.compile(r"x-goog-authenticated-user", re.IGNORECASE)
DEFAULT_SITE = "http://:80"

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


_EXPORT = re.compile(r"^export\s+")
_COMMENT = re.compile(r"\s#")


def _value(raw: str) -> str:
    """One value, read the way compose reads it.

    A quoted value is whatever is between the quotes, `#` and all; anything after
    the closing quote (a trailing comment) is dropped. An UNQUOTED value ends at the
    first whitespace followed by `#`, so `abc # a long note` is `abc`. That matters
    for a safety check: counting the note would make a 3-character password look
    long enough, and compose would use the 3 characters.
    """
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        quote, i = raw[0], 1
        while i < len(raw):
            if quote == '"' and raw[i] == "\\":
                i += 2
                continue
            if raw[i] == quote:
                return raw[1:i]
            i += 1
        return raw  # unterminated: compose rejects it; do not guess
    cut = _COMMENT.search(raw)
    return (raw[: cut.start()] if cut else raw).strip()


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
        out[_EXPORT.sub("", key.strip())] = _value(value)
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

    # The API serves as a RESTRICTED database role, created by the `migrate` job
    # from this password (#48). It must exist, be as strong as the owner's, and
    # differ from it: the point of two roles is that the credential in the API
    # container is not the owner's, and a shared password would make it one.
    if not env.get("APP_DATABASE_URL"):
        app_password = env.get("APP_POSTGRES_PASSWORD", "")
        if not app_password:
            problems.append(
                "APP_POSTGRES_PASSWORD is empty. It is the password of the\n"
                "    restricted role the API connects as; the owner's password\n"
                "    (POSTGRES_PASSWORD) stays in the one-shot migrate job. Generate\n"
                "    a DIFFERENT one:\n"
                "      openssl rand -base64 32"
            )
        elif app_password.casefold() in PLACEHOLDERS:
            problems.append(
                f"APP_POSTGRES_PASSWORD is the placeholder {app_password!r}.\n"
                "    Generate one:  openssl rand -base64 32"
            )
        elif len(app_password) < 16:
            problems.append(
                f"APP_POSTGRES_PASSWORD is {len(app_password)} characters. Use at "
                "least 16:\n      openssl rand -base64 32"
            )
        elif app_password == password:
            problems.append(
                "APP_POSTGRES_PASSWORD is the same as POSTGRES_PASSWORD. Then the\n"
                "    credential in the API container is the owner's, which can\n"
                "    disable the append-only triggers, and the two roles protect\n"
                "    nothing. Generate a different one:  openssl rand -base64 32"
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

    # Google IAP prefixes its identity headers with "accounts.google.com:". The
    # API strips it only if IDENTITY_STRIP_PREFIX says to, and access lists are
    # matched against the stripped id. Compose passes the variable through
    # EMPTY by default, so a Google source with no prefix stores prefixed ids,
    # which stop matching the day the same people arrive any other way (a move to
    # Cloud Run's IDENTITY_MODE=iap, or simply setting the prefix later). Every
    # project then vanishes from its owner with no error anywhere (#35).
    if any(
        GOOGLE_HEADER.search(env.get(name, ""))
        for name in (
            "IDENTITY_ID_SOURCE",
            "IDENTITY_NAME_SOURCE",
            "IDENTITY_EMAIL_SOURCE",
        )
    ):
        prefix = env.get("IDENTITY_STRIP_PREFIX", "")
        if prefix != GOOGLE_PREFIX:
            problems.append(
                f"IDENTITY_STRIP_PREFIX={prefix!r}, but an identity source reads a\n"
                "    Google IAP header, whose values arrive as\n"
                f"    {GOOGLE_PREFIX}person@hospital.org. Set\n"
                f"      IDENTITY_STRIP_PREFIX={GOOGLE_PREFIX}\n"
                "    before anyone signs in. Without it every access list is built\n"
                "    from prefixed ids, and the day you move to Cloud Run's\n"
                "    IDENTITY_MODE=iap, or set the prefix later, every project\n"
                "    silently disappears from its owner."
            )

    # `${VAR:-default}` substitutes the default when the variable is unset OR EMPTY,
    # so `HTTP_BIND=` and `SITE_ADDRESS=` mean the defaults. Reading an empty
    # SITE_ADDRESS as "not plain HTTP" waved through a bind to the whole network
    # while compose served plain HTTP on it.
    bind = env.get("HTTP_BIND") or DEFAULT_BIND
    site = env.get("SITE_ADDRESS") or DEFAULT_SITE
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
