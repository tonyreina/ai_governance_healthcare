#!/usr/bin/env python3
"""examples/croissant_export.py must not publish named people by default (#60).

A Croissant record exists to be published and indexed. The exporter withheld
cohort detail unless asked, and said why, but put `meta.reviewers` and
`meta.sponsor` into `maintainer` unconditionally: the clinical sponsor and the
review team, by name, linked to a named model, a site and a time. That is
personal data (GDPR Art. 4(1)), and it is the detail that supports targeted
social engineering against the person who has authority over a deployment.

So individuals are gated the way cohorts are: the default names an
organizational contact, and `--include-maintainer-names` opts in, with a warning
that lists what is being published.

    pixi run test-croissant
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "examples" / "croissant_export.py"

failures: list[str] = []

SPONSOR = "Dr. Jane Q. Doe, Chief Medical Officer"
REVIEWERS = "Alan Smith (CMIO), Beatriz Jones (data science), Chidi Okafor (nursing)"
NAMES = ["Jane", "Doe", "Alan Smith", "Beatriz", "Jones", "Chidi", "Okafor"]


def export(**meta: str) -> dict:
    base = {
        "solution": "Sepsis early warning",
        "org": "Mercy General Hospital",
        "developer": "Acme AI Inc.",
        "sponsor": SPONSOR,
        "reviewers": REVIEWERS,
    }
    base.update(meta)
    return {
        "schema": "chai-review/2",
        "meta": base,
        "model_card": {
            "name": "Sepsis early warning",
            "summary": "Predicts sepsis six hours ahead.",
            "devData": "n=412 adults, 2019-01 to 2023-06, two sites",
        },
        "_state": {"updatedAt": "2026-01-01T00:00:00Z"},
    }


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def run(data: dict, *flags: str) -> tuple[dict, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "export.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(SCRIPT), str(path), *flags],
            capture_output=True,
            text=True,
        )
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-500:])
    return json.loads(done.stdout), done.stderr


def main() -> int:
    print("The default export names no individuals")
    doc, err = run(export())
    text = json.dumps(doc, ensure_ascii=False)
    leaked = [n for n in NAMES if n in text]
    check("no sponsor or reviewer name appears anywhere", not leaked, str(leaked))
    check(
        "the maintainer is an organizational contact",
        "AI Governance Committee" in json.dumps(doc.get("maintainer", {}))
        and "Mercy General Hospital" in json.dumps(doc.get("maintainer", {})),
        str(doc.get("maintainer")),
    )
    check(
        "it is still an organization, which the schema accepts",
        doc.get("maintainer", {}).get("@type") == "sc:Organization",
    )
    check(
        "the default run does not claim to have published personal data",
        "personal" not in err.lower(),
        err,
    )

    print("With no organization recorded there is nothing honest to name")
    doc, _ = run(export(org=""))
    check("the maintainer is omitted, not invented", "maintainer" not in doc)
    check(
        "and still no names",
        not [n for n in NAMES if n in json.dumps(doc, ensure_ascii=False)],
    )

    print("The opt-in publishes names, and says what it published")
    doc, err = run(export(), "--include-maintainer-names")
    check(
        "the named maintainer is emitted",
        REVIEWERS in json.dumps(doc.get("maintainer", {}), ensure_ascii=False),
        str(doc.get("maintainer")),
    )
    check(
        "a warning is printed that says personal data was published",
        "personal data" in err.lower(),
        err,
    )
    check(
        "and lists what it published",
        "Alan Smith" in err or "reviewers" in err.lower(),
        err,
    )
    doc, _ = run(export(reviewers=""), "--include-maintainer-names")
    check(
        "with no reviewers it falls back to the sponsor, as it used to",
        SPONSOR in json.dumps(doc.get("maintainer", {})),
        str(doc.get("maintainer")),
    )

    print("The output still validates, which the docs claim")
    import mlcroissant

    for label, flags in (
        ("default", []),
        ("with names", ["--include-maintainer-names"]),
    ):
        doc, _ = run(export(), *flags)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dataset.jsonld"
            path.write_text(json.dumps(doc), encoding="utf-8")
            issues = mlcroissant.Dataset(jsonld=str(path)).metadata.issues
        check(
            f"{label} output has no mlcroissant errors",
            not issues.errors,
            str(issues.errors),
        )

    print("Cohort detail keeps its own gate")
    doc, err = run(export())
    check(
        "cohort detail is still withheld by default",
        "412" not in json.dumps(doc),
    )
    doc, err = run(export(), "--include-cohort-detail")
    check("and still published on request", "412" in json.dumps(doc), err)
    check("with its own warning", "cohort detail included" in err, err)
    check(
        "which does not publish names",
        not [n for n in NAMES if n in json.dumps(doc, ensure_ascii=False)],
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("croissant exporter checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
