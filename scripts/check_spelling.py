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

The list is of roots, not of words: each root's inflections (plurals, -ed,
-ing, -er, the -isation family, un-, re- and the like) are generated from it,
because a list of exact forms missed "judgements" while it listed "judgement"
(#169). Words are read the way code writes them, so the parts of an identifier
(``colourPicker``, ``MAX_COLOURS``, ``data-colour-id``) are checked too, in any
case. tests/test_check_spelling.py pins all of this.

Quoting a source that spells a word the British way is legitimate. Two escapes:

* Put ``spelling-ok`` in a comment on the same line; that line is skipped.
* Add the exact phrase to ``.spelling-allow`` in the repo root, one per line;
  that phrase is skipped wherever it appears, and the rest of its line is not.

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

# British -> American, by root. A word list of exact forms catches the forms
# someone thought to type: "judgement" was listed and "judgements" was not, so
# the plural passed (#169). So the list holds roots, and every inflection is
# generated from a root by the endings its family takes, under the prefixes it
# takes. A generated form that is not a real word is harmless: it can only ever
# match a British spelling, because each one keeps the British part of its root.
#
# A family is (endings, prefixes, stems). Each ending is a (British, American)
# pair appended to the stem; each prefix is prepended to both.
Family = tuple[tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]]

FAMILIES: dict[str, Family] = {
    # colour -> color: the stem is everything before the "our".
    "-our": (
        (
            ("our", "or"),
            ("ours", "ors"),
            ("oured", "ored"),
            ("ouring", "oring"),
            ("ourings", "orings"),
            ("oural", "oral"),
            ("ourally", "orally"),
            ("ourable", "orable"),
            ("ourably", "orably"),
            ("ourite", "orite"),
            ("ourites", "orites"),
            ("ourer", "orer"),
            ("ourers", "orers"),
            ("ourful", "orful"),
            ("ourfully", "orfully"),
            ("ourless", "orless"),
            ("ourly", "orly"),
            ("ourhood", "orhood"),
            ("ourhoods", "orhoods"),
            ("ourism", "orism"),
            ("ourist", "orist"),
            ("ourists", "orists"),
            ("oury", "ory"),
            ("ourise", "orize"),
            ("ourised", "orized"),
            ("ourising", "orizing"),
        ),
        ("", "mis", "dis", "un", "water", "multi"),
        (
            "arm",
            "behavi",
            "cand",
            "clam",
            "col",
            "endeav",
            "fav",
            "flav",
            "harb",
            "hon",
            "hum",
            "lab",
            "neighb",
            "od",
            "parl",
            "rig",
            "rum",
            "savi",
            "sav",
            "splend",
            "tum",
            "val",
            "vap",
            "vig",
        ),
    ),
    # centre -> center: the stem is everything before the "re".
    "-re": (
        (
            ("re", "er"),
            ("res", "ers"),
            ("red", "ered"),
            ("ring", "ering"),
        ),
        ("", "kilo", "centi", "milli", "micro", "nano", "de", "re", "epi"),
        ("calib", "cent", "fib", "lit", "meag", "met", "somb", "spect", "theat"),
    ),
    # defence -> defense.
    "-ce": (
        (
            ("ce", "se"),
            ("ces", "ses"),
            ("ced", "sed"),
            ("cing", "sing"),
            ("celess", "seless"),
        ),
        ("", "sub", "self"),
        ("defen", "licen", "offen", "preten"),
    ),
    # organise -> organize, and every form built on it. Only stems whose -ise
    # form is British: "advertise", "exercise", "revise" and the like are
    # American too, so they are not here.
    "-ise": (
        (
            ("ise", "ize"),
            ("ised", "ized"),
            ("ises", "izes"),
            ("ising", "izing"),
            ("iser", "izer"),
            ("isers", "izers"),
            ("isable", "izable"),
            ("isation", "ization"),
            ("isations", "izations"),
            ("isational", "izational"),
        ),
        ("", "re", "un", "de", "dis", "mis", "pre", "non", "over", "under"),
        (
            "anonym",
            "apolog",
            "author",
            "capital",
            "categor",
            "central",
            "character",
            "civil",
            "colon",
            "conceptual",
            "container",
            "contextual",
            "critic",
            "custom",
            "digit",
            "emphas",
            "energ",
            "equal",
            "familiar",
            "fantas",
            "final",
            "formal",
            "general",
            "global",
            "harmon",
            "hospital",
            "hypothes",
            "ideal",
            "incentiv",
            "initial",
            "internal",
            "item",
            "jeopard",
            "legal",
            "legitim",
            "local",
            "marginal",
            "material",
            "maxim",
            "memor",
            "minim",
            "mobil",
            "modern",
            "monet",
            "national",
            "neutral",
            "normal",
            "operational",
            "optim",
            "organ",
            "parameter",
            "parametr",
            "patron",
            "penal",
            "personal",
            "polar",
            "popular",
            "priorit",
            "privat",
            "pseudonym",
            "public",
            "random",
            "rational",
            "real",
            "recogn",
            "sanit",
            "scrutin",
            "sensit",
            "serial",
            "social",
            "special",
            "stabil",
            "standard",
            "steril",
            "subsid",
            "summar",
            "symbol",
            "sympath",
            "synchron",
            "synthes",
            "theor",
            "token",
            "trivial",
            "util",
            "vapor",
            "victim",
            "virtual",
            "visual",
            "weapon",
        ),
    ),
    # analyse -> analyze. Not "-yses": "analyses" is the plural of "analysis".
    "-yse": (
        (
            ("yse", "yze"),
            ("ysed", "yzed"),
            ("ysing", "yzing"),
            ("yser", "yzer"),
            ("ysers", "yzers"),
        ),
        ("", "re", "over", "psycho"),
        ("anal", "catal", "dial", "electrol", "hydrol", "paral"),
    ),
    # travelled -> traveled. Only the forms that double the l in British and not
    # in American; "cancellation", "excelled", "controlled" are American too.
    "-ll": (
        (
            ("led", "ed"),
            ("ling", "ing"),
            ("ler", "er"),
            ("lers", "ers"),
            ("lings", "ings"),
            ("lor", "or"),
            ("lors", "ors"),
            ("lous", "ous"),
            ("lously", "ously"),
            ("lery", "ry"),
        ),
        ("", "re", "un", "mis"),
        (
            "cancel",
            "channel",
            "counsel",
            "dial",
            "duel",
            "enamel",
            "equal",
            "fuel",
            "funnel",
            "initial",
            "jewel",
            "label",
            "level",
            "libel",
            "marvel",
            "model",
            "panel",
            "pedal",
            "quarrel",
            "ravel",
            "revel",
            "rival",
            "shovel",
            "signal",
            "snorkel",
            "spiral",
            "stencil",
            "swivel",
            "total",
            "towel",
            "travel",
            "tunnel",
            "yodel",
        ),
    ),
}

# Words that belong to no family, each with its own inflections spelled out.
EXPLICIT: dict[str, str] = {
    "catalogue": "catalog",
    "catalogues": "catalogs",
    "catalogued": "cataloged",
    "cataloguing": "cataloging",
    "cataloguer": "cataloger",
    "cataloguers": "catalogers",
    "grey": "gray",
    "greys": "grays",
    "greyed": "grayed",
    "greying": "graying",
    "greyer": "grayer",
    "greyest": "grayest",
    "greyish": "grayish",
    "greyness": "grayness",
    "greyscale": "grayscale",
    "fulfil": "fulfill",
    "fulfils": "fulfills",
    "fulfilment": "fulfillment",
    "fulfilments": "fulfillments",
    "enrol": "enroll",
    "enrols": "enrolls",
    "enrolment": "enrollment",
    "enrolments": "enrollments",
    "instalment": "installment",
    "instalments": "installments",
    "instil": "instill",
    "instils": "instills",
    "skilful": "skillful",
    "skilfully": "skillfully",
    "unskilful": "unskillful",
    "wilful": "willful",
    "wilfully": "willfully",
    "acknowledgement": "acknowledgment",
    "acknowledgements": "acknowledgments",
    "judgement": "judgment",
    "judgements": "judgments",
    "judgemental": "judgmental",
    "misjudgement": "misjudgment",
    "misjudgements": "misjudgments",
    "abridgement": "abridgment",
    "towards": "toward",
    "amongst": "among",
    "whilst": "while",
    "programme": "program",
    "programmes": "programs",
    "storey": "story",
    "storeys": "stories",
    "tyre": "tire",
    "tyres": "tires",
    "plough": "plow",
    "ploughs": "plows",
    "ploughed": "plowed",
    "ploughing": "plowing",
    "aluminium": "aluminum",
    "artefact": "artifact",
    "artefacts": "artifacts",
    "draught": "draft",
    "draughts": "drafts",
    "draughty": "drafty",
    "kerb": "curb",
    "kerbs": "curbs",
    "manoeuvre": "maneuver",
    "manoeuvres": "maneuvers",
    "manoeuvred": "maneuvered",
    "manoeuvring": "maneuvering",
    "manoeuvrable": "maneuverable",
    "manoeuvrability": "maneuverability",
    "mould": "mold",
    "moulds": "molds",
    "moulded": "molded",
    "moulding": "molding",
    "mouldings": "moldings",
    "mouldy": "moldy",
    "moustache": "mustache",
    "moustaches": "mustaches",
    "practise": "practice",
    "practised": "practiced",
    "practises": "practices",
    "practising": "practicing",
    "sceptic": "skeptic",
    "sceptics": "skeptics",
    "sceptical": "skeptical",
    "sceptically": "skeptically",
    "scepticism": "skepticism",
    "speciality": "specialty",
    "specialities": "specialties",
    "cheque": "check",
    "cheques": "checks",
    "jewellery": "jewelry",
    "pyjamas": "pajamas",
    "sulphur": "sulfur",
    "aeroplane": "airplane",
    "aeroplanes": "airplanes",
    # Medicine, since this is aimed at US health systems.
    "anaemia": "anemia",
    "anaemic": "anemic",
    "anaesthesia": "anesthesia",
    "anaesthetic": "anesthetic",
    "anaesthetics": "anesthetics",
    "anaesthetist": "anesthetist",
    "anaesthetists": "anesthetists",
    "caesarean": "cesarean",
    "diarrhoea": "diarrhea",
    "encyclopaedia": "encyclopedia",
    "foetal": "fetal",
    "foetus": "fetus",
    "gynaecological": "gynecological",
    "gynaecologist": "gynecologist",
    "gynaecology": "gynecology",
    "haematologist": "hematologist",
    "haematology": "hematology",
    "haemoglobin": "hemoglobin",
    "haemorrhage": "hemorrhage",
    "ischaemia": "ischemia",
    "ischaemic": "ischemic",
    "leukaemia": "leukemia",
    "oedema": "edema",
    "oesophageal": "esophageal",
    "oesophagus": "esophagus",
    "oestrogen": "estrogen",
    "orthopaedic": "orthopedic",
    "orthopaedics": "orthopedics",
    "paediatric": "pediatric",
    "paediatrician": "pediatrician",
    "paediatricians": "pediatricians",
    "paediatrics": "pediatrics",
    "septicaemia": "septicemia",
}


def generate(families: dict[str, Family], explicit: dict[str, str]) -> dict[str, str]:
    """Every British form, lowercase, mapped to its American one."""
    out: dict[str, str] = {}
    for endings, prefixes, stems in families.values():
        for stem in stems:
            for prefix in prefixes:
                for ending_b, ending_a in endings:
                    out[prefix + stem + ending_b] = prefix + stem + ending_a
    out.update(explicit)
    return out


BRITISH: dict[str, str] = generate(FAMILIES, EXPLICIT)

MARKER = "spelling-ok"
# A word, as the checker sees one: a run of letters, split where an identifier
# changes case, so `colourPicker`, `MAX_COLOURS` and `data-colour-id` are each
# read as their words. Underscores, digits and hyphens separate words.
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
# The whole run of letters, without splitting identifiers (kept for the tests'
# mutation that shows the split matters).
WHOLE = re.compile(r"[A-Za-z]+")
# A URL or a path can legitimately contain any spelling; it is not prose.
URLISH = re.compile(r"(https?://\S+|\b[\w.-]+/[\w./-]+)")


def blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def american_for(word: str, american: str) -> str:
    """The American spelling, in the case the British one was written in."""
    if word.isupper() and len(word) > 1:
        return american.upper()
    if word[0].isupper():
        return american[0].upper() + american[1:]
    return american


def find(line: str, allow: list[str]) -> list[tuple[int, str, str]]:
    """(column, British word, American word) for each hit in one line.

    A line with the marker is exempt. An allowed phrase exempts only itself: it
    is blanked out before the scan, like a URL, so a British word elsewhere on
    the same line is still caught.
    """
    if MARKER in line:
        return []
    scannable = line
    for phrase in allow:
        scannable = scannable.replace(phrase, " " * len(phrase))
    scannable = URLISH.sub(blank, scannable)
    hits = []
    for match in WORD.finditer(scannable):
        word = match.group(0)
        american = BRITISH.get(word.lower())
        if american is not None:
            hits.append((match.start(), word, american_for(word, american)))
    return hits


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
        for column, word, american in find(line, allow):
            problems.append(
                f"{path}:{number}:{column + 1}: "
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
    """Rewrite British spellings in place. Returns how many were changed.

    Uses the same scan as check(), so it changes exactly what check() reports:
    never an exempt line, an allowed phrase or a URL.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0

    changed = 0
    out = []
    for line in text.splitlines(keepends=True):
        # Right to left, so an earlier column is not moved by a later change.
        for column, word, american in reversed(find(line, allow)):
            line = line[:column] + american + line[column + len(word) :]
            changed += 1
        out.append(line)

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
