#!/usr/bin/env python3
"""`make phi-scan` finds a pasted patient identifier, and stays quiet on a governance
record (#66, R-50).

Three layers, each against the real thing:

* the patterns, on text written to look like what gets pasted and on the names, dates,
  versions, statistics and contact details a governance record is made of;
* the false-positive rate on this corpus specifically: the dashboard's own sample
  projects, read out of a real browser, must produce no match at all;
* the real script against a real PostgreSQL with the real migrations: the live record,
  the unpurged history and the audit log are all scanned, purged content is not, the
  matched text is never printed, and `--strict` fails the run.

Needs Docker and Chromium.

    pixi run test-phi-scan
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))
APP = ROOT / "docs" / "app" / "index.html"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ps = load("phi_scan", ROOT / "scripts" / "phi_scan.py")
vb = load("verify_backup", ROOT / "scripts" / "verify_backup.py")
Kind = ps.Kind

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  {status}")
    if not ok:
        failures.append(name)


# Each is what an example case or a cohort extract pasted into a field looks like.
POSITIVES = [
    (Kind.SSN, "Example case: 123-45-6789, readmitted"),
    (Kind.SSN, "SSN: 123456789"),
    (Kind.SSN, "social security number 123 45 6789"),
    (Kind.MRN, "MRN: A1234567"),
    (Kind.MRN, "mrn 00482913"),
    (Kind.MRN, "Medical record number 77-301-2"),
    (Kind.MRN, "patient id: 4471920"),
    (Kind.DOB, "DOB 03/14/1961"),
    (Kind.DOB, "date of birth: 1961-03-14"),
    (Kind.DOB, "born on March 14, 1961"),
    (Kind.DOB, "D.O.B. 14 Mar 1961"),
    (Kind.PATIENT_NAME, "Patient name: Smith, John"),
    (Kind.PATIENT_NAME, "pt name - Garcia"),
    (Kind.PHONE, "call the patient at (555) 201-3344."),
    (Kind.PHONE, "+1 555.201.3344"),
]

# What a governance record is made of. None of it may match.
NEGATIVES = [
    "Dr. Jane Q. Doe, Chief Medical Officer",
    "Alan Smith (CMIO), Beatriz Jones (data science), Chidi Okafor (nursing)",
    "Signed off by jane.doe@hospital.org on 2026-03-14",
    "Next periodic review 03/14/2027; due 2026-09-30",
    "n=412 adults, 2019-01 to 2023-06, two sites",
    "AUROC 0.81 (95% CI 0.78-0.84), sensitivity 0.72",
    "Model version 2.13.5, build 2026.03.14",
    "Validated on 12,345 encounters across 3 hospitals",
    "MRN fields were removed before the extract",
    "Patient identifiers were excluded; patient id fields dropped",
    "The patient population is adults aged 18-89",
    "Born-digital documentation pipeline",
    "Ticket INC-2026-004512, CAB approval 2026-05-02",
    "Mean age 61.4, SD 14.2; 54% female",
    "ISO 14971:2019 and IEC 62304:2006",
]


def unit() -> None:
    print("The patterns")
    for kind, text in POSITIVES:
        found = ps.kinds_in(text)
        check(f"{kind}: {text!r}", kind in found, str(found))
    for text in NEGATIVES:
        found = ps.kinds_in(text)
        check(f"no match: {text!r}", not found, str(found))

    doc = {
        "card": {"contact": "AI team, 555-201-3344"},
        "items": {"s2-1": {"evidence": "see 555-201-3344"}},
    }
    hits = ps.scan_doc(doc)
    check(
        "a phone number in the contact field is expected, not flagged",
        ("card.contact", Kind.PHONE) not in hits,
        str(hits),
    )
    check(
        "the same number in evidence is flagged",
        ("items.s2-1.evidence", Kind.PHONE) in hits,
        str(hits),
    )
    check(
        "a list index is part of the path",
        ps.scan_doc({"metrics": [{"pop": "x"}, {"pop": "MRN: A1234567"}]})
        == [("metrics[1].pop", Kind.MRN)],
    )
    check(
        "revision ranges are compressed",
        ps.ranges((1, 2, 3, 7, 9, 10)) == "1-3, 7, 9-10",
    )

    clean = ps.render([], dict.fromkeys(ps.Source, 0))
    check(
        "a clean run does not claim there is no patient information",
        "not a finding that no patient information is present" in clean
        and "no phi" not in clean.lower(),
        clean,
    )
    check("a clean run says what it does not check", "names, dates" in clean)

    # Mutation: a pattern set that loses a kind is noticed by the positives above.
    saved = ps.PATTERNS[Kind.SSN]
    ps.PATTERNS[Kind.SSN] = ()
    check(
        "dropping the SSN patterns is noticed",
        Kind.SSN not in ps.kinds_in(POSITIVES[0][1]),
    )
    ps.PATTERNS[Kind.SSN] = saved
    saved = dict(ps.EXPECTED)
    ps.EXPECTED.clear()
    check(
        "dropping the contact-field exception is noticed",
        ("card.contact", Kind.PHONE) in ps.scan_doc(doc),
    )
    ps.EXPECTED.update(saved)


def sample_corpus() -> None:
    print("The dashboard's own sample projects produce no match")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        check("playwright is available", False, "run through pixi")
        return
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        docs = page.evaluate(
            "[...PROJECTS.values()].map(p => JSON.parse(JSON.stringify(p)))"
        )
        browser.close()
    strings = sum(1 for d in docs for _ in ps.strings(d))
    hits = [
        (d.get("meta", {}).get("solution"), h) for d in docs for h in ps.scan_doc(d)
    ]
    check(f"{len(docs)} sample projects were read", len(docs) >= 10, str(len(docs)))
    check(f"no match across {strings} strings", not hits, str(hits[:6]))


def docker(*args: str, stdin: bytes | None = None):
    return subprocess.run(["docker", *args], input=stdin, capture_output=True)


def psql(container: str, sql: str) -> str:
    done = docker("exec", container, "psql", "-U", "chai", "-d", "chai", "-tAc", sql)
    assert done.returncode == 0, done.stderr.decode()[-300:]
    return done.stdout.decode().strip()


def start() -> str:
    name = f"chai-phi-{secrets.token_hex(3)}"
    done = docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "POSTGRES_USER=chai", "-e", "POSTGRES_DB=chai",
        "-e", f"POSTGRES_PASSWORD={secrets.token_hex(8)}",
        "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
        vb.production_image(),
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode()[-300:]
    streak = 0
    for _ in range(120):
        ready = docker("exec", name, "pg_isready", "-U", "chai", "-d", "chai")
        streak = streak + 1 if ready.returncode == 0 else 0
        if streak >= 2:
            break
        time.sleep(0.6)
    for migration in sorted((ROOT / "server" / "migrations").glob("*.sql")):
        done = docker(
            "exec", "-i", name, "psql", "-U", "chai", "-d", "chai",
            "-v", "ON_ERROR_STOP=1", "-q", "-f", "-",
            stdin=migration.read_bytes(),
        )  # fmt: skip
        assert done.returncode == 0, done.stderr.decode()[-400:]
    return name


PASTED_SSN = "123-45-6789"
PASTED_MRN = "A7731902"
PASTED_DOB = "03/14/1961"
SECRETS = (PASTED_SSN, PASTED_MRN, PASTED_DOB, "201-3344")


def seed(name: str) -> None:
    clean = '{"meta":{"solution":"Sepsis","reviewers":"Alan Smith, Beatriz Jones"}}'
    pasted = (
        '{"meta":{"solution":"Sepsis"},'
        f'"items":{{"s2-1":{{"evidence":"Example case: {PASTED_SSN}"}}}},'
        '"card":{"contact":"AI team, 555-201-3344"}}'
    )
    psql(
        name,
        f"""
        INSERT INTO projects (id, doc) VALUES ('p1', '{pasted}'), ('p2', '{clean}');
        INSERT INTO project_version (project_id, rev, doc, content_md5, incarnation)
        VALUES ('p1', 1, '{clean}', 'a', gen_random_uuid()),
               ('p1', 2, '{pasted}', 'b', gen_random_uuid()),
               ('p1', 3, '{pasted}', 'c', gen_random_uuid()),
               ('p2', 1, '{clean}', 'd', gen_random_uuid()),
               ('gone', 1, '{{"meta":{{"scope":"MRN: {PASTED_MRN}"}}}}', 'e',
                gen_random_uuid());
        INSERT INTO project_version
               (project_id, rev, doc, content_md5, incarnation, purged_at, purged_by)
        VALUES ('p2', 2, '{{}}', 'f', gen_random_uuid(), now(), 'dpo@hosp.org');
        INSERT INTO project_log (project_id, by_id, entry) VALUES
          ('p1', 'a@hosp.org', '{{"text":"Changed evidence to DOB {PASTED_DOB}"}}'),
          ('p2', 'a@hosp.org', '{{"text":"Signed off 2026-03-14 by Alan Smith"}}');
        """,
    )


def run(name: str, *args: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    prefix = ["docker", "exec", "-i", name, "psql", "-U", "chai", "-d", "chai"]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ps.main(list(args), psql=prefix)
    return code, out.getvalue() + err.getvalue()


def integration() -> None:
    print("The real script, against a real PostgreSQL")
    if not shutil.which("docker"):
        if REQUIRE_TESTS:
            check("docker is available", False, "REQUIRE_TESTS is set")
        else:
            print("  skip  docker unavailable: the database scan is not checked")
        return
    name = start()
    try:
        seed(name)
        before = psql(name, "SELECT count(*) FROM project_version")
        rows = ps.fetch(
            ["docker", "exec", "-i", name, "psql", "-U", "chai", "-d", "chai"]
        )
        findings, counts = ps.scan_rows(rows)
        got = {(f.project, f.source, f.path, f.kind, f.refs) for f in findings}
        check(
            "the live record is scanned",
            ("p1", ps.Source.CURRENT, "items.s2-1.evidence", Kind.SSN, ()) in got,
            str(got),
        )
        check(
            "the history is scanned, and the revisions are named",
            ("p1", ps.Source.REVISION, "items.s2-1.evidence", Kind.SSN, (2, 3)) in got,
            str(got),
        )
        check(
            "a deleted project's surviving revisions are scanned",
            any(f.project == "gone" and f.kind is Kind.MRN for f in findings),
            str(got),
        )
        check(
            "the audit log is scanned",
            any(f.source is ps.Source.LOG and f.kind is Kind.DOB for f in findings),
            str(got),
        )
        check(
            "nothing from the clean project, the contact field or a purged revision",
            not any(f.project == "p2" for f in findings)
            and not any(f.path == "card.contact" for f in findings),
            str(got),
        )
        check(
            "purged revisions are not counted as scanned",
            counts[ps.Source.REVISION] == 5,
            str(counts),
        )

        code, text = run(name)
        check("a report run exits 0", code == 0, text[-300:])
        leaked = [s for s in SECRETS if s in text]
        check("the matched text is never printed", not leaked, str(leaked))
        check(
            "it says how to remove a value",
            "/versions" in text and "live record" in text,
        )
        check("it says earlier backups still hold it", "backups" in text)

        code, _ = run(name, "--strict")
        check("--strict fails the run when something matched", code == 1)
        code, _ = run(name, "--nonsense")
        check("an unknown flag is a usage error, not a scan", code == 2)
        check(
            "it changed nothing",
            psql(name, "SELECT count(*) FROM project_version") == before,
        )
    finally:
        docker("rm", "-f", name)


def main() -> int:
    unit()
    sample_corpus()
    integration()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("phi-scan checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
