#!/usr/bin/env python3
"""A deployment guide must not pick the data's country for the reader (#58).

Every command example in docs/deploy.md named a US region, so a hospital that copied
them stored records in the US without ever deciding to. Where the data lives is a
decision (a DPO's, for an EU or UK deployment), not a default. These checks keep the
command examples free of concrete regions and keep the "Data residency" section that
tells the reader it is their call. They are text checks on the guide, each with a
mutation test so a rule that stops noticing is itself noticed.

    pixi run test-deploy-residency
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "deploy.md"

# Region names as the three providers spell them.
REGION = re.compile(
    r"\b(?:"
    r"(?:us|eu|ap|sa|ca|me|af|il)-[a-z]+-\d"  # AWS
    r"|(?:us|europe|asia|australia|northamerica|southamerica|me|africa)"  # GCP
    r"-[a-z]+\d+"
    r"|(?:east|west|north|south|central)(?:us|europe)\d?"  # Azure
    r"|(?:uk|germany|france|swiss|norway|sweden)[a-z]*(?:south|west|north|central)\w*"
    r")\b"
)  # fmt: skip

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def code_blocks(text: str) -> list[tuple[int, str]]:
    """(first line number, body) of each fenced block."""
    blocks = []
    for found in re.finditer(r"^```[a-z]*\n(.*?)^```", text, re.M | re.S):
        blocks.append((text.count("\n", 0, found.start(1)) + 1, found.group(1)))
    return blocks


def hardcoded_regions(text: str) -> list[str]:
    """Each concrete region named inside a command example."""
    problems = []
    for start, body in code_blocks(text):
        for offset, line in enumerate(body.splitlines()):
            for hit in REGION.findall(line):
                problems.append(f"line {start + offset}: {hit!r}")
    return problems


def section(text: str, heading: str) -> str:
    found = re.search(
        rf"^### {re.escape(heading)}\n(.*?)(?=^#{{2,3}} )", text, re.M | re.S
    )
    return found.group(1) if found else ""


def residency_problems(text: str) -> list[str]:
    body = section(text, "Data residency")
    if not body:
        return ["there is no 'Data residency' section"]
    problems = []
    for provider, regions in (
        ("Google Cloud", ("europe-west1", "europe-west4")),
        ("AWS", ("eu-central-1", "eu-west-1")),
        ("Azure", ("westeurope", "germanywestcentral")),
    ):
        if provider not in body or not any(r in body for r in regions):
            problems.append(f"it names no EU region for {provider}")
    if "not legal advice" not in body.lower():
        problems.append("it does not say it is not legal advice")
    if "transfer" not in body.lower():
        problems.append("it does not raise the cross-border transfer question")
    if re.search(r"\badequate\b|\bGDPR[- ]compliant\b", body, re.I):
        problems.append(
            "it asserts adequacy or compliance, which is a legal conclusion"
        )
    if "unverified" not in body.lower():
        problems.append("it does not mark the provider region names as unverified")
    return problems


def main() -> int:
    text = GUIDE.read_text(encoding="utf-8")

    print("the guide")
    check(
        "no command example names a concrete region",
        not hardcoded_regions(text),
        "; ".join(hardcoded_regions(text)[:6]),
    )
    check(
        "the Data residency section is complete",
        not residency_problems(text),
        "; ".join(residency_problems(text)),
    )

    print("the rules notice (mutation)")
    check(
        "a gcloud region is caught",
        bool(
            hardcoded_regions("```bash\ngcloud run deploy --region=us-central1\n```\n")
        ),
    )
    check(
        "an AWS region is caught",
        bool(hardcoded_regions("```bash\nREGION=us-east-1\n```\n")),
    )
    check(
        "an Azure location is caught",
        bool(hardcoded_regions("```bash\naz group create --location eastus\n```\n")),
    )
    check(
        "a European region is caught too",
        bool(hardcoded_regions("```bash\nREGION=europe-west4\n```\n")),
    )
    check(
        "a placeholder is not",
        not hardcoded_regions('```bash\ngcloud run deploy --region="$REGION"\n```\n'),
    )
    check(
        "a region in prose outside a block is allowed",
        not hardcoded_regions("Use europe-west4 or eu-central-1.\n"),
    )
    good = (
        "### Data residency\n\nGoogle Cloud europe-west4, AWS eu-central-1, Azure "
        "westeurope (unverified). Cross-border transfer is for your DPO. This is "
        "not legal advice.\n\n## Next\n"
    )
    check("a complete section passes", not residency_problems(good))
    check("a missing section is caught", bool(residency_problems("## Next\n")))
    check(
        "a missing provider is caught",
        bool(residency_problems(good.replace("AWS eu-central-1, ", ""))),
    )
    check(
        "a missing disclaimer is caught",
        bool(residency_problems(good.replace("not legal advice", "fine"))),
    )
    check(
        "a missing transfer question is caught",
        bool(residency_problems(good.replace("transfer", "move"))),
    )
    check(
        "a claim of adequacy is caught",
        bool(residency_problems(good.replace("is for", "is adequate, for"))),
    )
    check(
        "a missing unverified mark is caught",
        bool(residency_problems(good.replace("(unverified)", ""))),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("deploy residency checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
