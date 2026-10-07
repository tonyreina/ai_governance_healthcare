#!/usr/bin/env python3
"""The Caddy edge, exercised against a real Caddy: identity, headers, body cap.

This is the one part of the stack no other test touched, and it was broken:
proxy/Caddyfile stripped the upstream providers' headers BEFORE the step that
reads one of them through a placeholder, so every cloud configuration this
repository documents resolved to an empty identity and answered 401 to every
request. The only setting that worked was a literal string -- the single
configuration the rest of the review exists to prevent.

Nothing in Python could have caught that. It needs Caddy parsing the real
Caddyfile and an upstream reporting what arrived.

The security headers and the 2MB request cap are exposed to the same class of
mistake, because in a Caddyfile *where* a directive sits decides which
responses it applies to. `header` at the site level covers /api/* too; the same
block moved inside the static `handle` leaves every JSON response without so
much as nosniff, and looks identical until somebody reads a response. Likewise
an absent `request_body` cap is invisible from Python, because the API enforces
its own limit and answers 413 either way -- the only way to tell the edge cap
apart is to ask the upstream whether it ever saw the request.

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

# Keep in step with the `header` block in proxy/Caddyfile. A value changed
# there and not here fails loudly, which is the point: these are the response
# headers the dashboard's threat model assumes, not incidental formatting.
#
# Strict-Transport-Security is in this list on purpose even though the rig only
# speaks plain HTTP. Caddy sends it unconditionally, and that is the intent:
# browsers ignore HSTS on a plaintext response, so it costs nothing behind a
# cloud front door that terminates TLS and it is load-bearing the moment
# SITE_ADDRESS is a hostname and Caddy is the public edge. A conditional
# `header` would be the bug -- the header would then be missing exactly where
# it matters.
EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "content-security-policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src "
        "'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src "
        "'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}

# proxy/Caddyfile caps /api/* bodies with `max_size 2MB`. Caddy parses that
# with SI units, so it is 2,000,000 bytes and NOT 2 MiB -- worth pinning,
# because `2MB` reads like the larger number and the 97KB difference is exactly
# the kind of thing nobody notices until a document sits on the boundary.
EDGE_BODY_CAP = 2_000_000

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

# The upstream. It echoes the headers it was handed -- which is how the
# identity checks see what Caddy actually forwarded -- and records how many
# body bytes it managed to read for each request, which is what the body-cap
# check needs. /_seen returns that log and is not itself recorded.
ECHO = """
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
SEEN = []
class H(BaseHTTPRequestHandler):
    def respond(self):
        if self.path.endswith("/_seen"):
            body = json.dumps(SEEN).encode()
        else:
            declared = int(self.headers.get("Content-Length") or 0)
            read = 0
            truncated = False
            try:
                while read < declared:
                    chunk = self.rfile.read(min(65536, declared - read))
                    if not chunk:
                        truncated = True
                        break
                    read += len(chunk)
            except Exception:
                truncated = True
            SEEN.append({"method": self.command, "path": self.path,
                         "declared": declared, "read": read,
                         "truncated": truncated})
            if truncated:
                return
            body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = respond
    do_POST = respond
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


def request(
    path: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    body: bytes | None = None,
) -> tuple[int, str, dict[str, str]]:
    """Return (status, body, response headers lowercased) for one request.

    Response headers come back because half the checks below are about what
    Caddy puts on the response rather than what it forwards.
    """
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", headers=headers, method=method, data=body
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            got = response.read().decode()
            status, raw = response.status, response.headers
    except urllib.error.HTTPError as exc:
        got, status, raw = exc.read().decode(), exc.code, exc.headers
    return status, got, {k.lower(): v for k, v in raw.items()}


def get(path: str, headers: dict[str, str]) -> tuple[int, str]:
    status, body, _ = request(path, headers)
    return status, body


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


def check_security_headers(label: str, path: str, headers: dict[str, str]) -> None:
    """Every response Caddy serves must carry the whole `header` block.

    Run against /api/* as well as the dashboard: the block lives at the site
    level precisely so the JSON responses get it, and a future edit that moves
    it back inside the static `handle` would still pass a dashboard-only check.
    """
    status, _, got = request(path, headers)
    check(f"{label}: responds", status in (200, 401), f"HTTP {status}")
    for name, want in EXPECTED_HEADERS.items():
        check(
            f"{label}: {name}",
            got.get(name) == want,
            f"got {got.get(name)!r}",
        )
    # `-Server` in the Caddyfile. Caddy announces itself otherwise, and the
    # version it announces is a free hint about which bugs apply.
    check(f"{label}: no Server header", "server" not in got, got.get("server", ""))


def seen_by_upstream(headers: dict[str, str]) -> list[dict]:
    """The requests the echo upstream has served, newest last."""
    _, body = get("/api/_seen", headers)
    return json.loads(body)


def check_edge_body_cap(headers: dict[str, str]) -> None:
    """The 2MB cap must be enforced BY CADDY, not merely by the API.

    The API enforces its own limit and answers 413 too, so a status code alone
    proves nothing about the edge. What distinguishes them is what the upstream
    was able to read.

    Note what Caddy's `request_body max_size` does and does not do. It does NOT
    reject on Content-Length before dialing: the upstream still sees the
    request line and headers, and `reverse_proxy` streams the body into it.
    What the directive installs is a reader that stops dead at the cap -- so
    the upstream reads at most 2,000,000 bytes, never the complete document,
    the connection is torn down under it, and the client gets 413. The
    guarantee is therefore "no handler ever receives a whole over-size body",
    which is the one that matters: the oversized write cannot happen, and the
    append-only copy of it in project_version cannot happen either.

    Asserting "the upstream never saw the request at all" would be a stricter
    claim than Caddy makes, and would start failing the day someone looks.
    """
    under = b"a" * 4096
    status, _, _ = request(
        "/api/projects/small",
        {**headers, "Content-Type": "application/json"},
        method="POST",
        body=under,
    )
    check("a body under the cap is forwarded", status == 200, f"HTTP {status}")
    small = [r for r in seen_by_upstream(headers) if r["path"] == "/api/projects/small"]
    check(
        "the under-cap body arrives whole",
        bool(small) and small[-1]["read"] == len(under) and not small[-1]["truncated"],
        f"upstream saw {small[-1:]}",
    )

    over = b"a" * (EDGE_BODY_CAP + 512 * 1024)
    status, _, _ = request(
        "/api/projects/big",
        {**headers, "Content-Type": "application/json"},
        method="POST",
        body=over,
    )
    check(
        f"a body over {EDGE_BODY_CAP} bytes is refused",
        status == 413,
        f"HTTP {status}",
    )

    big = [r for r in seen_by_upstream(headers) if r["path"] == "/api/projects/big"]
    check(
        "Caddy cut the over-size body off at the cap",
        bool(big) and big[-1]["read"] <= EDGE_BODY_CAP,
        f"upstream read {big[-1]['read'] if big else None} of {len(over)}",
    )
    check(
        "the API never receives a complete over-size body",
        bool(big) and big[-1]["truncated"],
        f"upstream saw {big[-1:]}",
    )


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

        # ---------------------------------------------------------------
        # The response headers and the edge body cap. #20 added both and
        # nothing asserted either; see the module docstring for why a Python
        # test of the API cannot stand in for this.
        # ---------------------------------------------------------------
        oauth2 = FRONT_DOORS[3]
        start_caddy(workdir, oauth2[1])
        signed_in = oauth2[2]

        check_security_headers("an authenticated /api response", "/api/me", signed_in)
        check_security_headers("an anonymous /api 401", "/api/me", {})
        check_security_headers("the dashboard", "/", {})

        # Cache-Control belongs to the static handler alone: the dashboard is
        # rebuilt at a URL that never changes, so a cached copy is a stale app.
        _, _, dash = request("/", {})
        check(
            "the dashboard is served no-cache",
            dash.get("cache-control") == "no-cache",
            f"got {dash.get('cache-control')!r}",
        )

        check_edge_body_cap(signed_in)
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
