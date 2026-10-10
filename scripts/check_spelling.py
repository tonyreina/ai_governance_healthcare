#!/usr/bin/env python3
"""Fail if a file uses British spelling where American is wanted.

This project is written in American English: it is built around CHAI, a US
non-profit, and aimed at US health systems, so British spellings read as
inconsistent with the subject matter. The slips are easy to miss in review
because words like "behavior" and "defense" look unremarkable.

Deliberately conservative. Only words whose American form is unambiguous are
listed, and anything that is a word in both -- "specialist", "analysis",
"practice" as a noun -- is left out, because a checker that cries wolf gets
switched off.

Quoting a source that spells a word the British way is legitimate. Two escapes:

* Put ``spelling-ok`` in a comment on the same line.
* Add the exact phrase to ``.spelling-allow`` in the repo root, one per line;
  a line matching that phrase is skipped.

Run via: pixi run check-spelling
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_i18n import Locale

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / ".spelling-allow"

SKIP_DIRS = {
    ".git",
    ".pixi",
    "site",
    ".cache",
    "node_modules",
    ".venv",
    "venv",
    "backups",
    # Output of a build of other frameworks (pixi run build-example), ignored by git.
    "build",
}
# This file IS the word list. Scanning it would flag every British key, and
# --fix would rewrite the keys to match their values, quietly turning the
# dictionary into identity mappings and disabling the check.
SELF = Path(__file__).resolve()

# Files that reproduce third-party text verbatim. CHAI's Testing & Evaluation
# content is CC BY 4.0 and quoted exactly; "correcting" its spelling would
# misquote the source, which is worse than an inconsistent spelling. These are
# generated from upstream, so a fix here would be overwritten anyway.
QUOTED_VERBATIM = {
    "data/chai_te_metrics.json",
    "docs/frameworks/chai-metrics.md",
    "app/js/10-frameworks/10-chai/05-te-metrics.js",
    # The built dashboard concatenates all of the above. Its own sources under
    # app/ ARE checked, so nothing of ours escapes review by being in here.
    "docs/app/index.html",
}
CHECK_SUFFIXES = {
    ".md",
    ".py",
    ".js",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".sql",
    ".rst",
    ".txt",
}
CHECK_NAMES = {"Caddyfile", "Dockerfile", "Makefile"}

# British -> American. Keys are matched case-insensitively on word boundaries.
BRITISH: dict[str, str] = {
    # -our
    "behaviour": "behavior",
    "behavioural": "behavioral",
    "behaviourally": "behaviorally",
    "colour": "color",
    "coloured": "colored",
    "colours": "colors",
    "favour": "favor",
    "favours": "favors",
    "favourite": "favorite",
    "honour": "honor",
    "honours": "honors",
    "labour": "labor",
    "neighbour": "neighbor",
    "rumour": "rumor",
    "endeavour": "endeavor",
    # -re
    "centre": "center",
    "centres": "centers",
    "centred": "centered",
    "metre": "meter",
    "metres": "meters",
    "theatre": "theater",
    "fibre": "fiber",
    # -ce nouns whose American form is -se
    "defence": "defense",
    "offence": "offense",
    "licence": "license",
    "pretence": "pretense",
    # -ise / -isation
    "organise": "organize",
    "organised": "organized",
    "organises": "organizes",
    "organising": "organizing",
    "organisation": "organization",
    "organisations": "organizations",
    "organisational": "organizational",
    "recognise": "recognize",
    "recognised": "recognized",
    "recognises": "recognizes",
    "normalise": "normalize",
    "normalised": "normalized",
    "normalises": "normalizes",
    "normalising": "normalizing",
    "normalisation": "normalization",
    "serialise": "serialize",
    "serialised": "serialized",
    "serialising": "serializing",
    "serialisation": "serialization",
    "summarise": "summarize",
    "summarised": "summarized",
    "summarises": "summarizes",
    "prioritise": "prioritize",
    "prioritised": "prioritized",
    "authorise": "authorize",
    "authorised": "authorized",
    "authorisation": "authorization",
    "minimise": "minimize",
    "minimised": "minimized",
    "minimising": "minimizing",
    "maximise": "maximize",
    "maximised": "maximized",
    "optimise": "optimize",
    "optimised": "optimized",
    "optimising": "optimizing",
    "standardise": "standardize",
    "standardised": "standardized",
    "standardisation": "standardization",
    "specialise": "specialize",
    "specialised": "specialized",
    "utilise": "utilize",
    "utilised": "utilized",
    "categorise": "categorize",
    "categorised": "categorized",
    "characterise": "characterize",
    "characterised": "characterized",
    "emphasise": "emphasize",
    "emphasised": "emphasized",
    "analyse": "analyze",
    "analysed": "analyzed",
    "analysing": "analyzing",
    "apologise": "apologize",
    "realise": "realize",
    "realised": "realized",
    "criticise": "criticize",
    "criticised": "criticized",
    "synthesise": "synthesize",
    "synthesised": "synthesized",
    "initialise": "initialize",
    "initialised": "initialized",
    "initialisation": "initialization",
    # doubled consonants
    "cancelled": "canceled",
    "cancelling": "canceling",
    "labelled": "labeled",
    "labelling": "labeling",
    "modelling": "modeling",
    "modelled": "modeled",
    "travelled": "traveled",
    "travelling": "traveling",
    "signalled": "signaled",
    "fuelled": "fueled",
    # miscellaneous
    "catalogue": "catalog",
    "grey": "gray",
    "greyed": "grayed",
    "fulfil": "fulfill",
    "fulfils": "fulfills",
    "fulfilment": "fulfillment",
    "enrol": "enroll",
    "enrolment": "enrollment",
    "instalment": "installment",
    "skilful": "skillful",
    "acknowledgement": "acknowledgment",
    "acknowledgements": "acknowledgments",
    "judgement": "judgment",
    "judgements": "judgments",
    "towards": "toward",
    "amongst": "among",
    "whilst": "while",
    "programme": "program",
    "programmes": "programs",
    "storey": "story",
    "tyre": "tire",
    "plough": "plow",
    "aluminium": "aluminum",
    "artefact": "artifact",
    "artefacts": "artifacts",
    "draught": "draft",
    "kerb": "curb",
    "manoeuvre": "maneuver",
    "mould": "mold",
    "moustache": "mustache",
    "practise": "practice",
    "sceptical": "skeptical",
    "scepticism": "skepticism",
    "speciality": "specialty",
}

PATTERN = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, BRITISH), key=len, reverse=True)) + r")\b",
    re.I,
)
# A URL or a path can legitimately contain any spelling; it is not prose.
URLISH = re.compile(r"(https?://\S+|\b[\w.-]+/[\w./-]+)")


def is_translation(rel: str) -> bool:
    """A message catalog in another language (#80). American English is the source
    language, app/i18n/en.json, which IS checked. "Organisation" is correct German and
    "centre" correct French, so judging a translation by English spelling is wrong."""
    parts = Path(rel).parts
    # app/i18n/<tag>.json, or the framework content's app/i18n/framework/<tag>.json.
    if parts[:3] == ("app", "i18n", "framework"):
        parts = ("app", "i18n", *parts[3:])
    return (
        len(parts) == 3
        and parts[:2] == ("app", "i18n")
        and parts[2].endswith(".json")
        and parts[2] != f"{Locale.EN}.json"
    )


def skip(path: Path) -> bool:
    """This file (it IS the word list), anything quoted verbatim, and translations."""
    resolved = path.resolve()
    if resolved == SELF:
        return True
    try:
        rel = str(resolved.relative_to(ROOT))
    except ValueError:
        return False
    return rel in QUOTED_VERBATIM or is_translation(rel)


def load_allowlist() -> list[str]:
    if not ALLOWLIST.exists():
        return []
    return [
        line.strip()
        for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def check(path: Path, allow: list[str]) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        if "spelling-ok" in line or any(phrase in line for phrase in allow):
            continue
        # Blank out URLs so a path like creativecommons.org/licenses cannot trip.
        scannable = URLISH.sub(lambda m: " " * len(m.group(0)), line)
        for match in PATTERN.finditer(scannable):
            word = match.group(0)
            american = BRITISH[word.lower()]
            if word[0].isupper():
                american = american.capitalize()
            problems.append(
                f"{path}:{number}:{match.start() + 1}: "
                f"British spelling {word!r} -- use {american!r}\n"
                f"    {line.strip()[:100]}"
            )
    return problems


def targets(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a) for a in argv]
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(d in SKIP_DIRS for d in p.relative_to(ROOT).parts)
        and (p.suffix in CHECK_SUFFIXES or p.name in CHECK_NAMES)
    ]


def fix(path: Path, allow: list[str]) -> int:
    """Rewrite British spellings in place. Returns how many were changed."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0

    changed = 0
    out = []
    for line in text.splitlines(keepends=True):
        if "spelling-ok" in line or any(phrase in line for phrase in allow):
            out.append(line)
            continue

        # Replace only outside URLs, so a path keeps whatever spelling it has.
        pieces, last = [], 0
        for m in URLISH.finditer(line):
            pieces.append((line[last : m.start()], True))
            pieces.append((m.group(0), False))
            last = m.end()
        pieces.append((line[last:], True))

        rebuilt = []
        for chunk, scan in pieces:
            if not scan:
                rebuilt.append(chunk)
                continue

            def swap(m: re.Match[str]) -> str:
                nonlocal changed
                changed += 1
                word = m.group(0)
                american = BRITISH[word.lower()]
                if word.isupper():
                    return american.upper()
                if word[0].isupper():
                    return american.capitalize()
                return american

            rebuilt.append(PATTERN.sub(swap, chunk))
        out.append("".join(rebuilt))

    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


def main(argv: list[str]) -> int:
    do_fix = "--fix" in argv
    argv = [a for a in argv if a != "--fix"]
    allow = load_allowlist()

    if do_fix:
        total = 0
        for path in targets(argv):
            if path.is_file() and not skip(path):
                n = fix(path, allow)
                if n:
                    try:
                        shown = path.resolve().relative_to(ROOT)
                    except ValueError:
                        shown = path
                    print(f"  {n:3d}  {shown}")
                    total += n
        print(f"\n{total} spelling(s) corrected")
        return 0

    problems = [
        msg
        for path in targets(argv)
        if path.is_file() and not skip(path)
        for msg in check(path, allow)
    ]

    for msg in problems:
        print(msg, file=sys.stderr)

    if problems:
        print(
            f"\n{len(problems)} British spelling(s) found. This project uses "
            "American English.\nIf a word is quoted from a source, add "
            "`spelling-ok` to the line or the phrase to .spelling-allow.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
