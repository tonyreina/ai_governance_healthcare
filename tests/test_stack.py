#!/usr/bin/env python3
"""End-to-end checks against a running Docker Compose stack.

Verifies the properties that only exist once the real stack is up: the browser
selects ApiStore, identity comes from the proxy and cannot be forged, writes
reach PostgreSQL, and a change made elsewhere arrives over SSE.

Start the stack first, then:

    docker compose up -d --build
    pixi run test-stack

Skips cleanly (exit 0) when nothing is listening, so it is safe in CI without
Docker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8080"

# CI sets REQUIRE_TESTS=1. A suite that cannot run then FAILS instead of
# skipping, because a skip exits 0 and reads as a pass: that is how CI once
# reported green while running none of these tests (#32).
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))


def http(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def stack_up() -> bool:
    try:
        return http("/api/health")[0] == 200
    except Exception:
        return False


def wait_until(page, expression: str, timeout: float = 20.0) -> None:
    """Poll until a page expression is truthy, or raise.

    NOT page.wait_for_function: that evaluates its argument with the page's own
    `eval`, which the Content-Security-Policy this stack serves
    (`script-src 'unsafe-inline'`, deliberately no `unsafe-eval`) forbids. This
    suite broke the day that policy shipped and nobody noticed, because CI did not
    run it (#32). `page.evaluate` goes through the debugging protocol instead, so
    the app is still tested under the policy it actually ships with.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(200)
    raise TimeoutError(f"still false after {timeout}s: {expression}")


def main() -> int:
    if not stack_up():
        print("stack not running at " + BASE + " - skipping")
        print("  start it with: docker compose up -d --build")
        return 1 if REQUIRE_TESTS else 0

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
        if not ok:
            failures.append(name)

    print("API")
    status, body = http("/api/health")
    check("health reports ok", json.loads(body).get("status") == "ok", body)

    # Identity must come from the proxy, never from the client.
    _, me = http("/api/me")
    baseline = json.loads(me)
    req = urllib.request.Request(
        BASE + "/api/me",
        headers={
            "X-Auth-Request-Email": "ceo@hospital.org",
            "X-Goog-Authenticated-User-Email": "attacker@evil.com",
            "X-Amzn-Oidc-Identity": "attacker@evil.com",
            "X-Ms-Client-Principal-Name": "attacker@evil.com",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        forged = json.loads(r.read().decode())
    check(
        "forged identity headers are stripped",
        forged == baseline,
        f"{forged} != {baseline}",
    )

    # Deep merge must preserve siblings at every level, and replace arrays.
    pid = "t-" + uuid.uuid4().hex[:8]
    status, _ = http(
        f"/api/projects/{pid}",
        "POST",
        {
            "meta": {"solution": "merge test"},
            "items": {"a": {"status": "met"}, "b": {"status": "partial"}},
            "metrics": [{"name": "old"}],
        },
    )
    check("create returns 201", status == 201, str(status))
    check(
        "duplicate create returns 409",
        http(f"/api/projects/{pid}", "POST", {})[0] == 409,
    )

    http(
        f"/api/projects/{pid}",
        "PATCH",
        {"items": {"a": {"owner": "Alice"}}, "metrics": [{"name": "new"}]},
    )
    _, body = http("/api/projects")
    doc = next(p for p in json.loads(body) if p["id"] == pid)
    check(
        "nested sibling key preserved",
        doc["items"]["a"] == {"status": "met", "owner": "Alice"},
        str(doc["items"]["a"]),
    )
    check("sibling object untouched", doc["items"]["b"] == {"status": "partial"})
    check(
        "arrays replace, not merge",
        doc["metrics"] == [{"name": "new"}],
        str(doc["metrics"]),
    )

    # Who signed a checkpoint is the server's to say, not the client's (#31). Sent
    # through the real proxy to the real API: the identity comes from Caddy, so
    # this is the only place the two halves are tested together.
    forged = "cmo@hospital.example"
    forged_at = "2026-01-15T09:00:00.000Z"
    sid = "t-" + uuid.uuid4().hex[:8]
    http(f"/api/projects/{sid}", "POST", {"meta": {"solution": "sign-off test"}})
    status, _ = http(
        f"/api/projects/{sid}",
        "PATCH",
        {
            "gates": {
                "A": {
                    "decision": "Proceed",
                    "signedBy": forged,
                    "signedAt": forged_at,
                }
            }
        },
    )
    check("a forged sign-off is accepted as a patch", status == 200, str(status))
    _, listing = http("/api/projects")
    gate = next(p for p in json.loads(listing) if p["id"] == sid)["gates"]["A"]
    check(
        "the sign-off is attributed to the proxy identity, not the claim",
        gate["signedBy"] == baseline["id"] and gate["signedBy"] != forged,
        f"signedBy={gate['signedBy']!r}, expected {baseline['id']!r}",
    )
    check(
        "the sign-off time is the server's, not the claim",
        gate["signedAt"] != forged_at,
        gate["signedAt"],
    )

    # Disposal (#36), through the real proxy: a purge destroys the content and says
    # so, a delete leaves the history, and neither is the same as the other.
    secret = "MRN-" + uuid.uuid4().hex[:8]
    did = "t-" + uuid.uuid4().hex[:8]
    http(
        f"/api/projects/{did}",
        "POST",
        {"meta": {"solution": "disposal test"}, "items": {"a": {"evidence": secret}}},
    )
    http(
        f"/api/projects/{did}/log",
        "POST",
        {"text": f"Changed evidence: {secret}", "change": {"path": "a", "to": secret}},
    )
    check(
        "a purge is accepted", http(f"/api/projects/{did}/versions", "DELETE")[0] == 204
    )
    _, rev = http(f"/api/projects/{did}/versions/1")
    check(
        "the revision's content is gone",
        secret not in rev and json.loads(rev)["doc"] == {},
    )
    _, entries = http(f"/api/projects/{did}/log")
    check(
        "the audit log no longer holds the value", secret not in entries, entries[:200]
    )
    check("and says it was purged", "[content purged]" in entries)
    check("a delete is accepted", http(f"/api/projects/{did}", "DELETE")[0] == 204)
    check(
        "deleting did not erase what was already purged, or restore it",
        http(f"/api/projects/{did}/versions/1")[0] == 200,
    )

    print("Browser")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  playwright not installed - skipping browser checks")
        return 1 if failures or REQUIRE_TESTS else 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/")
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED", timeout=20)
        page.wait_for_timeout(1500)

        check(
            "app selects ApiStore",
            page.evaluate("STORE.constructor.name") == "ApiStore",
        )
        check("identity taken from the proxy", page.evaluate("ME.id") == baseline["id"])
        check("mode badge says shared", "Shared" in page.inner_text("#mode"))

        # A change made OUTSIDE the browser must arrive over SSE. This is the
        # one that silently regressed once: the server sends named events, and
        # EventSource.onmessage never fires for those.
        before = page.evaluate("PROJECTS.size")
        other = "t-" + uuid.uuid4().hex[:8]
        subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-d",
                '{"meta":{"solution":"pushed externally"}}',
                f"{BASE}/api/projects/{other}",
            ],
            capture_output=True,
            timeout=20,
        )
        arrived = False
        for _ in range(24):
            time.sleep(0.5)
            if page.evaluate("PROJECTS.size") > before:
                arrived = True
                break
        check("external change arrives over SSE", arrived)
        check("no page errors", not errors, "; ".join(errors[:2]))
        browser.close()
        http(f"/api/projects/{other}", "DELETE")

    http(f"/api/projects/{pid}", "DELETE")

    print()
    if failures:
        print(
            f"{len(failures)} check(s) failed: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
