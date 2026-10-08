#!/usr/bin/env python3
"""Look for patient identifiers that should never have been entered (#66).

The scope is governance metadata only, never patient-identifiable information, in any
mode (R-49). That is a policy, and the place it fails is a free-text field: an example
case or a cohort extract pasted into evidence or a rationale. This scans the records
for the few things that look like a patient identifier with very few false alarms:

* a Social Security number (dashed, or labeled);
* a medical record number, patient id, date of birth or patient name, **when it is
  labeled as one** ("MRN: A1234567", "DOB 03/14/1961", "Patient name: ...");
* a phone number, outside the model card's contact field, where one is expected.

It deliberately does **not** look for names or dates on their own. A governance record
is made of them (sponsors, reviewers, signers, review and due dates), so a detector for
them flags every record and gets ignored (R-50). It uses no model and sends nothing
anywhere.

    python3 scripts/phi_scan.py              # report, exit 0
    python3 scripts/phi_scan.py --strict     # exit 1 if anything matched, for cron
    make phi-scan [STRICT=1]

It reads, through the running database container, the live records, every revision
that has not been purged and every audit entry that has not been redacted, because a
value edited out of the live record is still in the history. It reports where and
what kind, **never the matched text**: a report that quotes it is a second copy of the
problem. A match is a place to look; no match is not a finding that there is no
patient information.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, assert_never

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preflight import ENV_FILE, read_env

PATTERNS_VERSION = "1"


class Kind(StrEnum):
    SSN = "ssn"
    MRN = "mrn"
    DOB = "dob"
    PATIENT_NAME = "patient-name"
    PHONE = "phone"


class Source(StrEnum):
    CURRENT = "current"
    REVISION = "revision"
    LOG = "log"


_DATE = (
    r"(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?i:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?i:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4})"
)

PATTERNS: dict[Kind, tuple[re.Pattern[str], ...]] = {
    Kind.SSN: (
        re.compile(
            r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])"
        ),
        re.compile(
            r"(?i:\bSSN\b|\bsocial\s+security(?:\s+(?:number|no\.?|#))?)"
            r"\s*[:#=]?\s*\d{3}[- ]?\d{2}[- ]?\d{4}(?!\d)"
        ),
    ),
    Kind.MRN: (
        re.compile(
            r"(?i:\bMRN\b|\bmedical\s+record\s+(?:number|no\.?|num|#)"
            r"|\bpatient\s+(?:id|identifier|no\.?|number|#))"
            r"\s*[:#=]?\s*(?=[A-Za-z0-9-]*\d)[A-Za-z0-9][A-Za-z0-9-]{3,}"
        ),
    ),
    Kind.DOB: (
        re.compile(
            r"(?i:\bDOB\b|\bD\.O\.B\.?|\bdate\s+of\s+birth|\bborn(?:\s+on)?)"
            rf"\s*[:=-]?\s*{_DATE}"
        ),
    ),
    Kind.PATIENT_NAME: (
        re.compile(r"(?i:\b(?:patient|pt)\.?\s*name)\s*[:=-]\s*[A-Z][a-z]+"),
    ),
    Kind.PHONE: (
        re.compile(
            r"(?<!\d)(?<!\d\.)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}"
            r"(?!\d|\.\d)"
        ),
    ),
}

DESCRIBE: dict[Kind, str] = {
    Kind.SSN: "an SSN-shaped number",
    Kind.MRN: "a labeled medical record number or patient id",
    Kind.DOB: "a labeled date of birth",
    Kind.PATIENT_NAME: "a labeled patient name",
    Kind.PHONE: "a phone number (a staff number matches too)",
}

# Where a kind is expected and is not patient data: the model card asks for an
# "Email or phone" contact for inquiries, which is a vendor's or a team's.
EXPECTED: dict[Kind, frozenset[str]] = {
    Kind.PHONE: frozenset({"card.contact"}),
}

QUERY = """
SELECT json_build_object('source', 'current', 'project', id, 'ref', NULL,
                         'doc', doc)::text
  FROM projects
UNION ALL
SELECT json_build_object('source', 'revision', 'project', project_id, 'ref', rev,
                         'doc', doc)::text
  FROM project_version WHERE purged_at IS NULL
UNION ALL
SELECT json_build_object('source', 'log', 'project', project_id, 'ref', seq,
                         'doc', entry)::text
  FROM project_log WHERE purged_at IS NULL AND NOT is_system;
"""


@dataclass(frozen=True)
class Finding:
    project: str
    source: Source
    path: str
    kind: Kind
    refs: tuple[int, ...]


def strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a JSON value, with its dotted path."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from strings(item, f"{path}[{index}]")


def kinds_in(text: str) -> set[Kind]:
    return {
        kind for kind, pats in PATTERNS.items() if any(p.search(text) for p in pats)
    }


def scan_doc(doc: Any) -> list[tuple[str, Kind]]:
    """(path, kind) for each string that matches, skipping where a kind is expected."""
    hits = []
    for path, text in strings(doc):
        for kind in sorted(kinds_in(text)):
            if path not in EXPECTED.get(kind, frozenset()):
                hits.append((path, kind))
    return hits


def scan_rows(
    rows: Iterable[dict[str, Any]],
) -> tuple[list[Finding], dict[Source, int]]:
    """Group hits by project, source, path and kind, collecting revisions/entries."""
    grouped: dict[tuple[str, Source, str, Kind], list[int]] = {}
    counts = dict.fromkeys(Source, 0)
    for row in rows:
        source = Source(row["source"])
        counts[source] += 1
        for path, kind in scan_doc(row["doc"]):
            # A log entry's fields are one place to look, whatever the field.
            where = "audit log entry" if source is Source.LOG else path
            refs = grouped.setdefault((row["project"], source, where, kind), [])
            if row.get("ref") is not None and row["ref"] not in refs:
                refs.append(row["ref"])
    findings = [
        Finding(project, source, where, kind, tuple(sorted(refs)))
        for (project, source, where, kind), refs in grouped.items()
    ]
    order = list(Source)
    findings.sort(key=lambda f: (f.project, order.index(f.source), f.path, f.kind))
    return findings, counts


def ranges(numbers: tuple[int, ...]) -> str:
    """(1, 2, 3, 7) -> '1-3, 7'."""
    out: list[str] = []
    start = prev = None
    for n in numbers:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            out.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = n
    if start is not None:
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(out)


def where_text(finding: Finding) -> str:
    match finding.source:
        case Source.CURRENT:
            return "the live record"
        case Source.REVISION:
            return f"revision(s) {ranges(finding.refs)}"
        case Source.LOG:
            return f"audit entr(ies) {ranges(finding.refs)}"
        case _:
            assert_never(finding.source)


def render(findings: list[Finding], counts: dict[Source, int]) -> str:
    lines = [
        f"phi-scan: patterns v{PATTERNS_VERSION}: SSNs; labeled medical record "
        "numbers, dates of birth and patient names; phone numbers outside the "
        "contact field.",
        f"scanned {counts[Source.CURRENT]} live record(s), "
        f"{counts[Source.REVISION]} unpurged revision(s), "
        f"{counts[Source.LOG]} unredacted audit entr(ies).",
        "",
    ]
    if not findings:
        lines.append(
            "No match for these patterns. That is not a finding that no patient "
            "information is present: names, dates and free-form descriptions are not "
            "checked."
        )
        return "\n".join(lines)
    for f in findings:
        lines.append(f"  {f.project}  {f.path}: {DESCRIBE[f.kind]}, in {where_text(f)}")
    projects = len({f.project for f in findings})
    lines += [
        "",
        f"{len(findings)} match(es) in {projects} project(s). The matched text is not "
        "shown: open the record and judge it. A match is a place to look, not proof "
        "of patient information.",
        "To remove a value entered by mistake: take it out of the live record, then "
        "an owner destroys the history (DELETE /api/projects/<id>/versions), which "
        "empties every revision and redacts the audit log. See docs/self-hosting.md, "
        '"Deleting and destroying data". Earlier backups still hold it.',
    ]
    return "\n".join(lines)


def fetch(psql: list[str]) -> list[dict[str, Any]]:
    command = [*psql, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"]
    done = subprocess.run(
        command, input=QUERY, capture_output=True, text=True, timeout=600
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip()[-300:] or "psql failed")
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None, psql: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    unknown = [a for a in args if a != "--strict"]
    if unknown:
        print("usage: phi_scan.py [--strict]", file=sys.stderr)
        return 2
    if psql is None:
        env = read_env(ENV_FILE)
        psql = [
            "docker", "compose", "exec", "-T", "db", "psql",
            "-U", env.get("POSTGRES_USER", "chai"),
            "-d", env.get("POSTGRES_DB", "chai"),
        ]  # fmt: skip
    try:
        findings, counts = scan_rows(fetch(psql))
    except (RuntimeError, OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"phi-scan: {exc}", file=sys.stderr)
        return 2
    print(render(findings, counts))
    return 1 if findings and "--strict" in args else 0


if __name__ == "__main__":
    sys.exit(main())
