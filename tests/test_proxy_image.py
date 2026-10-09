#!/usr/bin/env python3
"""The cloud proxy image is built, starts, and serves the page under its policy (D-72).

proxy/Dockerfile rebuilds the Caddy binary from the release the stack runs, with a
patched Go toolchain, instead of using the official binary as is. That is a binary
nothing else in CI starts: the compose stack and tests/test_proxy_identity.py run
the official caddy:2 image. So this builds the image, runs it as it would run in
the cloud, and checks:

  * it answers on 8080 as the unprivileged user, with the page and the
    Content-Security-Policy that names the page's script by hash;
  * its Caddy is the same release as the official image compose.yaml pins, so the
    cloud and the local stack cannot drift apart while the rebuild is in place;
  * it carries the standard modules and nothing else, the same set as the official
    binary.

    pixi run test-proxy-image      (needs Docker)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG = "chai-proxy:test-image"
NAME = "chai-test-proxy-image"
PORT = 18098
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def official_caddy_image() -> str:
    """The caddy:2 image compose.yaml pins, digest and all."""
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    m = re.search(r"image:\s*(caddy:2@sha256:[0-9a-f]{64})", compose)
    if not m:
        raise SystemExit("compose.yaml pins no caddy:2 image by digest")
    return m.group(1)


def caddy(image: str, *args: str) -> str:
    out = docker("run", "--rm", "--entrypoint", "caddy", image, *args)
    return out.stdout.strip()


def main() -> int:
    if not shutil.which("docker") or docker("info").returncode != 0:
        print("docker unavailable; skipping the proxy image checks")
        return 1 if REQUIRE_TESTS else 0

    print("Build")
    built = docker("build", "-f", "proxy/Dockerfile", "-t", TAG, str(ROOT))
    check("proxy/Dockerfile builds", built.returncode == 0, built.stderr[-800:])
    if built.returncode != 0:
        return 1

    print("The same Caddy as the stack")
    official = official_caddy_image()
    ours_v = caddy(TAG, "version").split()[:1]
    theirs_v = caddy(official, "version").split()[:1]
    check(
        "the same Caddy release as the image compose.yaml pins",
        bool(ours_v) and ours_v == theirs_v,
        f"{ours_v} vs {theirs_v}",
    )
    ours_m = set(caddy(TAG, "list-modules", "--skip-standard").splitlines())
    theirs_m = set(caddy(official, "list-modules", "--skip-standard").splitlines())
    check(
        "no module added or missing beyond the standard set",
        ours_m == theirs_m,
        f"{sorted(ours_m ^ theirs_m)}",
    )

    print("It runs as it would in the cloud")
    docker("rm", "-f", NAME)
    run = docker("run", "-d", "--name", NAME, "-p", f"{PORT}:8080", TAG)
    check("the container starts", run.returncode == 0, run.stderr[-400:])
    try:
        status, headers, body = 0, {}, ""
        for _ in range(50):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT}/", timeout=2
                ) as r:
                    status, body = r.status, r.read().decode("utf-8", "replace")
                    headers = {k.lower(): v for k, v in r.headers.items()}
                break
            except OSError:
                time.sleep(0.2)
        check("it serves the page on 8080", status == 200 and "<html" in body.lower())
        policy = headers.get("content-security-policy", "")
        generated = (ROOT / "proxy" / "csp.caddy").read_text(encoding="utf-8")
        hashes = re.findall(r"'sha256-[A-Za-z0-9+/=]+'", generated)
        check(
            "with the policy that names the page's script by hash",
            bool(hashes)
            and all(h in policy for h in hashes)
            and "'unsafe-inline'"
            not in policy.split("script-src", 1)[-1].split(";")[0],
            policy[:160],
        )
        user = docker("exec", NAME, "id", "-u").stdout.strip()
        check("as the unprivileged user", user == "65532", user)
    finally:
        docker("rm", "-f", NAME)

    print("A different release is noticed (mutation)")
    older = docker(
        "build",
        "-f",
        "proxy/Dockerfile",
        "--build-arg",
        "CADDY_VERSION=v2.11.6",
        "-t",
        f"{TAG}-older",
        str(ROOT),
    )
    if older.returncode != 0:
        check("an image built from another release builds", False, older.stderr[-400:])
    else:
        mutant = caddy(f"{TAG}-older", "version").split()[:1]
        check(
            "an image built from an older release fails the release check",
            bool(mutant) and mutant != theirs_v,
            f"{mutant} vs {theirs_v}",
        )
        docker("rmi", "-f", f"{TAG}-older")

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("proxy image checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
