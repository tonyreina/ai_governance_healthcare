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
DEV = ROOT / "compose.dev.yaml"

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
        if re.fullmatch(r"postgres:\d+(@sha256:[0-9a-f]{64})?", image)
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


MIGRATE = "migrate"
OWNER_SECRETS = ("POSTGRES_PASSWORD", "POSTGRES_USER", "DATABASE_URL")
PROXY_INIT = "proxy-perms"
NON_ROOT = {"0", "root", ""}


def _security_opts(svc: dict) -> list[str]:
    return [str(o) for o in svc.get("security_opt", [])]


def container_hardening(compose: dict) -> list[str]:
    """The baseline a hospital's container standard asks for (#50).

    The proxy is the only service reachable from outside and it ran as root with
    every default capability; the API's image already drops to uid 10001. No
    service had a memory limit, so any one could take the host's memory. The
    rate limiter's own docstring says the hard protections are elsewhere, and a
    memory limit is one of the elsewheres.
    """
    problems = []
    for name, svc in compose.get("services", {}).items():
        if svc.get("privileged"):
            problems.append(f"{name} is privileged")
        if "no-new-privileges:true" not in _security_opts(svc):
            problems.append(f"{name} lacks security_opt no-new-privileges:true")
        if not svc.get("mem_limit"):
            problems.append(f"{name} has no mem_limit")
        if not svc.get("pids_limit"):
            problems.append(f"{name} has no pids_limit")
        if not svc.get("cpus"):
            problems.append(f"{name} has no cpus limit")

    for name in (API, PROXY, MIGRATE):
        svc = service(compose, name)
        if "ALL" not in [str(c).upper() for c in svc.get("cap_drop", [])]:
            problems.append(f"{name} does not cap_drop ALL")
        if svc.get("read_only") is not True:
            problems.append(f"{name} does not have a read-only root filesystem")
    adds = {str(c).upper() for c in service(compose, API).get("cap_add", [])}
    if adds:
        problems.append(f"api adds back capabilities it does not need: {sorted(adds)}")
    adds = {str(c).upper() for c in service(compose, PROXY).get("cap_add", [])}
    if adds - {"NET_BIND_SERVICE"}:
        problems.append(f"proxy adds back more than NET_BIND_SERVICE: {sorted(adds)}")

    user = str(service(compose, PROXY).get("user", "")).split(":")[0]
    if user in NON_ROOT:
        problems.append("proxy runs as root: set a numeric non-root user")

    # A non-root proxy cannot write the named volumes, which are root-owned, so a
    # one-shot root service fixes their ownership. It must stay off every network
    # and drop everything but CHOWN, or it is a new way in.
    init = service(compose, PROXY_INIT)
    if not init:
        problems.append(f"{PROXY_INIT} is missing, so the non-root proxy cannot write")
    else:
        if init.get("network_mode") != "none":
            problems.append(f"{PROXY_INIT} has network access")
        if init.get("networks"):
            problems.append(f"{PROXY_INIT} is on a network")
        if "ALL" not in [str(c).upper() for c in init.get("cap_drop", [])]:
            problems.append(f"{PROXY_INIT} does not cap_drop ALL")
        if {str(c).upper() for c in init.get("cap_add", [])} - {
            "CHOWN",
            "DAC_READ_SEARCH",
        }:
            problems.append(f"{PROXY_INIT} adds back more than it needs")
        gate = (service(compose, PROXY).get("depends_on") or {}).get(PROXY_INIT, {})
        if gate.get("condition") != "service_completed_successfully":
            problems.append(f"proxy does not wait for {PROXY_INIT} to finish")
    return problems


def cloud_proxy_image_is_unprivileged(dockerfile: str) -> list[str]:
    """proxy/Dockerfile is what Cloud Run, ECS and Container Apps actually run, so it
    must not diverge from the compose service on the one service reachable from
    outside (#50)."""
    problems = []
    user = re.search(r"^USER\s+65532(:65532)?\s*$", dockerfile, re.M)
    if not user:
        problems.append("proxy/Dockerfile does not switch to the non-root user 65532")
    chown = re.search(r"^RUN\s+chown\s+-R\s+65532:65532\s+(.*)$", dockerfile, re.M)
    if not chown or "/data" not in chown.group(1) or "/config" not in chown.group(1):
        problems.append("proxy/Dockerfile does not hand /data and /config to that user")
    elif user and chown.start() > user.start():
        problems.append("the chown must come before USER, or it runs unprivileged")
    return problems


def owner_credential_stays_in_migrate(compose: dict) -> list[str]:
    """The API serves as a restricted role; only `migrate` holds the owner's (#48).

    The owner can disable the append-only triggers the audit log and version
    history depend on. If the API container held that credential, a compromised API
    could do it in one statement, which is the finding. So the API gets the
    restricted role's credential and no trace of the owner's, does not migrate, and
    waits for the job that creates its schema and role.
    """
    problems = []
    api = service(compose, API)
    env = api.get("environment", {})
    leaked = [k for k in OWNER_SECRETS if k in env]
    if leaked:
        problems.append(f"api is given the owner's credential: {leaked}")
    if "APP_POSTGRES_PASSWORD" not in env and "APP_DATABASE_URL" not in env:
        problems.append("api is given no restricted-role credential")
    if str(env.get("RUN_MIGRATIONS")).lower() != "false":
        problems.append("api would try to migrate, which a restricted role cannot do")
    gate = (api.get("depends_on") or {}).get(MIGRATE, {})
    if gate.get("condition") != "service_completed_successfully":
        problems.append("api does not wait for migrate to finish")

    migrate = service(compose, MIGRATE)
    if not migrate:
        problems.append("there is no migrate service, so nothing creates the role")
    else:
        nets = migrate.get("networks", [])
        nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
        if nets != [DATA]:
            problems.append(f"migrate must be on [{DATA}] only, found {nets}")
        if migrate.get("ports"):
            problems.append("migrate publishes a port")
        if "POSTGRES_PASSWORD" not in migrate.get("environment", {}):
            problems.append("migrate has no owner credential to migrate with")
        if migrate.get("restart") not in ("no", False, None):
            problems.append("migrate must run once, not restart")
        if "app.migrate" not in " ".join(map(str, migrate.get("command", []))):
            problems.append("migrate does not run app.migrate")
    return problems


SESSION_SETTINGS = {
    "SSE_MAX_LIFETIME_SECONDS": "${SSE_MAX_LIFETIME_SECONDS:-900}",
    "IDLE_LOCK_MINUTES": "${IDLE_LOCK_MINUTES:-0}",
    "SIGN_OUT_URL": "${SIGN_OUT_URL:-}",
}


def session_settings_reach_the_api(compose: dict) -> list[str]:
    """The documented session settings must be delivered, or they do nothing."""
    env = service(compose, API).get("environment", {})
    return [
        f"api does not receive {name} as {want}"
        for name, want in SESSION_SETTINGS.items()
        if env.get(name) != want
    ]


def logs_are_capped(compose: dict) -> list[str]:
    """Every service's log has a size cap (#38).

    Docker's default keeps a container's log without bound, so a chatty service fills
    the host's disk, and the audit trail's own database with it. The cap is also what
    makes local retention finite and honest: it is not a retention policy, which is
    why docs/deploy.md says where to send the security stream.
    """
    problems = []
    for name, svc in compose.get("services", {}).items():
        logging_cfg = svc.get("logging") or {}
        opts = logging_cfg.get("options") or {}
        if logging_cfg.get("driver") != "json-file":
            problems.append(f"{name} does not use the json-file log driver")
        if not opts.get("max-size") or not opts.get("max-file"):
            problems.append(f"{name} has no log size cap (max-size and max-file)")
    return problems


def emergency_setting_reaches_the_api(compose: dict) -> list[str]:
    """EMERGENCY_ACCESS_IDS is documented as a .env setting, so compose must pass it.

    A setting the docs tell people to use and the stack never delivers is the
    PROXY_SHARED_SECRET failure (#61): the operator sets it, nothing happens, and
    for an emergency path the first time anyone finds out is the emergency.
    """
    env = service(compose, API).get("environment", {})
    want = "${EMERGENCY_ACCESS_IDS:-}"
    if env.get("EMERGENCY_ACCESS_IDS") != want:
        return [f"api does not receive EMERGENCY_ACCESS_IDS as {want}"]
    return []


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
        *container_hardening(compose),
        *owner_credential_stays_in_migrate(compose),
        *emergency_setting_reaches_the_api(compose),
        *session_settings_reach_the_api(compose),
        *logs_are_capped(compose),
        *cloud_proxy_image_is_unprivileged(
            (ROOT / "proxy" / "Dockerfile").read_text(encoding="utf-8")
        ),
    ]


def dead_ports(base: dict, dev: dict) -> list[str]:
    """A published port on a service that no routable network reaches does nothing.

    Docker makes no host binding for a container that is only on `internal: true`
    networks, and compose does not complain, so the file reads as if the port works
    (#88). The dev override must not claim one.
    """
    internal = {
        name
        for name, net in (base.get("networks") or {}).items()
        if (net or {}).get("internal")
    }
    problems = []
    for name, svc in (dev.get("services") or {}).items():
        if not svc.get("ports"):
            continue
        nets = service(base, name).get("networks", [])
        nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
        if nets and all(n in internal for n in nets):
            problems.append(
                f"{name} publishes {svc['ports']} but is only on internal "
                f"network(s) {nets}, so Docker creates no host binding"
            )
    return problems


def mentions_dead_db_port(text: str) -> bool:
    """Prose or config that offers the database on a host port nothing opens."""
    return "DEV_DB_PORT" in text


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

    dev = yaml.safe_load(DEV.read_text(encoding="utf-8"))
    dead = dead_ports(compose, dev)
    check(
        "the dev override publishes no port that does nothing",
        not dead,
        "; ".join(dead),
    )
    for path in (".env.example", "compose.dev.yaml"):
        check(
            f"{path} offers no DEV_DB_PORT, which has no effect",
            not mentions_dead_db_port((ROOT / path).read_text(encoding="utf-8")),
        )
    running = (ROOT / "docs" / "running.md").read_text(encoding="utf-8")
    check(
        "running.md does not point the server tests at the stack's own database",
        "localhost:5432" not in running,
    )

    print("Mutation tests: each rule must notice when it is broken")

    probe = {"services": {DB: {"ports": ["127.0.0.1:5432:5432"]}}}
    check(
        "a dev port on an internal-only service is noticed",
        bool(dead_ports(compose, probe)),
    )
    probe = {"services": {API: {"ports": ["127.0.0.1:8000:8000"]}}}
    check("a dev port on the api is not", not dead_ports(compose, probe))
    check("a DEV_DB_PORT mention is noticed", mentions_dead_db_port("DEV_DB_PORT=5432"))

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

    def hardening_mutation(label: str, mutate) -> None:
        broken = copy.deepcopy(compose)
        mutate(broken["services"])
        check(f"{label} is noticed", bool(container_hardening(broken)))

    for name in (DB, API, PROXY):
        hardening_mutation(
            f"{name} losing no-new-privileges",
            lambda s, n=name: s[n].pop("security_opt", None),
        )
        hardening_mutation(
            f"{name} losing its memory limit", lambda s, n=name: s[n].pop("mem_limit")
        )
        hardening_mutation(
            f"{name} losing its pids limit", lambda s, n=name: s[n].pop("pids_limit")
        )
        hardening_mutation(
            f"{name} losing its cpu limit", lambda s, n=name: s[n].pop("cpus")
        )
        hardening_mutation(
            f"{name} becoming privileged",
            lambda s, n=name: s[n].update(privileged=True),
        )
    for name in (API, PROXY):
        hardening_mutation(
            f"{name} keeping its default capabilities",
            lambda s, n=name: s[n].pop("cap_drop"),
        )
        hardening_mutation(
            f"{name} with a writable root filesystem",
            lambda s, n=name: s[n].update(read_only=False),
        )
    hardening_mutation("the proxy running as root", lambda s: s[PROXY].pop("user"))
    hardening_mutation(
        "the proxy running as uid 0", lambda s: s[PROXY].update(user="0:0")
    )
    hardening_mutation(
        "the proxy adding back SYS_ADMIN",
        lambda s: s[PROXY].update(cap_add=["NET_BIND_SERVICE", "SYS_ADMIN"]),
    )
    hardening_mutation(
        "the api adding any capability back", lambda s: s[API].update(cap_add=["CHOWN"])
    )
    hardening_mutation(
        "the ownership fixer joining a network",
        lambda s: s[PROXY_INIT].update(networks=["edge"]),
    )
    hardening_mutation(
        "the ownership fixer keeping network access",
        lambda s: s[PROXY_INIT].pop("network_mode"),
    )
    hardening_mutation(
        "the ownership fixer keeping every capability",
        lambda s: s[PROXY_INIT].pop("cap_drop"),
    )
    hardening_mutation(
        "the proxy not waiting for the ownership fixer",
        lambda s: s[PROXY].pop("depends_on"),
    )
    hardening_mutation("the ownership fixer being removed", lambda s: s.pop(PROXY_INIT))

    def role_mutation(label: str, mutate) -> None:
        broken = copy.deepcopy(compose)
        mutate(broken["services"])
        check(f"{label} is noticed", bool(owner_credential_stays_in_migrate(broken)))

    role_mutation(
        "the api being given the owner's password",
        lambda s: s[API]["environment"].update(POSTGRES_PASSWORD="x"),
    )
    role_mutation(
        "the api being given a DATABASE_URL",
        lambda s: s[API]["environment"].update(DATABASE_URL="postgresql://x"),
    )
    role_mutation(
        "the api losing both of its restricted credentials",
        lambda s: [
            s[API]["environment"].pop(k)
            for k in ("APP_POSTGRES_PASSWORD", "APP_DATABASE_URL")
        ],
    )
    role_mutation(
        "the api being told to migrate",
        lambda s: s[API]["environment"].update(RUN_MIGRATIONS="true"),
    )
    role_mutation(
        "the api not waiting for migrate", lambda s: s[API]["depends_on"].pop(MIGRATE)
    )
    role_mutation("the migrate service being removed", lambda s: s.pop(MIGRATE))
    role_mutation(
        "migrate joining the internet-facing network",
        lambda s: s[MIGRATE].update(networks=["data", "edge"]),
    )
    role_mutation(
        "migrate publishing a port", lambda s: s[MIGRATE].update(ports=["9:9"])
    )
    role_mutation(
        "migrate restarting forever", lambda s: s[MIGRATE].update(restart="always")
    )
    role_mutation(
        "migrate losing the owner credential",
        lambda s: s[MIGRATE]["environment"].pop("POSTGRES_PASSWORD"),
    )
    for svc_name in compose["services"]:
        broken = copy.deepcopy(compose)
        broken["services"][svc_name].pop("logging")
        check(
            f"{svc_name} losing its log cap is noticed", bool(logs_are_capped(broken))
        )
        broken = copy.deepcopy(compose)
        broken["services"][svc_name]["logging"] = {"driver": "json-file"}
        check(
            f"{svc_name} with a log driver but no size cap is noticed",
            bool(logs_are_capped(broken)),
        )
    for name in SESSION_SETTINGS:
        broken = copy.deepcopy(compose)
        del broken["services"][API]["environment"][name]
        check(
            f"{name} not reaching the api is noticed",
            bool(session_settings_reach_the_api(broken)),
        )
    broken = copy.deepcopy(compose)
    del broken["services"][API]["environment"]["EMERGENCY_ACCESS_IDS"]
    check(
        "EMERGENCY_ACCESS_IDS not reaching the api is noticed",
        bool(emergency_setting_reaches_the_api(broken)),
    )
    hardening_mutation(
        "migrate keeping its default capabilities", lambda s: s[MIGRATE].pop("cap_drop")
    )
    hardening_mutation(
        "migrate with a writable root filesystem",
        lambda s: s[MIGRATE].update(read_only=False),
    )

    real = (ROOT / "proxy" / "Dockerfile").read_text(encoding="utf-8")
    check(
        "the cloud proxy image: a real Dockerfile passes",
        not cloud_proxy_image_is_unprivileged(real),
    )
    check(
        "the cloud proxy image: dropping USER is noticed",
        bool(cloud_proxy_image_is_unprivileged(real.replace("USER 65532:65532", ""))),
    )
    check(
        "the cloud proxy image: dropping the chown is noticed",
        bool(
            cloud_proxy_image_is_unprivileged(
                re.sub(r"^RUN chown.*$", "", real, flags=re.M)
            )
        ),
    )
    check(
        "the cloud proxy image: a chown after USER is noticed",
        bool(
            cloud_proxy_image_is_unprivileged(
                real.replace(
                    "RUN chown -R 65532:65532 /data /config\nUSER 65532:65532",
                    "USER 65532:65532\nRUN chown -R 65532:65532 /data /config",
                )
            )
        ),
    )

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
