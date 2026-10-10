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
(#169). The British medical digraphs ("haem", "oesoph", "paed", "-aemia" and the
like) are matched as segments in a word, so every inflection of "haemorrhage"
or "oedema" is caught without being listed.

A segment can also be part of a name that keeps its spelling in American text,
and --fix must not respell a name. Those are recognized by their shape, with a
short list only where no shape tells them apart:

* a species epithet, the lowercase Latin word after a genus ("Enterococcus
  faecalis", "S. haemolyticus"): a capitalized Latin-shaped word or a capital
  and a period, then a lowercase word with a Latin ending (and the genus too
  when it ends in -us or -um: "Oestrus ovis");
* a taxon by its rank's suffix ("Oestridae", "Haemosporida",
  "Faecalibacterium", "Haematococcus");
* a segment narrowed where a name or an American word shares its letters:
  "-aemi-" never starts a word ("Aemilia"), the "caesar" of "caesarean" must be
  followed by "-ean" or "-ian" ("Caesarea"), "paed" is not the "paedomorph-"
  or "paedogen-" of American biology, and only "leucocyt-" and "leucopeni-"
  are caught ("leucovorin" is American);
* GENERA, the genera with a British segment that stand alone in a sentence
  ("Haemophilus", "Haematobia"), and PROPER_NOUNS, the places and titles
  ("Sulphur Springs", "Encyclopaedia Britannica").

A capitalized word is otherwise checked like any other: a heading ("Paediatric
Care") and an identifier (``PaediatricWard``) are ours to spell, so
"Haemorrhage was noted." is caught. The other way, leaving every capitalized
segment word alone unless it is a known common noun, was rejected: it needs a
list of every common medical word, the list this checker exists not to keep.
Its cost is a name that has no shape and is not listed, like the city of
Sulphur, Louisiana written without its state; that takes ``spelling-ok``.

Words are read the way code writes them, so the parts of an identifier
(``colourPicker``, ``MAX_COLOURS``, ``data-colour-id``) are checked too, in any
case, and the ligatures "œ" and "æ" are read as "oe" and "ae".
tests/test_check_spelling.py pins all of this.

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
            # "anesthet": the American segment, so "anaesthetise" is caught by
            # its segment and its ending together (see american()).
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
# entry here may also be generated by a family or matched by a segment: the
# tests check that, so every entry is load-bearing.
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

# British spellings that are a segment of many words, mostly medical since this
# is aimed at US health systems. Each is a regular expression matched in a word
# and replaced by its American segment, so "haemorrhages", "haemorrhagic",
# "haematoma" and "haemodialysis" are all caught by "haem" without a list of
# their forms. A segment is meant to be one no American word contains. That was
# checked only against the words we thought of, which are the American
# look-alikes pinned in tests/test_check_spelling.py ("aerial", "academia",
# "coelacanth", "Caesar", "paean", "onomatopoeia", "leucovorin" and the rest);
# it is not a search of a dictionary. Where one of them shares a segment's
# letters, the segment is narrowed: "oea" alone is not a segment (only "rrhoea"
# and "pnoea" are), nor is "coel" ("coelacanth", "coelom"), nor "leuco"
# ("leucovorin"); "caesar" only before "-ean" or "-ian" (the names "Caesar" and
# "Caesarea"); "-aemi-" never at the start of a word ("Aemilia"); "paed" not in
# "paedomorphosis" or "paedogenesis", which American biology spells so.
SEGMENTS: tuple[tuple[str, str], ...] = (
    ("haem", "hem"),  # haemorrhage, haematoma, haemodynamic, haemophilia
    ("(?<=[a-z])aemi", "emi"),  # anaemia, leukaemia, septicaemic, ischaemia
    ("anaes", "anes"),  # anaesthesia, anaesthetise
    ("paed(?!omorph|ogene)", "ped"),  # paediatric, orthopaedist, encyclopaedia
    ("oesoph", "esoph"),  # oesophagus, oesophagitis
    ("oestr", "estr"),  # oestrogen, oestradiol
    ("oedem", "edem"),  # oedema, oedematous
    ("foet", "fet"),  # foetus, foetal
    ("faec", "fec"),  # faeces, faecal
    ("gynaec", "gynec"),  # gynaecology, gynaecologic
    ("coeliac", "celiac"),
    ("caesar(?=[ei]an)", "cesar"),  # caesarean, caesarian
    ("aetiolog", "etiolog"),  # aetiology
    ("rrhoea", "rrhea"),  # diarrhoea, gonorrhoea
    ("pnoea", "pnea"),  # apnoea, dyspnoea
    ("sulph", "sulf"),  # sulphur, sulphate, sulphide
    ("homoeo", "homeo"),  # homoeopathy, homoeostasis
    ("leucocyt", "leukocyt"),  # leucocyte, leucocytosis
    ("leucopeni", "leukopeni"),  # leucopenia
)
SEGMENT_PATTERNS = tuple((re.compile(b), a) for b, a in SEGMENTS)

# Names that keep a British segment in American text, so must not be respelled.
#
# Genera that stand alone in a sentence, where no shape tells "Haematobia" (a
# fly) from "haematuria" (British for hematuria). Matched as the whole word.
# "Oestrus" is not here: alone it is far more often the British "estrus", and
# as a genus it comes with its species ("Oestrus ovis"), which BINOMIAL reads.
GENERA: frozenset[str] = frozenset(
    {
        "haemophilus",
        "haemaphysalis",
        "haemonchus",
        "haemagogus",
        "haemadipsa",
        "haematopinus",
        "haematobia",
        "haemoproteus",
        "paederus",
    }
)
# A taxon named by its rank's suffix: a family (-idae), subfamily (-inae), order
# (-ida), plant family (-aceae), or a bacterial or algal genus (-bacterium,
# -bacter, -coccus, -monas). No common word with a British segment ends so.
TAXON_SUFFIXES: tuple[str, ...] = (
    "idae",
    "inae",
    "ida",
    "aceae",
    "bacterium",
    "bacter",
    "coccus",
    "monas",
)
# A species epithet: the lowercase word after a genus, which is a capitalized
# word with a Latin ending, or the genus's initial and a period ("Enterococcus
# faecalis", "E. faecium", "Mannheimia haemolytica"). The epithet must look Latin
# too, and not like an English noun of the -sis, -itis, -ia, -ma or -oea kinds
# ("Trauma haematoma" is prose, and is checked). The genus is left alone too
# when it ends in -us or -um and its epithet ends in -ae, -ii, -i or -is
# ("Oestrus ovis"), endings an English word after "Foetus" or "Oesophagus"
# almost never has; a genus in -a stays checked ("Leukaemia virus" is prose).
BINOMIAL = re.compile(
    r"\b(?:([A-Z][a-z]{3,}(?:us|um|a|is|on|es|as|ix))|[A-Z]\.) +([a-z]+)\b"
)
EPITHET = re.compile(
    r"[a-z]{2,}(?:us|um|ae|ii|i|is|a)(?<!ous)(?<!sis)(?<!itis)(?<!ia)(?<!ma)(?<!oea)"
)
LATIN_ONLY = re.compile(r"[a-z]+(?:ae|i|is)(?<!sis)(?<!itis)")
KEPT_GENUS = re.compile(r"[A-Z][a-z]+(?:us|um)")
# Places and titles, matched exactly and case-sensitively anywhere. "Sulphur"
# alone is read as the element: the city is named with its state.
PROPER_NOUNS: tuple[str, ...] = (
    "Encyclopaedia Britannica",
    "Sulphur Springs",  # Texas; and White Sulphur Springs, West Virginia
    "Sulphur, Louisiana",
    "Sulphur, LA",
)


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

# The ligatures, as their two letters. Each is one character, so a word keeps
# its length and its column when it is read this way.
LIGATURES = str.maketrans({"œ": "oe", "æ": "ae"})


def american(word: str) -> str | None:
    """The American spelling of `word`, lowercase, or None if it is not British."""
    key = word.lower().translate(LIGATURES)
    hit = BRITISH.get(key)
    if hit is not None:
        return hit
    if key in GENERA or key.endswith(TAXON_SUFFIXES):
        return None
    respelled = key
    for pattern, american_segment in SEGMENT_PATTERNS:
        respelled = pattern.sub(american_segment, respelled)
    if respelled == key:
        return None
    # A segment and an ending can both be British: "anaesthetise" is respelled
    # "anesthetise" by its segment, and then "anesthetize" by the -ise family.
    return BRITISH.get(respelled, respelled)


MARKER = "spelling-ok"
# A word, as the checker sees one: a run of letters, split where an identifier
# changes case, so `colourPicker`, `MAX_COLOURS` and `data-colour-id` are each
# read as their words. Underscores, digits and hyphens separate words.
WORD = re.compile(r"[A-ZŒÆ]+(?![a-zœæ])|[A-ZŒÆ]?[a-zœæ]+")
# The whole run of letters, without splitting identifiers (kept for the tests'
# mutation that shows the split matters).
WHOLE = re.compile(r"[A-Za-zŒÆœæ]+")
# A URL or a path can legitimately contain any spelling; it is not prose. A URL
# has a scheme. A run with a slash is a path only if it starts with "./", "../"
# or "/", or a segment has a file extension: "colour/flavour" is prose. A run
# is matched from its first character (a match starts at the leftmost place it
# can, and every character a run is made of can start one), so no lookbehind
# is needed to keep a match from starting mid-run.
URL = re.compile(r"\b[A-Za-z][\w+.-]*://\S+")
SLASHED = re.compile(r"[\w.~-]*/[\w./~-]*")
EXTENSION = re.compile(r"\w\.[A-Za-z0-9]+$")


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


def blank_urls(line: str) -> str:
    return SLASHED.sub(blank_path, URL.sub(blank, line))


def blank_names(line: str) -> str:
    """Blank the proper nouns and the species epithets, which keep their
    spelling. Each is replaced by spaces of its length, so columns hold."""
    for name in PROPER_NOUNS:
        line = line.replace(name, " " * len(name))
    for match in BINOMIAL.finditer(line):
        genus, epithet = match.group(1, 2)
        if not EPITHET.fullmatch(epithet):
            continue
        spans = [match.span(2)]
        if genus and KEPT_GENUS.fullmatch(genus) and LATIN_ONLY.fullmatch(epithet):
            spans.append(match.span(1))
        for start, end in spans:
            line = line[:start] + " " * (end - start) + line[end:]
    return line


def american_for(word: str, american: str) -> str:
    """The American spelling, in the case the British one was written in."""
    if word.isupper() and len(word) > 1:
        return american.upper()
    if word[0].isupper():
        return american[0].upper() + american[1:]
    return american


def find(line: str, allow: list[str]) -> list[tuple[int, str, str]]:
    """(column, British word, American word) for each hit in one line.

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
    scannable = blank_names(blank_urls(scannable))
    hits = []
    for match in WORD.finditer(scannable):
        word = match.group(0)
        respelled = american(word)
        if respelled is not None:
            hits.append((match.start(), word, american_for(word, respelled)))
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
    and translations. pre-commit names files itself, so this applies to them."""
    resolved = path.resolve()
    if resolved == SELF:
        return True
    if resolved == ALLOWLIST.resolve():
        return True
    try:
        rel = str(resolved.relative_to(ROOT))
    except ValueError:
        return False
    return rel in QUOTED_VERBATIM or is_translation(rel)


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
        for column, word, respelled in find(line, phrases):
            problems.append(
                f"{path}:{number}:{column + 1}: "
                f"British spelling {word!r} -- use {respelled!r}\n"
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


def fix(path: Path, allow: list[Allow]) -> int:
    """Rewrite British spellings in place. Returns how many were changed.

    Uses the same scan as check(), so it changes exactly what check() reports:
    never an exempt line, an allowed phrase or a URL. A file that cannot be
    read raises, so the caller reports it.
    """
    text = read(path)
    phrases = allowed_in(path, allow)

    changed = 0
    out = []
    for line in text.splitlines(keepends=True):
        # Right to left, so an earlier column is not moved by a later change.
        for column, word, respelled in reversed(find(line, phrases)):
            line = line[:column] + respelled + line[column + len(word) :]
            changed += 1
        out.append(line)

    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


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
        for path in targets(argv):
            if path.is_file() and not skip(path):
                try:
                    n = fix(path, allow)
                except (UnicodeDecodeError, OSError) as error:
                    print(f"  could not read {path}: {error}", file=sys.stderr)
                    unread += 1
                    continue
                if n:
                    try:
                        shown = path.resolve().relative_to(ROOT)
                    except ValueError:
                        shown = path
                    print(f"  {n:3d}  {shown}")
                    total += n
        print(f"\n{total} spelling(s) corrected")
        return 1 if unread else 0

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
