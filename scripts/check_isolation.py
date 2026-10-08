#!/usr/bin/env python3
"""Prove, against a running stack, that the API is reachable only through the proxy.

``make check-isolation`` runs this. The whole identity model is "trust a header",
which is only safe if nothing else can reach the API, so this is the check an
operator is told to run after any networking change and to keep in post-deploy
automation. In automation nobody reads the output: the exit code is the whole
signal. It used to print step 3's response and swallow every failure with
``|| true``, and print ``docker compose ps`` for a human to look at, so it exited
0 whatever it found (#56).

It asserts three things, and exits non-zero if any fails:

1. no service named ``api`` or ``db`` publishes a host port;
2. a direct TCP connection to the API's port on the host is refused;
3. an identity header a client sends through the proxy does not become the
   identity the API sees. The test is for ABSENCE of the forged value, because
   the legitimate identity varies by deployment.

The decisions are small pure functions so ``tests/test_check_isolation.py`` can
break each one and demand it notice. A check that is never shown to fail is a
claim, not a control.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request

COMPOSE = ["docker", "compose"]
GUARDED_SERVICES = ("api", "db")
FORGED = "attacker@evil.test"
UNAUTHENTICATED = 401


def parse_ps(text: str) -> list[dict]:
    """Rows of ``docker compose ps --format json``, which is NDJSON or an array."""
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def published_ports(rows: list[dict]) -> list[str]:
    """Host ports published by the guarded services, as ``service:port`` strings.

    A publisher with ``PublishedPort`` 0 is an exposed container port with no
    host binding, which is not reachable from the host and is fine.
    """
    found = []
    for row in rows:
        if row.get("Service") not in GUARDED_SERVICES:
            continue
        for pub in row.get("Publishers") or []:
            if pub.get("PublishedPort"):
                found.append(f"{row['Service']}:{pub['PublishedPort']}")
    return found


def published_problems(rows: list[dict]) -> list[str]:
    if not any(row.get("Service") in GUARDED_SERVICES for row in rows):
        # Nothing to inspect is not a pass: it is a stack that is not up.
        return ["no api or db service found: is the stack running?"]
    return [
        f"{port} is published on the host; the API must be reachable only "
        "through the proxy. Look for a `ports:` entry."
        for port in published_ports(rows)
    ]


def reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def direct_access_problems(is_reachable: bool, port: int) -> list[str]:
    if not is_reachable:
        return []
    return [
        f"the API answers a direct connection on 127.0.0.1:{port}. Anyone who can "
        "reach it can set the identity header themselves and be anyone."
    ]


def forged_identity_problems(status: int | None, body: str) -> list[str]:
    """The forged identity must not come back as the caller's identity.

    A 401 is the proxy refusing a request with no identity, which is correct
    when the front door set nothing. A 200 is correct only if the body does not
    contain the forged value. Anything else (no answer, a 5xx) proves nothing,
    so it fails rather than passing by silence.
    """
    if status is None:
        return ["the proxy did not answer, so the strip could not be checked"]
    if status == UNAUTHENTICATED:
        return []
    if status == 200:
        if FORGED in body:
            return [
                f"the proxy forwarded the client's identity header: /api/me "
                f"answered as {FORGED}"
            ]
        return []
    return [f"/api/me answered {status}, so the strip could not be checked"]


def ask_proxy(port: int) -> tuple[int | None, str]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/me",
        headers={
            "X-Auth-Request-User": FORGED,
            "X-Auth-Request-Email": FORGED,
            "X-Auth-Request-Name": FORGED,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except OSError:
        return None, ""


def main() -> int:
    http_port = int(os.environ.get("HTTP_PORT") or 8080)
    api_port = int(os.environ.get("API_HOST_PORT") or 8000)
    failures: list[str] = []

    def step(title: str, problems: list[str]) -> None:
        print(f"{title}\n  {'ok' if not problems else 'FAIL'}")
        for problem in problems:
            print(f"    {problem}")
        failures.extend(problems)

    try:
        ps = subprocess.run(
            [*COMPOSE, "ps", "--format", "json"], capture_output=True, text=True
        )
        rows = parse_ps(ps.stdout) if ps.returncode == 0 else []
    except (OSError, ValueError):  # no docker, or output that is not JSON
        rows = []
    step("1. no published port on api or db", published_problems(rows))
    step(
        "2. a direct connection to the API from the host is refused",
        direct_access_problems(reachable("127.0.0.1", api_port), api_port),
    )
    status, body = ask_proxy(http_port)
    step(
        "3. a forged identity sent through the proxy does not become the identity",
        forged_identity_problems(status, body),
    )
    print("isolation holds" if not failures else f"{len(failures)} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
