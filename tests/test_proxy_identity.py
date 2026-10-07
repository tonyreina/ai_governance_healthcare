#!/usr/bin/env python3
"""The Caddy identity handoff, exercised against a real Caddy.

This is the one part of the stack no other test touched, and it was broken:
proxy/Caddyfile stripped the upstream providers' headers BEFORE the step that
reads one of them through a placeholder, so every cloud configuration this
repository documents resolved to an empty identity and answered 401 to every
request. The only setting that worked was a literal string -- the single
configuration the rest of the review exists to prevent.

Nothing in Python could have caught that. It needs Caddy parsing the real
Caddyfile and an upstream reporting what arrived.

    pixi run test-proxy        (needs Docker; skips cleanly without it)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CADDYFILE = ROOT / "proxy" / "Caddyfile"
PORT = 18099
NET = "chai-proxy-test"

# What each front door actually puts on the request, and how .env.example says
# to read it. Keep in step with the identity blocks in .env.example.
FRONT_DOORS = [
    (
        "Google Cloud IAP",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Goog-Authenticated-User-Id}",
            "IDENTITY_NAME_SOURCE": (
                "{http.request.header.X-Goog-Authenticated-User-Email}"
            ),
            "IDENTITY_EMAIL_SOURCE": (
                "{http.request.header.X-Goog-Authenticated-User-Email}"
            ),
        },
        {
            "X-Goog-Authenticated-User-Id": "accounts.google.com:1234",
            "X-Goog-Authenticated-User-Email": "accounts.google.com:cmo@hospital.org",
        },
        {"X-Auth-Request-User": "accounts.google.com:1234"},
    ),
    (
        "AWS ALB + OIDC",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Amzn-Oidc-Identity}",
            "IDENTITY_NAME_SOURCE": "{http.request.header.X-Amzn-Oidc-Identity}",
            "IDENTITY_EMAIL_SOURCE": "{http.request.header.X-Amzn-Oidc-Identity}",
        },
        {"X-Amzn-Oidc-Identity": "sub-abc-123"},
        {"X-Auth-Request-User": "sub-abc-123"},
    ),
    (
        "Azure Easy Auth",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Ms-Client-Principal-Id}",
            "IDENTITY_NAME_SOURCE": "{http.request.header.X-Ms-Client-Principal-Name}",
            "IDENTITY_EMAIL_SOURCE": "{http.request.header.X-Ms-Client-Principal-Name}",
        },
        {
            "X-Ms-Client-Principal-Id": "entra-oid-999",
            "X-Ms-Client-Principal-Name": "cmo@hospital.org",
        },
        {
            "X-Auth-Request-User": "entra-oid-999",
            "X-Auth-Request-Email": "cmo@hospital.org",
        },
    ),
    (
        "oauth2-proxy",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Forwarded-User}",
            "IDENTITY_NAME_SOURCE": (
                "{http.request.header.X-Forwarded-Preferred-Username}"
            ),
            "IDENTITY_EMAIL_SOURCE": "{http.request.header.X-Forwarded-Email}",
        },
        {
            "X-Forwarded-User": "cmo",
            "X-Forwarded-Preferred-Username": "C. M. Officer",
            "X-Forwarded-Email": "cmo@hospital.org",
        },
        {
            "X-Auth-Request-User": "cmo",
            "X-Auth-Request-Email": "cmo@hospital.org",
        },
    ),
]

ECHO = """
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
HTTPServer(("0.0.0.0", 8000), H).serve_forever()
"""

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def docker(*args: str, check_rc: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check_rc
    )


def get(path: str, headers: dict[str, str]) -> tuple[int, str]:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def start_caddy(workdir: Path, env: dict[str, str]) -> None:
    docker("rm", "-f", "chai-test-caddy")
    args = [
        "run",
        "-d",
        "--name",
        "chai-test-caddy",
        "--network",
        NET,
        "-p",
        f"{PORT}:80",
        "-v",
        f"{CADDYFILE}:/etc/caddy/Caddyfile:ro",
        "-v",
        f"{workdir}/srv:/srv/app:ro",
        "-e",
        "SITE_ADDRESS=http://:80",
    ]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    args.append("caddy:2")
    docker(*args)
    for _ in range(40):
        try:
            get("/", {})
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Caddy did not come up")


def main() -> int:
    if not shutil.which("docker") or docker("info").returncode != 0:
        print("docker unavailable; skipping proxy identity checks")
        return 0

    workdir = Path(tempfile.mkdtemp(prefix="chai-proxy-test-"))
    (workdir / "srv").mkdir()
    (workdir / "srv" / "index.html").write_text("app")
    (workdir / "echo.py").write_text(ECHO)

    docker("network", "create", NET)
    docker("rm", "-f", "chai-test-echo")
    docker(
        "run",
        "-d",
        "--name",
        "chai-test-echo",
        "--network",
        NET,
        "--network-alias",
        "api",
        "-v",
        f"{workdir}/echo.py:/echo.py:ro",
        "python:3.12-slim",
        "python",
        "/echo.py",
    )

    try:
        for name, env, sent, expected in FRONT_DOORS:
            start_caddy(workdir, env)
            status, body = get("/api/me", sent)
            if status != 200:
                check(f"{name}: request is forwarded", False, f"HTTP {status}")
                continue
            check(f"{name}: request is forwarded", True)
            got = {k.lower(): v for k, v in json.loads(body).items()}
            for header, want in expected.items():
                check(
                    f"{name}: {header} = {want!r}",
                    got.get(header.lower()) == want,
                    f"got {got.get(header.lower())!r}",
                )
            leaked = [
                k
                for k in got
                if k.startswith(("x-goog", "x-amzn", "x-ms-client", "x-forwarded-user"))
                or k in ("x-forwarded-email", "x-forwarded-preferred-username")
            ]
            check(
                f"{name}: no provider header reaches the API",
                not leaked,
                ", ".join(leaked),
            )

        # The canonical headers must never be accepted from the client.
        start_caddy(workdir, FRONT_DOORS[0][1])
        status, _ = get(
            "/api/me",
            {"X-Auth-Request-User": "evil@x", "X-Auth-Request-Email": "evil@x"},
        )
        check("a forged X-Auth-Request-* is refused", status == 401, f"HTTP {status}")

        status, _ = get("/api/me", {})
        check("a request with no identity is refused", status == 401, f"HTTP {status}")

        # An unset source must fail closed, not fall back to something usable.
        start_caddy(
            workdir,
            {
                "IDENTITY_ID_SOURCE": "",
                "IDENTITY_NAME_SOURCE": "",
                "IDENTITY_EMAIL_SOURCE": "",
            },
        )
        status, _ = get("/api/me", {"X-Forwarded-Email": "cmo@hospital.org"})
        check("an unset identity source fails closed", status == 401, f"HTTP {status}")
    finally:
        docker("rm", "-f", "chai-test-caddy")
        docker("rm", "-f", "chai-test-echo")
        docker("network", "rm", NET)
        shutil.rmtree(workdir, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("proxy identity checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
