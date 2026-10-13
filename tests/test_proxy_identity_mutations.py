#!/usr/bin/env python3
"""The identity handoff's guards in proxy/Caddyfile, each shown to fail (C-01).

tests/test_proxy_identity.py sends a forged X-Auth-Request-User, -Name and -Email
BESIDE a valid front-door identity and asserts the API would receive only the
proxy's values. A check nobody has seen fail is a claim, so this breaks a COPY of
the Caddyfile one way at a time (the delete of each canonical header, the set of
each, the provider strip) and demands that check notice. Needs Docker.

    pixi run test-proxy-identity
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tp = load("proxy_identity", ROOT / "tests" / "test_proxy_identity.py")

# The handoff is the `route` inside `handle /api/*`; the agent route has its own copy
# of these deletes, which tests/test_proxy_agent_mutations.py covers.
HANDOFF_START = "	handle /api/* {"
STRIP = "			request_header -{name}\n"
SET = '			request_header {name} "{{${source}}}"\n'


# Each mutation is a name and the (old, new) edits applied together inside the handoff.
#
# The delete of a canonical header cannot be broken alone and noticed: the `set`
# below it OVERWRITES whatever the client sent, so the delete is the second lock,
# and a Caddyfile without it forwards the same values. It is the only lock when a
# set stops overwriting (a find-and-replace form, or an add), which is the real way
# the delete comes to matter, so it is broken together with such a set: both
# edits are one mutation, and the check must notice the forged value arriving.
def set_line(header: str) -> str:
    return SET.format(name=header, source=tp.CANONICAL[header])


def add_line(header: str) -> str:
    return set_line(header).replace("request_header ", "request_header +", 1)


HEADERS = tuple(tp.CANONICAL)
MUTATIONS: list[tuple[str, list[tuple[str, str]]]] = (
    [
        (
            f"{header} is no longer deleted and its set only adds a value",
            [(STRIP.format(name=header), ""), (set_line(header), add_line(header))],
        )
        for header in HEADERS
    ]
    + [
        (f"the set of {header} is removed", [(set_line(header), "")])
        for header in HEADERS
    ]
    + [
        (
            "the set of X-Auth-Request-Name uses the wrong source",
            [
                (
                    set_line("X-Auth-Request-Name"),
                    set_line("X-Auth-Request-Name").replace(
                        "IDENTITY_NAME_SOURCE", "IDENTITY_ID_SOURCE"
                    ),
                )
            ],
        )
    ]
)


def mutate(original: str, edits: list[tuple[str, str]]) -> str | None:
    """`original` with each edit applied once inside the handoff, else None."""
    start = original.index(HANDOFF_START)
    head, tail = original[:start], original[start:]
    for old, new in edits:
        if old not in tail:
            return None
        tail = tail.replace(old, new, 1)
    return head + tail


def main() -> int:
    if not tp.docker_usable():
        print("docker unavailable; skipping the identity handoff's mutation checks")
        return 1 if REQUIRE_TESTS else 0

    original = (ROOT / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    failures = 0

    with tp.rig() as workdir:

        def run_against(caddyfile_text: str) -> list[str]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "Caddyfile"
                path.write_text(caddyfile_text, encoding="utf-8")
                shutil.copy(ROOT / "proxy" / "csp.caddy", Path(tmp) / "csp.caddy")
                tp.CADDYFILE = path
                tp.failures.clear()
                with contextlib.redirect_stdout(io.StringIO()):
                    tp.check_identity_replaced(workdir)
                return list(tp.failures)

        print("The unbroken Caddyfile")
        clean = run_against(original)
        print(
            f"  {'PASS' if not clean else 'FAIL'}  the forged-beside-valid checks "
            "pass a copy of the real file"
        )
        if clean:
            print("        " + "; ".join(clean[:5]))
            failures += 1

        print("Each guard, broken")
        for name, edits in MUTATIONS:
            mutated = mutate(original, edits)
            if mutated is None:
                print(f"  FAIL  {name}  <- the text to break is not in the Caddyfile")
                failures += 1
                continue
            assert mutated != original
            noticed = run_against(mutated)
            print(
                f"  {'PASS' if noticed else 'FAIL'}  {name} is noticed"
                + (f"  ({len(noticed)} check(s))" if noticed else "")
            )
            failures += 0 if noticed else 1

        tp.CADDYFILE = ROOT / "proxy" / "Caddyfile"

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("identity handoff mutation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
