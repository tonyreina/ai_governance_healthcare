#!/usr/bin/env python3
"""scripts/check_isolation.py: the check behind `make check-isolation`, shown to fail.

The docs tell operators this target "asserts all of this" and to keep it in
post-deploy automation. In automation the exit code is the whole signal, and the
shell it used to be exited 0 whatever it found: step 3 ended in `|| true` and
step 1 printed `docker compose ps` for a human (#56). A check that is never shown
to fail is a claim, not a control, so this breaks each decision on purpose and
demands the checker notice.

The decisions are pure functions, so most of this needs no Docker. Step 2 uses a
real listening socket, and step 3 a real local HTTP server that either strips the
forged header or echoes it back as the identity. The run against the real stack is
in tests/test_stack.py.

    pixi run test-isolation
"""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "check_isolation", ROOT / "scripts" / "check_isolation.py"
)
ci = importlib.util.module_from_spec(spec)
sys.modules["check_isolation"] = ci
spec.loader.exec_module(ci)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def row(service: str, *published: int) -> dict:
    return {
        "Service": service,
        "Publishers": [
            {"URL": "0.0.0.0", "TargetPort": 80, "PublishedPort": p, "Protocol": "tcp"}
            for p in published
        ]
        or [{"URL": "", "TargetPort": 8000, "PublishedPort": 0, "Protocol": "tcp"}],
    }


class Identity(BaseHTTPRequestHandler):
    """A stand-in for /api/me. `forwards` decides whether it trusts the header."""

    forwards = False

    def do_GET(self):
        who = (
            self.headers.get("X-Auth-Request-Email")
            if self.forwards
            else "real@hospital.example"
        )
        body = json.dumps({"id": who, "email": who}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(forwards: bool) -> tuple[HTTPServer, int]:
    handler = type("H", (Identity,), {"forwards": forwards})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    print("Step 1: published ports")
    safe = [row("proxy", 8080), row("api"), row("db")]
    check(
        "a stack with only the proxy published passes", not ci.published_problems(safe)
    )
    for service in ("api", "db"):
        broken = [row("proxy", 8080), row(service, 5555)]
        check(
            f"a published port on {service} is noticed",
            bool(ci.published_problems(broken)),
        )
    check("a stack that is not up is not a pass", bool(ci.published_problems([])))
    check(
        "an unrelated service's port is not this check's business",
        not ci.published_problems([*safe, row("metrics", 9100)]),
    )
    nd = "\n".join(json.dumps(r) for r in safe)
    check("compose's NDJSON output parses", len(ci.parse_ps(nd)) == 3)
    check("so does a JSON array", len(ci.parse_ps(json.dumps(safe))) == 3)

    print("Step 2: a direct connection to the API")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    open_port = listener.getsockname()[1]
    check(
        "a listening port is noticed",
        bool(
            ci.direct_access_problems(ci.reachable("127.0.0.1", open_port), open_port)
        ),
    )
    listener.close()
    closed = free_port()
    check(
        "a refused connection passes",
        not ci.direct_access_problems(ci.reachable("127.0.0.1", closed), closed),
    )

    print("Step 3: a forged identity through the proxy")
    stripping, strip_port = serve(forwards=False)
    status, body = ci.ask_proxy(strip_port)
    check(
        "a proxy that strips the header passes",
        not ci.forged_identity_problems(status, body),
        str(ci.forged_identity_problems(status, body)),
    )
    stripping.shutdown()

    forwarding, fwd_port = serve(forwards=True)
    status, body = ci.ask_proxy(fwd_port)
    check(
        "a proxy that forwards the header is noticed",
        bool(ci.forged_identity_problems(status, body)),
        f"{status} {body}",
    )
    forwarding.shutdown()

    check(
        "a 401 passes: no identity, refused",
        not ci.forged_identity_problems(401, "No authenticated identity."),
    )
    status, body = ci.ask_proxy(free_port())
    check(
        "no answer at all is not a pass",
        status is None and bool(ci.forged_identity_problems(status, body)),
    )
    check("a 5xx is not a pass", bool(ci.forged_identity_problems(502, "")))

    print("The exit code, which is the whole signal in automation")
    import subprocess

    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_isolation.py")],
        capture_output=True,
        text=True,
        env={
            "HTTP_PORT": str(free_port()),
            "API_HOST_PORT": str(free_port()),
            "PATH": "/nonexistent",
        },
    )
    check(
        "with nothing running it exits non-zero, not 0",
        done.returncode != 0,
        f"exit {done.returncode}: {done.stdout}",
    )
    check(
        "and does so by failing its checks, not by crashing",
        "FAIL" in done.stdout and "Traceback" not in done.stderr,
        done.stderr[-300:],
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("isolation checker checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
