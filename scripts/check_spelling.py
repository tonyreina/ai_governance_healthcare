#!/usr/bin/env python3
"""Fail if a file uses British spelling where American is wanted.

This project is written in American English: it is built around CHAI, a US
non-profit, and aimed at US health systems, so British spellings read as
inconsistent with the subject matter. The slips are easy to miss in review
because words like "behavior" and "defense" look unremarkable.

Deliberately conservative. Only words whose American form is unambiguous are
listed, and anything that is a word in both -- "specialist", "analysis",
"practice" as a noun -- is left out, because a checker that cries wolf gets
switched off. Left out on purpose, because they are standard or common American
spellings too: "dialogue", "analogue", "monologue", "prologue" and the other
-ogue words except "catalogue" (CLAUDE.md names "catalog"); "burnt", "dreamt",
"spelt"; "glamour"; "fulfilled", "enrolled" (the American past tense doubles
the l); "analyses" (the plural of "analysis"); "aesthetic", "archaeology",
"amoeba"; and the name "Caesar" (only "caesarean" and "caesarian" are caught).

The list is of roots, not of words: each root's inflections (plurals, -ed,
-ing, -er, the -isation family, un-, re- and the like) are generated from it,
because a list of exact forms missed "judgements" while it listed "judgement"
(#169). The British medical spellings are roots too (MEDICAL: "haemorrhag-",
"oedem-", "oesophag-", the -aemia words and the rest), each with a closed set of
English endings and a few known prefixes. Every word is matched whole, never
inside a longer word, so "phytoestrogen" and "proestrus" are not touched, and
no Latin species epithet ("faecalis", "haemolyticus") is ever generated.

Only what is listed is caught. A British word whose root is not listed passes
(tests/fixtures/spelling_corpus/unlisted.txt keeps a few), and so does a
commit message, which the check does not read.

Not prose, so neither reported nor rewritten: a URL (with "://", or one of the
schemes written without it, such as mailto:, urn:, doi: and data:), an email
address, a domain, a file name with a known extension, a path, a digest
("sha384-..."), and a long run that looks like encoded data (see
looks_encoded()). Hex needs no rule: a word is a run of letters, and no British
word is spelled with the letters a-f alone.

Reported, but not rewritten by --fix: a word with a capital letter, unless it is
part of an identifier (``getColourValue``, ``MAX_COLOURS``). It may be a name: a
journal ("British Journal of Haematology"), a company, a place ("Sulphur,
Oklahoma"), a genus ("Oestrus"), and no rule over the text tells a name from
the first word of a sentence. --fix lists each one it leaves and exits 1, and a
person respells it or marks the line ``spelling-ok``. See fixable().

Words are read the way code writes them, so the parts of an identifier
(``colourPicker``, ``MAX_COLOURS``, ``data-colour-id``) are checked too, in any
case, and the ligatures "œ" and "æ" are read as "oe" and "ae".
tests/test_check_spelling.py pins all of this, against a corpus a verifier
built (tests/fixtures/spelling_corpus/).

Quoting a source that spells a word the British way is legitimate. Two escapes:

* Put ``spelling-ok``, in lowercase, in a comment on the same line; that line is
  skipped.
* Add ``glob: phrase`` to ``.spelling-allow`` in the repo root, one per line.
  The phrase, matched exactly and case-sensitively, is skipped in the files the
  glob matches (``*.py``, ``.github/workflows/*.yml``; matched from the right,
  like ``PurePath.match``), and the rest of its line is still checked. ``*``
  matches every file, and needs a comment saying why.

A file that is not valid UTF-8 is reported, not skipped: a check that cannot
read a file has not checked it.

Run with no arguments, it reads every text file under the repository, by the
rule pre-commit's ``types: [text]`` uses for a file it cannot name (see
is_text()), so a whole-repository run and the hook read the same kinds of file:
a shell script, a .caddy file, .env.example and .gitignore as well as code and
documentation. Symbolic links are not read (pre-commit does not pass them; the
target is read on its own), nor anything under SKIP_DIRS.

Run via: pixi run check-spelling
"""

from __future__ import annotations

import re
import sys
from itertools import pairwise
from pathlib import Path, PurePosixPath

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
    # Tool caches, ignored by git and never ours to spell.
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
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
# The test corpus of tests/test_check_spelling.py: British words, and names and
# code that keep a British spelling, each there on purpose. Only the files
# directly in it are skipped.
CORPUS = "tests/fixtures/spelling_corpus"
# The bytes a text file is made of, by the rule of identify, which pre-commit's
# `types: [text]` uses for a file it cannot classify by its name: the printable
# range and the usual control characters. A NUL, or any other control byte, in
# the first KiB makes a file binary. Bytes 0x80-0xFF are text, so a Latin-1 file
# is read, and reported as not UTF-8.
TEXT_BYTES = bytes(
    sorted({7, 8, 9, 10, 11, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7F})
)

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
            ("ouritism", "oritism"),
            ("ourer", "orer"),
            ("ourers", "orers"),
            ("ourful", "orful"),
            ("ourfully", "orfully"),
            ("ourfulness", "orfulness"),
            ("ourless", "orless"),
            ("ourly", "orly"),
            ("ourliness", "orliness"),
            ("ourhood", "orhood"),
            ("ourhoods", "orhoods"),
            ("ourism", "orism"),
            ("ourist", "orist"),
            ("ourists", "orists"),
            ("oury", "ory"),
            ("ourise", "orize"),
            ("ourised", "orized"),
            ("ourising", "orizing"),
            ("ourisation", "orization"),
        ),
        ("", "mis", "dis", "un", "water", "multi"),
        (
            "ard",
            "arm",
            "behavi",
            "cand",
            "clam",
            "col",
            "demean",
            "endeav",
            "fav",
            "ferv",
            "flav",
            "harb",
            "hon",
            "hum",
            "lab",
            "neighb",
            "od",
            "parl",
            "ranc",
            "rig",
            "rum",
            "savi",
            "sav",
            "splend",
            "succ",
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
        (
            "calib",
            "cent",
            "fib",
            "goit",
            "lit",
            "meag",
            "met",
            "och",
            "sab",
            "scept",
            "somb",
            "spect",
            "theat",
        ),
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
        # No "self": the scan splits "self-defence" at the hyphen, so "defence"
        # is caught, and "selfdefence" is not a word.
        ("", "sub"),
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
        (
            "",
            "re",
            "un",
            "de",
            "dis",
            "mis",
            "pre",
            "non",
            "over",
            "under",
            "im",
            "neo",
            "hyper",
        ),
        (
            # "anesthet": the American stem with the British ending. The
            # British stem ("anaesthetise") is in MEDICAL.
            "anesthet",
            "anonym",
            "apolog",
            "author",
            "capital",
            "categor",
            "catheter",
            "cauter",
            "central",
            "character",
            "civil",
            "colon",
            "commercial",
            "conceptual",
            "container",
            "contextual",
            "critic",
            "crystall",
            "custom",
            "digit",
            "emphas",
            "energ",
            "equal",
            "familiar",
            "fantas",
            "fertil",
            "final",
            "formal",
            "general",
            "global",
            "harmon",
            "heparin",
            "homogen",
            "hospital",
            "human",
            "hypnot",
            "hypothes",
            "ideal",
            "immun",
            "incentiv",
            "initial",
            "institutional",
            "internal",
            "ion",
            "item",
            "jeopard",
            "legal",
            "legitim",
            "local",
            "lyophil",
            "marginal",
            "material",
            "maxim",
            "medical",
            "memor",
            "metabol",
            "metastas",
            "mineral",
            "minim",
            "mobil",
            "modern",
            "moistur",
            "monet",
            "national",
            "nebul",
            "neutral",
            "normal",
            "operational",
            "optim",
            "organ",
            "oxid",
            "parameter",
            "parametr",
            "pasteur",
            "patron",
            "penal",
            "personal",
            "polar",
            "popular",
            "pressur",
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
            "stigmat",
            "subsid",
            "summar",
            "symbol",
            "sympath",
            "synchron",
            "synthes",
            "theor",
            "token",
            "traumat",
            "trivial",
            "util",
            "vapor",
            "vascular",
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
            ("list", "ist"),
            ("lists", "ists"),
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

# Words that belong to no family, each with its own inflections spelled out. No
# entry here may also be generated by a family or by MEDICAL: the tests check
# that, so every entry is load-bearing.
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
    "instal": "install",
    "instals": "installs",
    "instalment": "installment",
    "instalments": "installments",
    "instil": "instill",
    "instils": "instills",
    # Only the forms the American spelling does not share: "appalled",
    # "appalling", "enthralled", "distilled" are American too.
    "appal": "appall",
    "appals": "appalls",
    "enthral": "enthrall",
    "enthrals": "enthralls",
    "enthralment": "enthrallment",
    "distil": "distill",
    "distils": "distills",
    # British in the doubled l and the -ise together; "tranquillity" is American.
    "tranquillise": "tranquilize",
    "tranquillised": "tranquilized",
    "tranquillises": "tranquilizes",
    "tranquillising": "tranquilizing",
    "tranquilliser": "tranquilizer",
    "tranquillisers": "tranquilizers",
    "skilful": "skillful",
    "skilfully": "skillfully",
    "unskilful": "unskillful",
    "wilful": "willful",
    "wilfully": "willfully",
    "woollen": "woolen",
    "woollens": "woolens",
    "acknowledgement": "acknowledgment",
    "acknowledgements": "acknowledgments",
    "judgement": "judgment",
    "judgements": "judgments",
    "judgemental": "judgmental",
    "misjudgement": "misjudgment",
    "misjudgements": "misjudgments",
    "abridgement": "abridgment",
    "ageing": "aging",
    "learnt": "learned",
    "unlearnt": "unlearned",
    "towards": "toward",
    "amongst": "among",
    "whilst": "while",
    "enquiry": "inquiry",
    "enquiries": "inquiries",
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
    # Not in the -re family: "lustring" is a fabric, spelled so in American too.
    "lustre": "luster",
    "lustres": "lusters",
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
    "moult": "molt",
    "moults": "molts",
    "moulted": "molted",
    "moulting": "molting",
    "smoulder": "smolder",
    "smoulders": "smolders",
    "smouldered": "smoldered",
    "smouldering": "smoldering",
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
    "pyjamas": "pajamas",
    "aeroplane": "airplane",
    "aeroplanes": "airplanes",
    "aeon": "eon",
    "aeons": "eons",
    "mediaeval": "medieval",
    "cosy": "cozy",
    "cosier": "cozier",
    "cosiest": "coziest",
    "cosily": "cozily",
    "cosiness": "coziness",
    "liquorice": "licorice",
    "yoghurt": "yogurt",
    "yoghurts": "yogurts",
    # Compounds of -re words, which that family's endings do not make.
    "centrepiece": "centerpiece",
    "centrepieces": "centerpieces",
    "centreline": "centerline",
    "centrelines": "centerlines",
    "fibreoptic": "fiberoptic",
    "fibreoptics": "fiberoptics",
    "fibreglass": "fiberglass",
    # "tumour" is in the -our family; these are built on it with no ending of
    # that family's.
    "tumourigenic": "tumorigenic",
    "tumourigenicity": "tumorigenicity",
    "tumourigenesis": "tumorigenesis",
}

# British medical spellings, as whole words. Each entry is (British stem,
# American stem, endings, prefixes): every prefix + stem + ending is generated,
# and matched only as an entire word, never inside a longer one. An ending is a
# string both spellings share, or a (British, American) pair where the ending is
# British too ("anaesthetise"). The endings are a closed set of English ones:
# none is a Latin ending such as -alis, -ium, -icus, -ica or -ae, so a species
# epithet ("faecalis", "faecium", "haemolyticus", "gonorrhoeae") is never
# generated and never matched, wherever it is written. A genus that is also an
# English word ("Oestrus") is capitalized, and a capitalized word is reported
# but never rewritten by --fix (see fixable()).
#
# This is a list, so a British word whose stem is not here passes ("haem" alone,
# "leucoplakia", "foetid" are not here). Add the stem, its endings and its
# prefixes when one turns up; the tests demand every stem has a row.
Ending = str | tuple[str, str]
Medical = tuple[str, str, tuple[Ending, ...], tuple[str, ...]]
AEMIA: tuple[Ending, ...] = ("ia", "ias", "ic")
PNOEA: tuple[Ending, ...] = ("a", "as", "ic")
MEDICAL: tuple[Medical, ...] = (
    (
        "haemorrhag",
        "hemorrhag",
        ("e", "es", "ed", "ing", "ic"),
        ("", "non", "post", "pre", "peri"),
    ),
    ("haemorrhoid", "hemorrhoid", ("", "s", "al", "ectomy", "ectomies"), ("",)),
    (
        "haemat",
        "hemat",
        (
            "oma",
            "omas",
            "omata",
            "ology",
            "ological",
            "ologic",
            "ologist",
            "ologists",
            "uria",
            "ocrit",
            "ocrits",
            "emesis",
            "ochezia",
            "opoiesis",
            "opoietic",
        ),
        ("", "micro", "macro"),
    ),
    (
        "haemoly",
        "hemoly",
        ("sis", "tic", "sin", "sins", ("se", "ze"), ("sed", "zed"), ("sing", "zing")),
        ("", "non"),
    ),
    (
        "haemoglobin",
        "hemoglobin",
        ("", "s", "uria", "opathy", "opathies", ("aemia", "emia")),
        ("",),
    ),
    ("haemodialys", "hemodialys", ("is", "es", ("er", "zer"), ("ers", "zers")), ("",)),
    ("haemodynamic", "hemodynamic", ("", "s", "ally"), ("",)),
    ("haemophil", "hemophil", ("ia", "iac", "iacs", "ic"), ("",)),
    ("haemosta", "hemosta", ("sis", "tic", "tics", "t", "ts"), ("",)),
    ("haemopty", "hemopty", ("sis",), ("",)),
    ("haemothorax", "hemothorax", ("", "es"), ("",)),
    ("haemangiom", "hemangiom", ("a", "as", "ata"), ("",)),
    ("haemochromatos", "hemochromatos", ("is",), ("",)),
    ("haemarthros", "hemarthros", ("is", "es"), ("",)),
    ("haemal", "hemal", ("",), ("",)),
    (
        "oedem",
        "edem",
        ("a", "as", "ata", "atous"),
        ("", "non", "myx", "lymph", "angio", "papill"),
    ),
    (
        "oesophag",
        "esophag",
        (
            "us",
            "i",
            "eal",
            "itis",
            "ectomy",
            "ectomies",
            "oscopy",
            "oscopies",
            "ostomy",
        ),
        ("", "gastro", "trans"),
    ),
    (
        "oestr",
        "estr",
        (
            "ogen",
            "ogens",
            "ogenic",
            "ogenicity",
            "adiol",
            "iol",
            "one",
            "us",
            "ous",
        ),
        ("", "anti", "an", "di", "pro", "met"),
    ),
    ("foet", "fet", ("us", "uses", "al", "icide", "oscopy"), ("",)),
    ("faec", "fec", ("es", "al", "aloma", "alith", "aliths"), ("",)),
    ("gynaecolog", "gynecolog", ("y", "ic", "ical", "ist", "ists"), ("", "uro")),
    ("gynaecomasti", "gynecomasti", ("a",), ("",)),
    ("anaem", "anem", AEMIA, ("", "non")),
    ("leukaem", "leukem", AEMIA, ("", "pre")),
    ("septicaem", "septicem", AEMIA, ("",)),
    ("ischaem", "ischem", AEMIA, ("", "non")),
    ("glycaem", "glycem", AEMIA, ("", "hypo", "hyper", "normo", "eu")),
    ("bacteraem", "bacterem", AEMIA, ("",)),
    ("viraem", "virem", AEMIA, ("",)),
    ("toxaem", "toxem", AEMIA, ("",)),
    ("uraem", "urem", AEMIA, ("",)),
    ("pyaem", "pyem", AEMIA, ("",)),
    ("hyperaem", "hyperem", AEMIA, ("",)),
    ("thalassaem", "thalassem", AEMIA, ("",)),
    ("oxaem", "oxem", AEMIA, ("hyp", "hyper")),
    ("kalaem", "kalem", AEMIA, ("hypo", "hyper", "normo")),
    ("natraem", "natrem", AEMIA, ("hypo", "hyper", "normo", "eu")),
    ("calcaem", "calcem", AEMIA, ("hypo", "hyper", "normo")),
    ("volaem", "volem", AEMIA, ("hypo", "hyper", "normo", "eu")),
    ("lipidaem", "lipidem", AEMIA, ("hyper", "dys")),
    ("cholesterolaem", "cholesterolem", AEMIA, ("hyper",)),
    ("uricaem", "uricem", AEMIA, ("hypo", "hyper")),
    ("insulinaem", "insulinem", AEMIA, ("hypo", "hyper")),
    ("phosphataem", "phosphatem", AEMIA, ("hypo", "hyper")),
    ("magnesaem", "magnesem", AEMIA, ("hypo", "hyper")),
    ("proteinaem", "proteinem", AEMIA, ("hypo", "hyper", "dys", "para")),
    ("cythaem", "cythem", AEMIA, ("poly",)),
    (
        "anaesthe",
        "anesthe",
        (
            "sia",
            "sias",
            "tic",
            "tics",
            "tist",
            "tists",
            "siology",
            "siologist",
            "siologists",
            "tize",
            "tized",
            "tizing",
            ("tise", "tize"),
            ("tised", "tized"),
            ("tises", "tizes"),
            ("tising", "tizing"),
            ("tisation", "tization"),
        ),
        ("", "non"),
    ),
    ("paraesthesi", "paresthesi", ("a", "as"), ("",)),
    ("dysaesthesi", "dysesthesi", ("a", "as"), ("",)),
    ("synaesthesi", "synesthesi", ("a", "as"), ("",)),
    ("hyperaesthesi", "hyperesthesi", ("a",), ("",)),
    ("hypoaesthesi", "hypoesthesi", ("a",), ("",)),
    ("kinaesthe", "kinesthe", ("sia", "tic"), ("",)),
    ("diarrhoe", "diarrhe", ("a", "as", "al", "ic"), ("",)),
    ("gonorrhoe", "gonorrhe", ("a", "al"), ("",)),
    ("menorrhoe", "menorrhe", ("a",), ("a", "dys")),
    ("rhinorrhoe", "rhinorrhe", ("a",), ("",)),
    ("steatorrhoe", "steatorrhe", ("a",), ("",)),
    ("seborrhoe", "seborrhe", ("a", "ic"), ("",)),
    ("galactorrhoe", "galactorrhe", ("a",), ("",)),
    ("pnoe", "pne", PNOEA, ("a", "dys", "hypo", "hyper", "tachy", "brady", "ortho")),
    ("paediatric", "pediatric", ("", "s", "ian", "ians", "ally"), ("", "non")),
    ("orthopaed", "orthoped", ("ic", "ics", "ist", "ists", "ically"), ("",)),
    ("paedophil", "pedophil", ("e", "es", "ia", "iac", "iacs", "ic"), ("",)),
    ("encyclopaedi", "encyclopedi", ("a", "as", "c", "st", "sts"), ("",)),
    ("coeliac", "celiac", ("", "s"), ("",)),
    ("caesar", "cesar", ("ean", "eans", "ian", "ians"), ("",)),
    ("aetiolog", "etiolog", ("y", "ies", "ic", "ical", "ically"), ("",)),
    ("homoeopath", "homeopath", ("y", "ic", "s", "ist", "ists", "ically"), ("",)),
    ("homoeosta", "homeosta", ("sis", "tic"), ("",)),
    ("leucocyt", "leukocyt", ("e", "es", "osis", "ic"), ("",)),
    ("leucopeni", "leukopeni", ("a", "c"), ("",)),
    (
        "sulph",
        "sulf",
        (
            "ur",
            "urs",
            "uric",
            "urous",
            "ate",
            "ates",
            "ated",
            "ide",
            "ides",
            "ite",
            "ites",
            "onamide",
            "onamides",
            "onate",
            "onates",
            "onic",
            "onylurea",
            "onylureas",
            "asalazine",
            "amethoxazole",
            "adiazine",
        ),
        ("", "bi", "di"),
    ),
)


def ending_pair(ending: Ending) -> tuple[str, str]:
    return (ending, ending) if isinstance(ending, str) else ending


def generate(
    families: dict[str, Family],
    explicit: dict[str, str],
    medical: tuple[Medical, ...] = (),
) -> dict[str, str]:
    """Every British form, lowercase, mapped to its American one."""
    out: dict[str, str] = {}
    for endings, prefixes, stems in families.values():
        for stem in stems:
            for prefix in prefixes:
                for ending_b, ending_a in endings:
                    out[prefix + stem + ending_b] = prefix + stem + ending_a
    for stem_b, stem_a, endings, prefixes in medical:
        for prefix in prefixes:
            for ending in endings:
                ending_b, ending_a = ending_pair(ending)
                out[prefix + stem_b + ending_b] = prefix + stem_a + ending_a
    out.update(explicit)
    return out


BRITISH: dict[str, str] = generate(FAMILIES, EXPLICIT, MEDICAL)

# The ligatures, as their two letters. Each is one character, so a word keeps
# its length and its column when it is read this way.
LIGATURES = str.maketrans({"œ": "oe", "æ": "ae"})


def american(word: str) -> str | None:
    """The American spelling of `word`, lowercase, or None if it is not British.
    Only an entire word is looked up: nothing is matched inside a longer one."""
    return BRITISH.get(word.lower().translate(LIGATURES))


MARKER = "spelling-ok"
# A word, as the checker sees one: a run of letters, split where an identifier
# changes case, so `colourPicker`, `MAX_COLOURS` and `data-colour-id` are each
# read as their words. Underscores, digits and hyphens separate words.
WORD = re.compile(r"[A-ZŒÆ]+(?![a-zœæ])|[A-ZŒÆ]?[a-zœæ]+")
# The whole run of letters, without splitting identifiers (kept for the tests'
# mutation that shows the split matters).
WHOLE = re.compile(r"[A-Za-zŒÆœæ]+")

# Text that is not prose, and is blanked before the scan, so it is neither
# reported nor rewritten: whatever is spelled there is someone else's, or is
# not a word at all. Each is replaced by spaces of its length, so columns hold.
#
# A URL: a scheme and "://", or one of the schemes written without slashes.
# A colon alone is not one ("note:colour" is prose).
URL = re.compile(
    r"\b[A-Za-z][\w+.-]*://\S+"
    r"|\b(?:mailto|urn|doi|data|tel|sms|news|blob|javascript|about|geo|magnet"
    r"|cid|mid|pmid|arxiv|isbn):\S+",
    re.IGNORECASE,
)
# An email address, and the user@host:path form of git.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?::\S*)?")
# A domain, by its top-level domain, with any path after it.
DOMAIN = re.compile(
    r"\b(?:[A-Za-z0-9-]+\.)+"
    r"(?:com|org|net|edu|gov|mil|int|io|ai|app|dev|co|uk|us|ca|au|nz|ie|de|fr"
    r"|eu|nl|info|biz|me|ly|gl)\b(?:[/:?#][^\s)\]>\"'`]*)?",
)
# A file name with a known extension ("colour.md", "behaviour.json").
FILE_NAME = re.compile(
    r"\b[\w.-]*\w\.(?:md|txt|py|pyi|js|mjs|cjs|ts|tsx|jsx|json|ya?ml|toml"
    r"|html?|css|scss|csv|tsv|png|jpe?g|gif|svg|webp|ico|pdf|sh|bash|git|sql"
    r"|xml|ini|cfg|conf|lock|log|rst|docx?|xlsx?|pptx?|gz|zip|tar|woff2?|ttf"
    r"|otf|env|caddy)\b",
    re.IGNORECASE,
)
# A run with a slash is a path only if it starts with "./", "../" or "/", or a
# segment has a file extension: "colour/flavour" is prose. A run is matched from
# its first character (a match starts at the leftmost place it can, and every
# character a run is made of can start one), so no lookbehind is needed.
SLASHED = re.compile(r"[\w.~-]*/[\w./~-]*")
EXTENSION = re.compile(r"\w\.[A-Za-z0-9]+$")
# A digest named by its algorithm (an SRI hash, a Docker digest).
DIGEST = re.compile(r"\b(?:sha1|sha224|sha256|sha384|sha512|md5)[-:]\S+", re.I)
# Hex needs no pattern: a word is a run of letters, so "#faec00" or a hash is
# read as its runs of the letters a-f, and no British word is spelled with
# those letters alone (the tests check every one).
# A run of the base64 alphabet (and base64url, and the dots of a JWT).
ENCODED = re.compile(r"[A-Za-z0-9+/=_.-]{16,}")


def blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def blank_path(match: re.Match[str]) -> str:
    run = match.group(0)
    path = run.rstrip(".")
    if path.startswith(("./", "../", "/")) or any(
        EXTENSION.search(segment) for segment in path.split("/")
    ):
        return " " * len(run)
    return run


def looks_encoded(run: str) -> bool:
    """Whether a long run of the base64 alphabet is data, not words: it ends in
    "=" padding, or it holds a digit and its letters and digits fall into runs
    of one kind (upper case, lower case, digits) two characters long or less on
    average. An identifier's words make longer runs: `renderColourPanelV2Layout`
    averages nearly three. One with no digit is never data, however its case
    changes (`TestWhoSignedAndWhen`)."""
    if run.endswith("="):
        return True
    alnum = [c for c in run if c.isalnum()]
    if not any(c.isdigit() for c in alnum):
        return False

    def kind(c: str) -> int:
        return 0 if c.isdigit() else 1 if c.isupper() else 2

    runs = 1 + sum(kind(a) != kind(b) for a, b in pairwise(alnum))
    return runs * 2 >= len(alnum)


def blank_encoded(match: re.Match[str]) -> str:
    run = match.group(0)
    return " " * len(run) if looks_encoded(run) else run


def blank_unprose(line: str) -> str:
    """Blank what is not prose: URLs, email addresses, domains, file names,
    paths, digests and encoded data."""
    for pattern in (URL, EMAIL, DIGEST, DOMAIN):
        line = pattern.sub(blank, line)
    # A path before a file name, so the file name does not cut the path short.
    line = SLASHED.sub(blank_path, line)
    line = FILE_NAME.sub(blank, line)
    return ENCODED.sub(blank_encoded, line)


def american_for(word: str, american: str) -> str:
    """The American spelling, in the case the British one was written in."""
    if word.isupper() and len(word) > 1:
        return american.upper()
    if word[0].isupper():
        return american[0].upper() + american[1:]
    return american


def fixable(line: str, start: int, word: str) -> bool:
    """Whether --fix may rewrite `word`, found at `start` in `line`.

    A lowercase word, yes. A word with a capital letter only when it is part of
    an identifier: right after a letter, digit or underscore (`getColourValue`,
    `MAX_COLOURS`), or right before an underscore or digit (`COLOUR_MAX`). Any
    other capitalized word may be a name ("British Journal of Haematology",
    "Haemonetics", "Oestrus ovis", "Sulphur, Oklahoma"), and no rule over the
    text can tell a name from a word at the start of a sentence, so it is
    reported and left for a human.
    """
    if word.islower():
        return True
    before = line[start - 1] if start > 0 else ""
    end = start + len(word)
    after = line[end] if end < len(line) else ""
    return before.isalnum() or before == "_" or after.isdigit() or after == "_"


# A hit: (column, British word, American word, whether --fix may rewrite it).
Hit = tuple[int, str, str, bool]


def find(line: str, allow: list[str]) -> list[Hit]:
    """Each hit in one line.

    `allow` is the phrases allowed in this file. A line with the marker is
    exempt. An allowed phrase exempts only itself, matched exactly: it is blanked
    out before the scan, like a URL, so a British word elsewhere on the same line
    is still caught.
    """
    if MARKER in line:
        return []
    scannable = line
    for phrase in allow:
        scannable = scannable.replace(phrase, " " * len(phrase))
    scannable = blank_unprose(scannable)
    hits = []
    for match in WORD.finditer(scannable):
        word = match.group(0)
        respelled = american(word)
        if respelled is not None:
            start = match.start()
            hits.append(
                (
                    start,
                    word,
                    american_for(word, respelled),
                    fixable(line, start, word),
                )
            )
    return hits


def relative(path: Path) -> str:
    """The path from the repository root, or the whole path if it is outside."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


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
    """This file (it IS the word list), the allowlist (it is the list of British
    phrases allowed, so each of its entries is one), anything quoted verbatim,
    the spelling corpus, and translations. pre-commit names files itself, so
    this applies to them."""
    resolved = path.resolve()
    if resolved == SELF:
        return True
    if resolved == ALLOWLIST.resolve():
        return True
    try:
        rel = str(resolved.relative_to(ROOT))
    except ValueError:
        return False
    return (
        rel in QUOTED_VERBATIM
        or PurePosixPath(rel).parent.as_posix() == CORPUS
        or is_translation(rel)
    )


# An allowlist entry: (glob, phrase). The phrase is allowed only in the files
# the glob matches.
Allow = tuple[str, str]


def parse_allowlist(text: str) -> list[Allow]:
    """`glob: phrase` per line. A line with no glob is an error, not a phrase
    allowed everywhere: an exemption names where it applies."""
    entries = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        glob, sep, phrase = line.partition(": ")
        if not sep or not glob or not phrase.strip():
            raise ValueError(
                f"{ALLOWLIST.name}:{number}: expected 'glob: phrase', got {line!r}"
            )
        entries.append((glob, phrase.strip()))
    return entries


def load_allowlist() -> list[Allow]:
    if not ALLOWLIST.exists():
        return []
    return parse_allowlist(ALLOWLIST.read_text(encoding="utf-8"))


def allowed_in(path: Path, allow: list[Allow]) -> list[str]:
    """The phrases allowed in `path`."""
    where = PurePosixPath(relative(path))
    return [phrase for glob, phrase in allow if where.match(glob)]


def read(path: Path) -> str:
    """The file's text. Raises UnicodeDecodeError or OSError if it cannot be read."""
    return path.read_text(encoding="utf-8")


# Said of a hit --fix will not rewrite.
LEFT_FOR_A_HUMAN = " (capitalized, so it may be a name: --fix leaves it to you)"


def check(path: Path, allow: list[Allow]) -> list[str]:
    try:
        text = read(path)
    except UnicodeDecodeError as error:
        return [f"{path}: not valid UTF-8 (byte {error.start}), so not checked"]
    except OSError as error:
        return [f"{path}: could not be read ({error.strerror}), so not checked"]

    phrases = allowed_in(path, allow)
    problems = []
    for number, line in enumerate(text.splitlines(), 1):
        for column, word, respelled, can_fix in find(line, phrases):
            problems.append(
                f"{path}:{number}:{column + 1}: "
                f"British spelling {word!r} -- use {respelled!r}"
                f"{'' if can_fix else LEFT_FOR_A_HUMAN}\n"
                f"    {line.strip()[:100]}"
            )
    return problems


def is_text(path: Path) -> bool:
    """Whether pre-commit would call `path` a text file. One that cannot be
    opened counts as text, so check() reports it rather than it being dropped."""
    try:
        with path.open("rb") as handle:
            head = handle.read(1024)
    except OSError:
        return True
    return not head.translate(None, TEXT_BYTES)


def targets(argv: list[str]) -> list[Path]:
    if argv:
        return [Path(a) for a in argv]
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not p.is_symlink()
        and not any(d in SKIP_DIRS for d in p.relative_to(ROOT).parts)
        and is_text(p)
    ]


def fix(path: Path, allow: list[Allow]) -> tuple[int, list[str]]:
    """Rewrite British spellings in place. Returns how many were changed, and
    the hits left for a human (each as "line:column: word").

    Uses the same scan as check(), so it never touches what check() does not
    report: an exempt line, an allowed phrase, a URL, an email address, a
    domain, a file name, a path, a digest or encoded data. Of what it
    reports, it rewrites only what fixable() allows: a capitalized word that is
    not part of an identifier may be a name, and is left as written. A file
    that cannot be read raises, so the caller reports it.
    """
    text = read(path)
    phrases = allowed_in(path, allow)

    changed = 0
    left = []
    out = []
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        # Right to left, so an earlier column is not moved by a later change.
        for column, word, respelled, can_fix in reversed(find(line, phrases)):
            if not can_fix:
                left.append(f"{number}:{column + 1}: {word!r} -- {respelled!r}")
                continue
            line = line[:column] + respelled + line[column + len(word) :]
            changed += 1
        out.append(line)

    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed, sorted(left, key=lambda h: tuple(map(int, h.split(":")[:2])))


def main(argv: list[str]) -> int:
    do_fix = "--fix" in argv
    argv = [a for a in argv if a != "--fix"]
    try:
        allow = load_allowlist()
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    if do_fix:
        total = 0
        unread = 0
        unfixed = 0
        for path in targets(argv):
            if path.is_file() and not skip(path):
                try:
                    n, left = fix(path, allow)
                except (UnicodeDecodeError, OSError) as error:
                    print(f"  could not read {path}: {error}", file=sys.stderr)
                    unread += 1
                    continue
                try:
                    shown = path.resolve().relative_to(ROOT)
                except ValueError:
                    shown = path
                if n:
                    print(f"  {n:3d}  {shown}")
                    total += n
                for hit in left:
                    print(f"  {shown}:{hit}{LEFT_FOR_A_HUMAN}", file=sys.stderr)
                unfixed += len(left)
        print(f"\n{total} spelling(s) corrected")
        if unfixed:
            print(
                f"{unfixed} left for you: respell each, or mark it `spelling-ok` "
                "if it is a name.",
                file=sys.stderr,
            )
        return 1 if unread or unfixed else 0

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
            f"\n{len(problems)} problem(s) found. This project uses American "
            "English.\nIf a word is quoted from a source, add `spelling-ok` to "
            "the line, or 'glob: phrase' to .spelling-allow.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
