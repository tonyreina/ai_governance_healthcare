#!/usr/bin/env python3
"""The data scope is stated where a deployer reads first, for every mode (#34).

The owner decided (R-49): governance metadata only, never patient-identifiable
information, in any storage mode. Before, the only statement was scoped to the
browser-only mode, so the server mode, which scores best on access control and audit,
read as the one fit for patient data. These checks keep the statement at the top of the
README, the docs home page and the deployment guide, keep the comparison table's row,
and keep every page from implying the opposite. The in-app notice in each mode is
tested in a real browser by tests/test_boot_storage.py.

    pixi run test-data-scope
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAD = ("README.md", "docs/index.md", "docs/deploy.md")
STATEMENT = "Governance metadata only."
NEVER = "Never enter patient-identifiable information"
# Wording that would say some mode, or the deployment, is fit for patient data.
IMPLIES_PHI_OK = re.compile(
    r"\b(?:approved|suitable|safe|appropriate|fit)\s+for\s+(?:PHI|ePHI|patient(?:\s+|-)"
    r"(?:data|identifiable|information))",
    re.I,
)
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
# A HIPAA citation framed as an obligation on this system. With patient data out of
# scope, a cited standard names the practice a control follows (#121).
CITES = re.compile(r"45 CFR|HIPAA", re.I)
OBLIGES = re.compile(
    r"\brequired\b|\baddressable\b|\basks for\b|\bmakes? .{0,60}required", re.I
)
PRACTICE_NOTE = "not a legal requirement on this system"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def flat(text: str) -> str:
    """Collapse wrapping and admonition indentation, so a sentence can be found."""
    return " ".join(text.split())


def lead_problems(text: str, *, within: int = 1500) -> list[str]:
    """The statement and the instruction, near the top of the page."""
    head = flat(text[:within])
    problems = []
    if STATEMENT not in head:
        problems.append(f"{STATEMENT!r} is not near the top")
    if NEVER not in head:
        problems.append(f"{NEVER!r} is not near the top")
    elif "any storage mode" not in head:
        problems.append("it does not say it applies in any storage mode")
    return problems


def table_problems(text: str) -> list[str]:
    for line in text.splitlines():
        if line.startswith("| Patient-identifiable information"):
            cells = [c.strip() for c in line.strip("|").split("|")][1:]
            if len(cells) == 2 and all(c == "**Never**" for c in cells):
                return []
            return [f"the row is not Never in both modes: {cells}"]
    return ["the comparison table has no patient-identifiable information row"]


def implies_ok(text: str) -> list[str]:
    """Phrases that call any mode fit for patient data, unless they deny it."""
    hits = []
    for found in IMPLIES_PHI_OK.finditer(flat(text)):
        before = flat(text)[max(0, found.start() - 40) : found.start()].lower()
        if not re.search(r"\b(?:not|never|no|nor|nothing)\b", before):
            hits.append(found.group(0))
    return hits


def hipaa_as_obligation(text: str) -> list[str]:
    """Sentences that cite a HIPAA standard as binding on this system.

    A sentence may say what the rule requires of systems that hold ePHI; it must say
    so, by naming ePHI, rather than read as a requirement this deployment is under.
    """
    hits = []
    for sentence in re.split(r"(?<=[.!?])\s+", flat(text)):
        cited = CITES.search(sentence) and OBLIGES.search(sentence)
        if cited and "ePHI" not in sentence:
            hits.append(sentence[:120])
    return hits


def main() -> int:
    print("The statement leads each page a deployer reads first")
    for rel in LEAD:
        problems = lead_problems((ROOT / rel).read_text(encoding="utf-8"))
        check(rel, not problems, "; ".join(problems))

    running = (ROOT / "docs" / "running.md").read_text(encoding="utf-8")
    problems = table_problems(running)
    check(
        "the comparison table says Never in every mode",
        not problems,
        "; ".join(problems),
    )

    print("No page says a mode or the deployment is fit for patient data")
    for path in DOCS:
        hits = implies_ok(path.read_text(encoding="utf-8"))
        check(path.relative_to(ROOT).as_posix(), not hits, ", ".join(hits))

    print("A HIPAA citation names the practice a control follows (#121)")
    deploy = (ROOT / "docs" / "deploy.md").read_text(encoding="utf-8")
    check(
        "the deployment guide says what its citations mean, near the top",
        PRACTICE_NOTE in flat(deploy[:4000]),
    )
    for path in DOCS:
        hits = hipaa_as_obligation(path.read_text(encoding="utf-8"))
        check(
            f"{path.relative_to(ROOT).as_posix()} cites no standard as binding here",
            not hits,
            " | ".join(hits[:3]),
        )

    print("The rules notice (mutation)")
    check(
        "'45 CFR 164.308(a)(7) makes a backup plan *required*' is noticed",
        bool(
            hipaa_as_obligation("45 CFR 164.308(a)(7) makes a backup plan *required*.")
        ),
    )
    check(
        "'is *addressable*' is noticed",
        bool(hipaa_as_obligation("45 CFR 164.312(a)(2)(iv) is *addressable*: do it.")),
    )
    check(
        "the same, said of systems that hold ePHI, is not",
        not hipaa_as_obligation(
            "For systems that hold ePHI, 45 CFR 164.308(a)(7) makes a plan required."
        ),
    )
    good = (ROOT / "README.md").read_text(encoding="utf-8")
    check(
        "a dropped statement is noticed",
        bool(lead_problems(good.replace(STATEMENT, ""))),
    )
    check(
        "a dropped instruction is noticed",
        bool(lead_problems(good.replace(NEVER, "x"))),
    )
    check(
        "a statement scoped to one mode is noticed",
        bool(lead_problems(good.replace("any storage mode", "this mode"))),
    )
    check(
        "a statement moved far down the page is noticed",
        bool(lead_problems("x\n" * 2000 + good)),
    )
    check(
        "a row that allows one mode is noticed",
        bool(table_problems(running.replace(
            "| Patient-identifiable information | **Never** | **Never** |",
            "| Patient-identifiable information | **Never** | Yes |",
        ))),
    )  # fmt: skip
    check("a missing row is noticed", bool(table_problems("| a | b |")))
    check(
        "'the server is approved for PHI' is noticed",
        bool(implies_ok("The server mode is approved for PHI.")),
    )
    check(
        "'suitable for patient data' is noticed",
        bool(implies_ok("This deployment is suitable for patient data.")),
    )
    check(
        "a denial is not",
        not implies_ok("nothing here makes the deployment suitable for patient data"),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("data scope checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
