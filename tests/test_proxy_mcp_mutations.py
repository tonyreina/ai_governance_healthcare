#!/usr/bin/env python3
"""The MCP route's guards in proxy/Caddyfile and proxy/Caddyfile.mcp-gate, each shown
to fail (#164, R-73, D-91).

tests/test_proxy_identity.py checks both files against a real Caddy: only the
transport's methods on the single path, every identity header stripped and none set,
the bearer passed on untouched, the secret kept from the service, nothing else
forwarded, and a 502 when nothing is behind the route. A check nobody has seen fail is
a claim, so this breaks a COPY of each file in each way that matters, runs the same
checks against a real Caddy, and demands that they notice. Needs Docker.

    pixi run test-proxy-mcp

Every broken copy restarts a real Caddy, and the gate's and the timeouts' checks wait
on real deadlines, so the whole list takes about 25 minutes. CI splits it (D-97):
MUTANT_SHARD=i/n runs the i-th of n shards, the mutant at position k going to shard
k % n + 1, so the shards partition the list and each mutant runs exactly once. Unset,
every mutant runs. A shard first runs the checks it uses against the unbroken files:
a mutant only counts as noticed when the same check passes the real files on the same
runner.

    MUTANT_SHARD=2/5 pixi run test-proxy-mcp
    python tests/test_proxy_mcp_mutations.py --list   # a shard's mutants, no Docker
    pixi run test-mutant-shards                     # the shards partition the list
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import assert_never

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tp = load("proxy_identity", ROOT / "tests" / "test_proxy_identity.py")

MAIN_START = "\t@mcpfront {"
MAIN_END = "\t# " + "-" * 73 + "\n\t# The dashboard: one pre-built"


def strip(name: str) -> str:
    return f"\t\t\trequest_header -{name}\n"


AGENT_ONLY_LOG = (
    r"(?i)^(?:([^?]*(?:agent|%|//|/\.{1,2}(?:/|$))[^?]*)\?.*|([^?]*)\?.*agent.*)$"
)
MCP_LOG = (
    r"(?i)^(?:([^?]*(?:agent|mcp|%|//|/\.{1,2}(?:/|$))[^?]*)\?.*"
    r"|([^?]*)\?.*(?:agent|mcp).*)$"
)

# (name, old, new, nth occurrence in its scope)
MAIN: list[tuple[str, str, str, int]] = [
    ("PUT is forwarded", "method POST GET DELETE", "method POST GET DELETE PUT", 1),
    ("PATCH is forwarded", "method POST GET DELETE", "method POST GET DELETE PATCH", 1),
    (
        "any path under the prefix is forwarded",
        "\t\tpath /mcp\n",
        "\t\tpath /mcp*\n",
        1,
    ),
    (
        "the canonical email header is not stripped",
        strip("X-Auth-Request-Email"),
        "",
        1,
    ),
    ("the canonical user header is not stripped", strip("X-Auth-Request-User"), "", 1),
    ("an IAP header is not stripped", strip("X-Goog-Authenticated-User-Email"), "", 1),
    (
        "the oauth2-proxy email header is not stripped",
        strip("X-Forwarded-Email"),
        "",
        1,
    ),
    ("an ALB header is not stripped", strip("X-Amzn-Oidc-Data"), "", 1),
    ("an Easy Auth header is not stripped", strip("X-Ms-Client-Principal-Name"), "", 1),
    ("a client's X-Proxy-Secret is not stripped", strip("X-Proxy-Secret"), "", 1),
    (
        "the proxy sets an identity on the mcp route",
        '\t\t\theader Cache-Control "no-store"\n',
        '\t\t\trequest_header X-Auth-Request-Email "{$IDENTITY_EMAIL_SOURCE}"\n'
        '\t\t\theader Cache-Control "no-store"\n',
        1,
    ),
    (
        "the proxy gives the service its shared secret",
        "\t\t\t\tflush_interval -1\n",
        "\t\t\t\tflush_interval -1\n"
        '\t\t\t\theader_up X-Proxy-Secret "{$PROXY_SHARED_SECRET}"\n',
        1,
    ),
    ("the answer is cacheable", '\t\t\theader Cache-Control "no-store"\n', "", 1),
    (
        "the body is not capped",
        "\t\trequest_body {\n\t\t\tmax_size 64KB\n\t\t}\n\n",
        "",
        1,
    ),
    (
        "the fallback no longer refuses the rest of the prefix",
        '\thandle /mcp* {\n\t\trespond "Not found." 404\n\t}\n',
        "",
        1,
    ),
    ("a client's X-Forwarded-For is not deleted", strip("X-Forwarded-For"), "", 1),
    ("a client's Forwarded is not deleted", strip("Forwarded"), "", 1),
    ("a client's X-Real-IP is not deleted", strip("X-Real-IP"), "", 1),
    (
        "X-Client-Address is not set from the peer",
        '\t\t\trequest_header X-Client-Address "{remote_host}"\n',
        "",
        1,
    ),
    (
        "X-Client-Address is set from a forwarding header",
        '\t\t\trequest_header X-Client-Address "{remote_host}"\n',
        "\t\t\trequest_header X-Client-Address "
        '"{http.request.header.X-Forwarded-For}"\n',
        1,
    ),
    (
        "the default upstream is the main API",
        "{$MCP_UPSTREAM:mcp-gate:8082}",
        "{$MCP_UPSTREAM:api:8000}",
        1,
    ),
]
# Applied to the whole file: the log's redaction is above the route.
MAIN_FILE: list[tuple[str, str, str, int]] = [
    (
        "X-Client-Address is not stripped on every route",
        "\trequest_header -X-Client-Address\n",
        "",
        1,
    ),
    ("the log keeps the query of /mcp", MCP_LOG, AGENT_ONLY_LOG, 1),
]

# Broken in the main file, and noticed by the timing checks only (they take a minute).
TIMEOUTS_MAIN: list[tuple[str, str, str, int]] = [
    (
        "the proxy waits for ever for a service",
        "\t\t\t\t\tresponse_header_timeout 30s\n",
        "",
        1,
    ),
    ("the proxy's header deadline is gone", "\t\t\tread_header 10s\n", "", 1),
]
TIMEOUTS_GATE: list[tuple[str, str, str, int]] = [
    (
        "the gate waits for ever for a service",
        "\t\t\t\t\tresponse_header_timeout 30s\n",
        "",
        1,
    ),
    ("the gate's header deadline is gone", "\t\t\tread_header 10s\n", "", 1),
]

GATE: list[tuple[str, str, str, int]] = [
    (
        "the gate's own logs keep the shared secret",
        "\t\t\t\trequest>headers>X-Proxy-Secret delete\n",
        "",
        1,
    ),
    (
        "the gate takes the address from a forwarding header",
        "\t\t\treverse_proxy {$MCP_UPSTREAM:mcp:8000} {\n\t\t\t\tflush_interval -1\n",
        "\t\t\treverse_proxy {$MCP_UPSTREAM:mcp:8000} {\n\t\t\t\tflush_interval -1\n"
        '\t\t\t\theader_up X-Client-Address "{client_ip}"\n',
        1,
    ),
    ("the gate does not delete a client's X-Real-IP", strip("X-Real-IP"), "", 1),
    ("the gate does not delete a client's Forwarded", strip("Forwarded"), "", 1),
    (
        "the gate has no health route",
        '\thandle /gate-health {\n\t\trespond "ok" 200\n\t}\n',
        "",
        1,
    ),
    (
        "the gate has no body deadline",
        "\t\t\tread_body 10s\n",
        "",
        1,
    ),
    (
        "the API listener has no body cap",
        "\t\trequest_body {\n\t\t\tmax_size 16KB\n\t\t}\n\n",
        "",
        1,
    ),
    # --- :8081, the service to the API
    (
        "8081 forwards a write verb",
        "\t\tmethod GET\n",
        "\t\tmethod GET POST DELETE\n",
        1,
    ),
    (
        "8081 forwards any agent path",
        "\t\tpath /api/agent/me /api/agent/portfolio /api/agent/projects/*\n",
        "\t\tpath /api/agent/*\n",
        1,
    ),
    (
        "8081 forwards every API path",
        "\t\tpath /api/agent/me /api/agent/portfolio /api/agent/projects/*\n",
        "\t\tpath /api/*\n",
        1,
    ),
    ("8081 does not strip the canonical email", strip("X-Auth-Request-Email"), "", 1),
    (
        "8081 does not strip an IAP header",
        strip("X-Goog-Authenticated-User-Email"),
        "",
        1,
    ),
    (
        "8081 does not send the caller's address",
        '\t\t\t\theader_up X-Real-IP "{http.request.header.X-Client-Address}"\n',
        "",
        1,
    ),
    (
        "8081 lets the sender choose the shared secret",
        '\t\t\t\theader_up X-Proxy-Secret "{$PROXY_SHARED_SECRET}"\n',
        "",
        1,
    ),
    (
        "8081 no longer refuses the rest",
        '\thandle {\n\t\trespond "Not found." 404\n\t}\n',
        "",
        1,
    ),
    ("8081 answer is cacheable", '\t\t\theader Cache-Control "no-store"\n', "", 1),
    # --- :8082, the proxy to the service
    (
        "8082 forwards PUT",
        "\t\tmethod POST GET DELETE\n",
        "\t\tmethod POST GET DELETE PUT\n",
        1,
    ),
    ("8082 forwards any path", "\t\tpath /mcp\n", "\t\tpath /mcp*\n", 1),
    ("8082 does not strip the canonical email", strip("X-Auth-Request-Email"), "", 2),
    ("8082 does not strip an ALB header", strip("X-Amzn-Oidc-Data"), "", 2),
    ("8082 passes a client's shared secret", strip("X-Proxy-Secret"), "", 1),
    (
        "8082 no longer refuses the rest",
        '\thandle {\n\t\trespond "Not found." 404\n\t}\n',
        "",
        2,
    ),
    (
        "8082 does not cap the body",
        "\t\trequest_body {\n\t\t\tmax_size 64KB\n\t\t}\n\n",
        "",
        1,
    ),
    ("8082 answer is cacheable", '\t\t\theader Cache-Control "no-store"\n', "", 2),
    # --- the log
    (
        "the gate's log keeps the query",
        'regexp "^([^?]*)\\?.*$" "$1?[redacted]"',
        'regexp "^nothing$" "$1?[redacted]"',
        1,
    ),
]


def replace_nth(text: str, old: str, new: str, nth: int) -> str | None:
    at = -1
    for _ in range(nth):
        at = text.find(old, at + 1)
        if at < 0:
            return None
    return text[:at] + new + text[at + len(old) :]


class Check(StrEnum):
    """Which of test_proxy_identity.py's checks judges a broken copy."""

    ROUTE = "main"
    GATE = "gate"
    TIMEOUTS = "timeouts"


class Scope(StrEnum):
    """Where the text to break is looked for."""

    ROUTE = "the route"  # the /mcp block of proxy/Caddyfile only
    MAIN = "the Caddyfile"
    GATE = "the gate"


@dataclasses.dataclass(frozen=True)
class Mutant:
    name: str
    old: str
    new: str
    nth: int
    scope: Scope
    check: Check


def all_mutants() -> list[Mutant]:
    """Every mutant, in the order the shards deal them out.

    The slow kinds come first (a timeout mutant takes about two minutes, a gate one
    about forty seconds, a route one a few), so dealing them round-robin spreads each
    kind evenly across the shards.
    """

    def of(rows: list, scope: Scope, check: Check) -> list[Mutant]:
        return [
            Mutant(name, old, new, nth, scope, check) for name, old, new, nth in rows
        ]

    return [
        *of(TIMEOUTS_MAIN, Scope.MAIN, Check.TIMEOUTS),
        *of(TIMEOUTS_GATE, Scope.GATE, Check.TIMEOUTS),
        *of(GATE, Scope.GATE, Check.GATE),
        *of(MAIN, Scope.ROUTE, Check.ROUTE),
        *of(MAIN_FILE, Scope.MAIN, Check.ROUTE),
    ]


SHARD_VAR = "MUTANT_SHARD"
Selector = Callable[[list[Mutant], int, int], list[Mutant]]


def parse_shard(raw: str | None) -> tuple[int, int]:
    """`i/n` -> (i, n), with 1 <= i <= n. Unset or empty is the whole list, (1, 1).
    Anything else is an error, never a quiet fallback to running all or nothing."""
    if not raw:
        return 1, 1
    match = re.fullmatch(r"([0-9]+)/([0-9]+)", raw.strip())
    if not match:
        raise ValueError(f"{SHARD_VAR}={raw!r} is not i/n")
    index, count = int(match[1]), int(match[2])
    if not 1 <= index <= count:
        raise ValueError(f"{SHARD_VAR}={raw!r}: the shard must be 1..{count}")
    return index, count


def select(mutants: list[Mutant], index: int, count: int) -> list[Mutant]:
    """Shard `index` of `count`: each mutant at a position k % count == index - 1."""
    return [m for k, m in enumerate(mutants) if k % count == index - 1]


def partition_problems(
    selector: Selector, mutants: list[Mutant], count: int
) -> list[str]:
    """Do shards 1..count of `selector` run each mutant exactly once, and no other?"""
    ran = Counter(
        id(m) for index in range(1, count + 1) for m in selector(mutants, index, count)
    )
    names = {id(m): m.name for m in mutants}
    problems = [f"{count} shards never run {names[i]!r}" for i in names if not ran[i]]
    problems += [
        f"{count} shards run {names[i]!r} {ran[i]} times" for i in names if ran[i] > 1
    ]
    problems += [
        f"{count} shards run something not in the list" for i in ran if i not in names
    ]
    return problems


def check_shards() -> int:
    """The sharding, unit-tested with no Docker: the shards partition the list for
    every shard count, the variable is parsed strictly, and each property is shown
    failing on a selector broken the way it guards against."""
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
        failures += 0 if ok else 1

    mutants = all_mutants()
    rows = [*MAIN, *MAIN_FILE, *TIMEOUTS_MAIN, *TIMEOUTS_GATE, *GATE]
    print("The mutant list")
    check(
        "every mutant row is in the list, once",
        len(mutants) == len(rows) and {m.name for m in mutants} == {r[0] for r in rows},
        f"{len(mutants)} mutants from {len(rows)} rows",
    )
    duplicated = [n for n, c in Counter(m.name for m in mutants).items() if c > 1]
    check("every mutant has its own name", not duplicated, f"{duplicated}")

    print("The shards partition the list")
    counts = range(1, len(mutants) + 2)
    problems = [p for n in counts for p in partition_problems(select, mutants, n)]
    check(
        f"for every shard count 1..{counts[-1]}, each mutant runs in exactly one shard",
        not problems,
        "; ".join(problems[:5]),
    )
    check("unset runs every mutant", select(mutants, *parse_shard(None)) == mutants)
    check("1/1 runs every mutant", select(mutants, *parse_shard("1/1")) == mutants)
    five = [select(mutants, i, 5) for i in range(1, 6)]
    check(
        "5 shards are balanced to within one mutant",
        max(map(len, five)) - min(map(len, five)) <= 1,
        f"{[len(s) for s in five]}",
    )
    for kind in Check:
        spread = [sum(m.check is kind for m in s) for s in five]
        check(
            f"5 shards share the {kind} mutants to within one",
            max(spread) - min(spread) <= 1,
            f"{spread}",
        )
    check("2/5 is (2, 5)", parse_shard("2/5") == (2, 5))
    for bad in ("0/5", "6/5", "5", "a/b", "2/0", "-1/5", "1/5/2", "1 / 5"):
        try:
            parse_shard(bad)
            refused = False
        except ValueError:
            refused = True
        check(f"{SHARD_VAR}={bad!r} is refused", refused, "it was accepted")

    print("Mutation tests: a broken selector must be noticed")
    broken: dict[str, Selector] = {
        "an off-by-one shard index": lambda ms, i, n: [
            m for k, m in enumerate(ms) if k % n == i
        ],
        "the last mutant dropped": lambda ms, i, n: select(ms[:-1], i, n),
        "contiguous blocks that round the size down": lambda ms, i, n: ms[
            (i - 1) * (len(ms) // n) : i * (len(ms) // n)
        ],
        "every shard also running the first mutant": lambda ms, i, n: [
            ms[0],
            *(m for m in select(ms, i, n) if m is not ms[0]),
        ],
    }
    for name, selector in broken.items():
        check(
            f"{name} is noticed",
            any(partition_problems(selector, mutants, n) for n in range(2, 9)),
        )
    return failures


def mutated_copy(m: Mutant, main_text: str, gate_text: str) -> tuple[str, str] | None:
    """The two files with `m` applied, or None if the text to break is not there."""
    match m.scope:
        case Scope.ROUTE:
            start, end = main_text.index(MAIN_START), main_text.index(MAIN_END)
            region = replace_nth(main_text[start:end], m.old, m.new, m.nth)
            if region is None:
                return None
            return main_text[:start] + region + main_text[end:], gate_text
        case Scope.MAIN:
            mutated = replace_nth(main_text, m.old, m.new, m.nth)
            return None if mutated is None else (mutated, gate_text)
        case Scope.GATE:
            mutated = replace_nth(gate_text, m.old, m.new, m.nth)
            return None if mutated is None else (main_text, mutated)
        case _:
            assert_never(m.scope)


def main() -> int:
    if "--check-shards" in sys.argv[1:]:
        failures = check_shards()
        print()
        print(
            f"{failures} check(s) failed" if failures else "mutant shard checks passed"
        )
        return 1 if failures else 0

    index, count = parse_shard(os.environ.get(SHARD_VAR))
    mutants = all_mutants()
    chosen = select(mutants, index, count)
    print(f"shard {index}/{count}: {len(chosen)} of {len(mutants)} mutants")
    if "--list" in sys.argv[1:]:
        for m in chosen:
            print(f"  [{m.check}] {m.name}")
        return 0

    if not tp.docker_usable():
        print("docker unavailable; skipping the MCP route's mutation checks")
        return 1 if REQUIRE_TESTS else 0

    main_text = (ROOT / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    gate_text = (ROOT / "proxy" / "Caddyfile.mcp-gate").read_text(encoding="utf-8")
    failures = 0

    with tp.rig() as workdir:

        def run(main_copy: str, gate_copy: str, which: Check) -> list[str]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "Caddyfile"
                path.write_text(main_copy, encoding="utf-8")
                shutil.copy(ROOT / "proxy" / "csp.caddy", Path(tmp) / "csp.caddy")
                gate = Path(tmp) / "Caddyfile.mcp-gate"
                gate.write_text(gate_copy, encoding="utf-8")
                tp.CADDYFILE, tp.GATE = path, gate
                tp.failures.clear()
                with contextlib.redirect_stdout(io.StringIO()):
                    match which:
                        case Check.ROUTE:
                            tp.check_mcp_route(workdir)
                        case Check.TIMEOUTS:
                            tp.check_mcp_timeouts(workdir)
                        case Check.GATE:
                            tp.check_mcp_gate(workdir)
                        case _:
                            assert_never(which)
                return list(tp.failures)

        # A mutant "noticed" by a check that fails the real files too proves nothing,
        # so each check this shard uses is first shown passing them, on this runner.
        print("The unbroken files")
        for which in (c for c in Check if any(m.check is c for m in chosen)):
            began = time.monotonic()
            clean = run(main_text, gate_text, which)
            ok = not clean
            print(
                f"  {'PASS' if ok else 'FAIL'}  the {which} checks pass a real copy"
                f"  ({time.monotonic() - began:.0f}s)"
            )
            if not ok:
                print("        " + "; ".join(clean[:5]))
                failures += 1

        # Order is not a property to break here, unlike the agent route's: Caddy sorts
        # `handle` blocks by how specific their matcher is, and the dashboard's
        # catch-all has none, so it can never take /mcp whatever order the file is
        # written in. What would break is the route reaching the sign-on handle, and
        # that is what the checks above (no identity set, nothing reaching /api/) are
        # for.
        print(
            "Each guard, broken (a timeout takes minutes, a gate one about 40 seconds)"
        )
        for m in chosen:
            copies = mutated_copy(m, main_text, gate_text)
            if copies is None:
                print(f"  FAIL  {m.name}  <- the text to break is not in {m.scope}")
                failures += 1
                continue
            assert copies != (main_text, gate_text)
            began = time.monotonic()
            noticed = run(*copies, m.check)
            ok = bool(noticed)
            took = f"{time.monotonic() - began:.0f}s"
            print(
                f"  {'PASS' if ok else 'FAIL'}  [{m.check}] {m.name} is noticed"
                + (f"  ({len(noticed)} check(s), {took})" if ok else f"  ({took})")
            )
            failures += 0 if ok else 1

        tp.CADDYFILE = ROOT / "proxy" / "Caddyfile"
        tp.GATE = ROOT / "proxy" / "Caddyfile.mcp-gate"

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print(f"proxy MCP mutation checks passed (shard {index}/{count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
