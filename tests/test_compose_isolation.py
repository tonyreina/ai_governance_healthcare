#!/usr/bin/env python3
"""The network isolation the whole security model rests on, as a test.

The API trusts an identity header, so it is only safe if nothing can reach it
except the proxy that sets that header. docs/self-hosting.md calls this "not
hardening, it is the security model", and says compose.yaml enforces it "with
networking rather than with a convention". Until now the only check was
`make check-isolation`, a manual target against a running stack that nothing in
CI ran, and one step of which asserts nothing (#56).

This reads the real compose.yaml and fails if the property is edited away:

* the API publishes no host port, and neither does the database;
* the database is only on a network that is `internal: true` (no route off the host);
* the only service on the internet-facing network besides the API is the proxy;
* the proxy publishes on loopback by default, because the stack speaks plain HTTP;
* the dev override (which DOES publish the API) is a named file, never
  compose.override.yaml, which a bare `docker compose up` would pick up silently;
* the database lives on a named volume (so `down` keeps the data) and its image is
  pinned to a major version (Postgres does not migrate its on-disk format).

Each rule has a mutation test: break a copy of the real file and demand it notice.

    pixi run test-compose
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "compose.yaml"

API, DB, PROXY = "api", "db", "proxy"
EDGE, DATA = "edge", "data"
VOLUME = "pgdata"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def load() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def service(compose: dict, name: str) -> dict:
    return compose.get("services", {}).get(name, {})


# --- the rules: parsed compose in, problems out ------------------------------


def published_ports(compose: dict, name: str) -> list[str]:
    return [str(p) for p in service(compose, name).get("ports", [])]


def api_ports(compose: dict) -> list[str]:
    return [f"api publishes {p}" for p in published_ports(compose, API)]


def db_ports(compose: dict) -> list[str]:
    return [f"db publishes {p}" for p in published_ports(compose, DB)]


def db_network(compose: dict) -> list[str]:
    nets = service(compose, DB).get("networks", [])
    nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
    problems = []
    if nets != [DATA]:
        problems.append(f"db must be on [{DATA}] only, found {nets}")
    if not (compose.get("networks", {}).get(DATA) or {}).get("internal"):
        problems.append(
            f"network '{DATA}' is not internal: true, so the db can route off the host"
        )
    return problems


def edge_members(compose: dict) -> list[str]:
    """Who shares the internet-facing network with the API. Only the proxy may."""
    members = []
    for name, svc in compose.get("services", {}).items():
        nets = svc.get("networks", [])
        nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
        if EDGE in nets:
            members.append(name)
    allowed = {API, PROXY}
    return [
        f"{m} is on '{EDGE}', which would let it reach the API and forge identity"
        for m in members
        if m not in allowed
    ]


def proxy_binds_loopback(compose: dict) -> list[str]:
    ports = published_ports(compose, PROXY)
    if not ports:
        return ["the proxy publishes no port"]
    bad = [p for p in ports if not p.startswith("${HTTP_BIND:-127.0.0.1}:")]
    return [f"the proxy publishes {p}, which does not default to loopback" for p in bad]


def database_persists(compose: dict) -> list[str]:
    mounts = service(compose, DB).get("volumes", [])
    problems = []
    if not any(str(m).startswith(f"{VOLUME}:") for m in mounts):
        problems.append(f"db does not mount the named volume '{VOLUME}'")
    if VOLUME not in (compose.get("volumes") or {}):
        problems.append(f"'{VOLUME}' is not declared as a named volume")
    return problems


def database_image_pinned(compose: dict) -> list[str]:
    image = str(service(compose, DB).get("image", ""))
    return (
        []
        if re.fullmatch(r"postgres:\d+", image)
        else [
            f"db image is '{image}'; pin a major version (postgres:NN), because "
            "Postgres "
            "does not migrate its on-disk format"
        ]
    )


def override_file_is_named() -> list[str]:
    stray = [
        n
        for n in (
            "compose.override.yaml",
            "compose.override.yml",
            "docker-compose.override.yml",
        )
        if (ROOT / n).exists()
    ]
    return [
        f"{n} exists, and a bare `docker compose up` would pick it up silently"
        for n in stray
    ]


def shared_secret_reaches_both_ends(compose: dict) -> list[str]:
    """The API checks PROXY_SHARED_SECRET and only the proxy can send it (#61).

    It was documented while no shipped config sent it, so setting it on the API
    made every request 403. Both services must be handed the same variable, or
    the control either never turns on or breaks the stack.
    """
    want = "${PROXY_SHARED_SECRET:-}"
    return [
        f"{name} does not receive PROXY_SHARED_SECRET as {want}"
        for name in (API, PROXY)
        if service(compose, name).get("environment", {}).get("PROXY_SHARED_SECRET")
        != want
    ]


def every_rule(compose: dict) -> list[str]:
    return [
        *api_ports(compose),
        *db_ports(compose),
        *db_network(compose),
        *edge_members(compose),
        *proxy_binds_loopback(compose),
        *database_persists(compose),
        *database_image_pinned(compose),
        *override_file_is_named(),
        *shared_secret_reaches_both_ends(compose),
    ]


# --- tests -------------------------------------------------------------------


def main() -> int:
    compose = load()

    print("The real compose.yaml")
    problems = every_rule(compose)
    check("every isolation rule holds", not problems, "; ".join(problems))
    check(
        "it has the three services it is about",
        all(service(compose, n) for n in (API, DB, PROXY)),
    )

    print("Mutation tests: each rule must notice when it is broken")

    broken = copy.deepcopy(compose)
    broken["services"][API]["ports"] = ["127.0.0.1:8000:8000"]
    check("publishing a port on the api is noticed", bool(api_ports(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][DB]["ports"] = ["5432:5432"]
    check("publishing a port on the database is noticed", bool(db_ports(broken)))

    broken = copy.deepcopy(compose)
    broken["networks"][DATA]["internal"] = False
    check("an internal network made routable is noticed", bool(db_network(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][DB]["networks"] = [DATA, EDGE]
    check("the database joining the edge network is noticed", bool(db_network(broken)))

    broken = copy.deepcopy(compose)
    broken["services"]["sidecar"] = {"image": "x", "networks": [EDGE]}
    check("a new service on the edge network is noticed", bool(edge_members(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][PROXY]["ports"] = ["0.0.0.0:8080:80"]
    check(
        "the proxy binding every interface is noticed",
        bool(proxy_binds_loopback(broken)),
    )

    broken = copy.deepcopy(compose)
    broken["services"][PROXY]["ports"] = []
    check("a proxy with no port is noticed", bool(proxy_binds_loopback(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][DB]["volumes"] = ["/tmp/pg:/var/lib/postgresql/data"]
    check(
        "the database leaving its named volume is noticed",
        bool(database_persists(broken)),
    )

    broken = copy.deepcopy(compose)
    del broken["volumes"][VOLUME]
    check("an undeclared named volume is noticed", bool(database_persists(broken)))

    for image in ("postgres:latest", "postgres", "postgres:17-alpine"):
        broken = copy.deepcopy(compose)
        broken["services"][DB]["image"] = image
        check(f"db image '{image}' is noticed", bool(database_image_pinned(broken)))

    for side in (API, PROXY):
        broken = copy.deepcopy(compose)
        del broken["services"][side]["environment"]["PROXY_SHARED_SECRET"]
        check(
            f"PROXY_SHARED_SECRET missing from {side} is noticed",
            bool(shared_secret_reaches_both_ends(broken)),
        )

    stray = ROOT / "compose.override.yaml"
    stray.write_text("services: {}\n", encoding="utf-8")
    try:
        check("a compose.override.yaml is noticed", bool(override_file_is_named()))
    finally:
        stray.unlink()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("compose isolation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
