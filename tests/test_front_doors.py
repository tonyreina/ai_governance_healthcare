#!/usr/bin/env python3
"""The identity settings the docs give for each front door match what is tested (C-02).

tests/test_proxy_identity.py runs a real Caddy once per front door, with the
settings in its `FRONT_DOORS` list. That list is a hand copy of what `.env.example`
and docs/self-hosting.md tell an operator to set, and it was kept in step with
them by a comment alone: a documented setting could change, or a new front door
could be documented, and the Caddy test would go on proving the old one. The IAP
case also left out `IDENTITY_STRIP_PREFIX`, which the guide requires for IAP.

This reads the documented settings out of the two files and fails when they and the
test's copy differ, in either direction. Then it breaks each side in a copy, one
way at a time, and demands that the comparison notice. No Docker.

    pixi run test-front-doors
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = ROOT / ".env.example"
GUIDE = ROOT / "docs" / "self-hosting.md"
GUIDE_HEADING = "### Identity comes from the proxy"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tp = load("proxy_identity", ROOT / "tests" / "test_proxy_identity.py")

# Which `# --- <title> ---` block of .env.example documents which tested door.
DOOR_TITLES = {
    "Google Cloud IAP": "Google Cloud",
    "AWS ALB + OIDC": "AWS",
    "Azure Easy Auth": "Azure",
    "oauth2-proxy": "oauth2-proxy",
}
# The doors the guide's own example block names (it does not name oauth2-proxy).
GUIDE_DOORS = ("Google Cloud IAP", "AWS ALB + OIDC", "Azure Easy Auth")

SETTING = re.compile(r"^#?\s*(IDENTITY_[A-Z_]+)=(\S*)")
BLOCK_TITLE = re.compile(r"^# --- (.+?) -+$")
RULE = re.compile(r"^# -{10,}$")


def documented_in_env(text: str) -> dict[str, dict[str, str]]:
    """{block title: {setting: value}} for each `# --- title ---` block."""
    blocks: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        title = BLOCK_TITLE.match(line)
        if title:
            current = blocks.setdefault(title.group(1), {})
        elif RULE.match(line):
            current = None
        elif current is not None and (setting := SETTING.match(line)):
            current[setting.group(1)] = setting.group(2)
    return {title: found for title, found in blocks.items() if found}


def documented_in_guide(text: str) -> list[tuple[str, str]]:
    """The (setting, value) lines of the bash block under the identity heading."""
    section = text[text.index(GUIDE_HEADING) :]
    fence = section.index("```bash")
    code = section[fence : section.index("```", fence + 7)]
    return [
        (m.group(1), m.group(2))
        for line in code.splitlines()
        if (m := SETTING.match(line))
    ]


def door_settings(env: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k.startswith("IDENTITY_")}


def drift(
    env_text: str, guide_text: str, doors: list[tuple] | None = None
) -> list[str]:
    """Every way the documented settings and the tested doors disagree."""
    doors = tp.FRONT_DOORS if doors is None else doors
    tested = {name: door_settings(env) for name, env, _sent, _expected in doors}
    problems: list[str] = []
    blocks = documented_in_env(env_text)

    for name, keyword in DOOR_TITLES.items():
        matching = [t for t in blocks if keyword in t]
        if len(matching) != 1:
            problems.append(f"{name}: .env.example has {len(matching)} blocks for it")
            continue
        if name not in tested:
            problems.append(f"{name}: documented in .env.example but not tested")
            continue
        if blocks[matching[0]] != tested[name]:
            problems.append(
                f"{name}: .env.example says {blocks[matching[0]]}, the test uses "
                f"{tested[name]}"
            )
    claimed = [t for t in blocks if not any(k in t for k in DOOR_TITLES.values())]
    problems += [
        f".env.example documents a front door the test lacks: {t}" for t in claimed
    ]
    problems += [
        f"{name}: tested but not documented in .env.example"
        for name in tested
        if name not in DOOR_TITLES
    ]

    # The guide: every ID source it lists is a tested door's, the three doors it
    # names are all there, and its prefix is the IAP door's.
    by_id = {s.get("IDENTITY_ID_SOURCE"): n for n, s in tested.items()}
    listed = documented_in_guide(guide_text)
    named = {by_id.get(v) for k, v in listed if k == "IDENTITY_ID_SOURCE"}
    for k, v in listed:
        if k == "IDENTITY_ID_SOURCE" and v not in by_id:
            problems.append(f"the guide's {k}={v} is not any tested door's")
    for door in GUIDE_DOORS:
        if door not in named:
            problems.append(f"the guide does not list {door}")
    guide_prefix = [v for k, v in listed if k == "IDENTITY_STRIP_PREFIX"]
    iap_prefix = tested.get("Google Cloud IAP", {}).get("IDENTITY_STRIP_PREFIX")
    if guide_prefix != [iap_prefix] or not iap_prefix:
        problems.append(
            f"the guide's IDENTITY_STRIP_PREFIX {guide_prefix} is not the IAP "
            f"door's {iap_prefix!r}"
        )
    return problems


failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else ' -- ' + detail}")
    if not ok:
        failures.append(name)


def main() -> int:
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    guide_text = GUIDE.read_text(encoding="utf-8")

    print("The documented settings, against the tested doors")
    found = drift(env_text, guide_text)
    check(
        "every documented front door setting matches the test's copy",
        not found,
        "; ".join(found),
    )
    iap = next(env for name, env, _s, _e in tp.FRONT_DOORS if "IAP" in name)
    check(
        "the IAP case carries IDENTITY_STRIP_PREFIX, which the guide requires",
        iap.get("IDENTITY_STRIP_PREFIX") == "accounts.google.com:",
        str(iap),
    )
    check(
        "all four documented doors are tested",
        len(tp.FRONT_DOORS) == len(DOOR_TITLES) == len(documented_in_env(env_text)),
        f"{len(tp.FRONT_DOORS)} tested, {len(documented_in_env(env_text))} documented",
    )

    print("Each side, drifted in a copy")
    alb = "# IDENTITY_ID_SOURCE={http.request.header.X-Amzn-Oidc-Identity}"
    prefix = "# IDENTITY_STRIP_PREFIX=accounts.google.com:"
    guide_iap = "IDENTITY_STRIP_PREFIX=accounts.google.com:"
    azure_guide = "# IDENTITY_ID_SOURCE={http.request.header.X-Ms-Client-Principal-Id}"
    env_mutants = [
        ("a documented ALB source changes", alb, alb.replace("Identity", "Subject")),
        ("the documented IAP prefix is dropped", prefix, ""),
        ("the documented IAP prefix changes", prefix, prefix + "x"),
        (
            "a documented oauth2-proxy email source changes",
            "{http.request.header.X-Forwarded-Email}",
            "{http.request.header.X-Forwarded-Mail}",
        ),
        (
            "a new front door is documented",
            "# --- Self-hosted oauth2-proxy",
            "# --- Okta ----------\n# IDENTITY_ID_SOURCE={http.request.header.X-Okta}\n"
            "# --- Self-hosted oauth2-proxy",
        ),
        (
            "a documented door loses its block",
            "# --- Azure: App Service",
            "# Azure: App Service",
        ),
    ]
    for name, old, new in env_mutants:
        assert old in env_text, name
        check(
            f"{name} in .env.example: noticed",
            bool(drift(env_text.replace(old, new, 1), guide_text)),
        )
    guide_mutants = [
        ("the guide's IAP prefix is dropped", guide_iap, ""),
        ("the guide's prefix changes", guide_iap, guide_iap + "x"),
        (
            "the guide's Azure source changes",
            azure_guide.lstrip("# "),
            azure_guide.lstrip("# ").replace("Principal-Id", "Principal-Oid"),
        ),
        (
            "the guide names a source no door is tested with",
            "IDENTITY_ID_SOURCE={http.request.header.X-Goog-Authenticated-User-Id}",
            "IDENTITY_ID_SOURCE={http.request.header.X-Other}",
        ),
    ]
    for name, old, new in guide_mutants:
        assert old in guide_text, name
        check(
            f"{name}: noticed",
            bool(drift(env_text, guide_text.replace(old, new, 1))),
        )

    def without(door: str, key: str):
        return [
            (n, {k: v for k, v in e.items() if k != key} if door in n else e, s, x)
            for n, e, s, x in tp.FRONT_DOORS
        ]

    check(
        "the test's IAP case losing IDENTITY_STRIP_PREFIX: noticed",
        bool(drift(env_text, guide_text, without("IAP", "IDENTITY_STRIP_PREFIX"))),
    )
    check(
        "the test's Azure case losing a source: noticed",
        bool(drift(env_text, guide_text, without("Azure", "IDENTITY_NAME_SOURCE"))),
    )
    check(
        "the test dropping a documented door: noticed",
        bool(drift(env_text, guide_text, tp.FRONT_DOORS[:3])),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("front door settings checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
