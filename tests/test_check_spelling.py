#!/usr/bin/env python3
"""The British-spelling guard, tested as a guardrail (#169).

scripts/check_spelling.py runs in pre-commit and CI and had no tests, so nothing
showed it failing. It missed a plural in docs/developing.md because only the
singular was listed: a word list of exact forms catches the forms someone
thought to type, and every other inflection of the same root passes in silence.

What is pinned, both ways:

* every word the checker knows is caught in prose, in a code comment, in a
  string, and as a part of an identifier (snake_case, camelCase, kebab-case),
  in lower, Title and UPPER case;
* the inflections of each root (plural, -ed, -ing, -er, -al, -able, the
  -isation family, a prefix such as un- or re-) are caught, from a table written
  independently of the checker, so a root listed in only one form fails here;
* words that merely contain a British string, and American words that look like
  an inflection ("enrolled", "analyses", "programmed"), are not flagged;
* `spelling-ok` exempts its own line and no other; a `.spelling-allow` phrase
  exempts that phrase and not the rest of the line;
* SKIP_DIRS, QUOTED_VERBATIM and the checker itself are skipped, and nothing
  that only looks like them is;
* --fix rewrites in place, keeping case, and leaves exempt text alone;
* the command exits nonzero on a hit and zero on clean input.

Then the checker is broken on purpose (a word dropped, case folding off, an
exemption widened or disabled, the inflections no longer generated) and the same
assertions must notice. A check never shown to fail is a claim, not a control.

The British words below are test data, so their lines carry `spelling-ok`.

    pixi run test-check-spelling
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "check_spelling.py"
sys.path.insert(0, str(SCRIPTS))

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def load(source: str | None = None, name: str = "check_spelling") -> ModuleType:
    """The real checker, or a copy of it built from `source` (a mutant)."""
    path = SCRIPT
    if source is not None:
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "check_spelling.py"
        path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cs = load()

# ---------------------------------------------------------------------------
# Test data. Each row is "british american"; the trailing marker exempts the
# line from the checker this file is testing. Written by hand, not derived from
# the checker, so it is an independent account of what must be caught.
# ---------------------------------------------------------------------------

INFLECTIONS = """
judgement judgment  spelling-ok
behaviour behavior  spelling-ok
colour color  spelling-ok
centre center  spelling-ok
organise organize  spelling-ok
catalogue catalog  spelling-ok
grey gray  spelling-ok
towards toward  spelling-ok
behaviours behaviors  spelling-ok
misbehaviour misbehavior  spelling-ok
behaviourist behaviorist  spelling-ok
colouring coloring  spelling-ok
colourful colorful  spelling-ok
colourless colorless  spelling-ok
discoloured discolored  spelling-ok
watercolours watercolors  spelling-ok
favoured favored  spelling-ok
favouring favoring  spelling-ok
favourable favorable  spelling-ok
unfavourable unfavorable  spelling-ok
favourites favorites  spelling-ok
honoured honored  spelling-ok
honourable honorable  spelling-ok
dishonour dishonor  spelling-ok
labourer laborers  spelling-ok
labourers laborers  spelling-ok
laboured labored  spelling-ok
neighbourhood neighborhood  spelling-ok
neighbouring neighboring  spelling-ok
neighbours neighbors  spelling-ok
rumoured rumored  spelling-ok
endeavours endeavors  spelling-ok
endeavoured endeavored  spelling-ok
flavours flavors  spelling-ok
humour humor  spelling-ok
tumours tumors  spelling-ok
harbour harbor  spelling-ok
centring centering  spelling-ok
centres centers  spelling-ok
kilometres kilometers  spelling-ok
centimetre centimeter  spelling-ok
theatres theaters  spelling-ok
fibres fibers  spelling-ok
litres liters  spelling-ok
licences licenses  spelling-ok
defences defenses  spelling-ok
defenceless defenseless  spelling-ok
offences offenses  spelling-ok
recognising recognizing  spelling-ok
recognisable recognizable  spelling-ok
unrecognised unrecognized  spelling-ok
reorganised reorganized  spelling-ok
organiser organizer  spelling-ok
organisers organizers  spelling-ok
disorganised disorganized  spelling-ok
normaliser normalizer  spelling-ok
serialiser serializer  spelling-ok
deserialise deserialize  spelling-ok
deserialised deserialized  spelling-ok
prioritising prioritizing  spelling-ok
prioritisation prioritization  spelling-ok
authorising authorizing  spelling-ok
unauthorised unauthorized  spelling-ok
minimises minimizes  spelling-ok
optimiser optimizer  spelling-ok
optimisation optimization  spelling-ok
standardising standardizing  spelling-ok
specialising specializing  spelling-ok
specialisation specialization  spelling-ok
utilisation utilization  spelling-ok
categorisation categorization  spelling-ok
characterisation characterization  spelling-ok
emphasising emphasizing  spelling-ok
apologised apologized  spelling-ok
realising realizing  spelling-ok
realisation realization  spelling-ok
criticising criticizing  spelling-ok
synthesising synthesizing  spelling-ok
initialising initializing  spelling-ok
customised customized  spelling-ok
anonymised anonymized  spelling-ok
pseudonymisation pseudonymization  spelling-ok
analyser analyzer  spelling-ok
paralysed paralyzed  spelling-ok
labeller labeler  spelling-ok
relabelled relabeled  spelling-ok
mislabelled mislabeled  spelling-ok
travellers travelers  spelling-ok
signalling signaling  spelling-ok
fuelling fueling  spelling-ok
modeller modeler  spelling-ok
cancelling canceling  spelling-ok
levelled leveled  spelling-ok
counsellor counselor  spelling-ok
catalogued cataloged  spelling-ok
cataloguing cataloging  spelling-ok
catalogues catalogs  spelling-ok
greying graying  spelling-ok
greyish grayish  spelling-ok
greyscale grayscale  spelling-ok
fulfilment fulfillment  spelling-ok
fulfils fulfills  spelling-ok
enrols enrolls  spelling-ok
enrolments enrollments  spelling-ok
instalments installments  spelling-ok
skilfully skillfully  spelling-ok
wilful willful  spelling-ok
acknowledgements acknowledgments  spelling-ok
misjudgement misjudgment  spelling-ok
judgements judgments  spelling-ok
artefacts artifacts  spelling-ok
manoeuvring maneuvering  spelling-ok
mouldy moldy  spelling-ok
ploughing plowing  spelling-ok
sceptics skeptics  spelling-ok
practising practicing  spelling-ok
practised practiced  spelling-ok
specialities specialties  spelling-ok
programmes programs  spelling-ok
tyres tires  spelling-ok
storeys stories  spelling-ok
paediatric pediatric  spelling-ok
anaesthesia anesthesia  spelling-ok
haemoglobin hemoglobin  spelling-ok
oedema edema  spelling-ok
"""

# American words, and words that merely contain a British string, which the
# checker must leave alone. Several are inflections of an American root that
# look like a British one ("enrolled" holds a British root; "analyses" is the
# plural of "analysis"), and the repository uses most of them.
AMERICAN = """
enrolled enrolling enrollment installed installing installment fulfilled
fulfilling analyses paralyses programmed programming programmer cancellation
licensed licensee practices practiced catalog dialogue analog colored meter
center theater offense defense behavior organize organization greyhound
Kerberos parameter diameter tour contour devour concentrate excelled
controlled propelled advise revise supervised exercise enterprise compromise
surprised televised advertise acre genre massacre mediocre ogre glamour
modeled labeled travel signal channel dialed fueled while among toward
judgment acknowledgment specialty skeptical mold plow draft artifact story
"""

# Ordinary American lines that must stay clean, a URL and a path among them.
CLEAN = [
    "The organization analyzes behavior and favors a gray, centered layout.",
    "See https://example.org/colour/behaviour for the source.",  # spelling-ok
    "Read docs/organisation/centre.md first.",  # spelling-ok
]


def rows(table: str) -> list[tuple[str, str]]:
    out = []
    for line in table.strip().splitlines():
        british, american = line.split()[:2]
        out.append((british, american))
    return out


INFLECTION_ROWS = [
    (b, "laborer" if b == "labourer" else a)  # spelling-ok
    for b, a in rows(INFLECTIONS)
]

HIT = re.compile(r":(\d+):(\d+): British spelling '([^']+)' -- use '([^']+)'")


def scan(mod: ModuleType, lines: list[str], allow: list[str] | None = None) -> dict:
    """Run mod.check on a file of `lines`; return {line number: [(word, fix)]}."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        problems = mod.check(path, allow or [])
    found: dict[int, list[tuple[str, str]]] = {}
    for msg in problems:
        m = HIT.search(msg)
        if m:
            found.setdefault(int(m.group(1)), []).append((m.group(3), m.group(4)))
    return found


def fixed(mod: ModuleType, text: str, allow: list[str] | None = None) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sample.md"
        path.write_text(text, encoding="utf-8")
        mod.fix(path, allow or [])
        return path.read_text(encoding="utf-8")


def cased(word: str, like: str) -> str:
    if like.isupper():
        return word.upper()
    if like[0].isupper():
        return word[0].upper() + word[1:]
    return word


# ---------------------------------------------------------------------------
# Properties. Each takes the module under test and returns the names of the
# properties that failed, so the mutation tests can run them on a broken copy.
# ---------------------------------------------------------------------------

CONTEXTS: list[tuple[str, Callable[[str], str], Callable[[str], str]]] = [
    ("prose", lambda w: f"The {w} matters here.", lambda w: w),
    ("a code comment", lambda w: f"x = 1  # the {w} of it", lambda w: w),
    ("a string", lambda w: f'label = "{w}"', lambda w: w),
    ("snake_case", lambda w: f"my_{w}_value = 2", lambda w: w),
    ("kebab-case", lambda w: f"data-{w}-id", lambda w: w),
    ("camelCase", lambda w: f"get{w.capitalize()}Value()", lambda w: w.capitalize()),
    ("Title case", lambda w: f"{w.capitalize()} first.", lambda w: w.capitalize()),
    ("UPPER CASE", lambda w: f"A {w.upper()} SHOUT", lambda w: w.upper()),
    ("UPPER_SNAKE", lambda w: f"MAX_{w.upper()}_SIZE = 3", lambda w: w.upper()),
]


def every_word(mod: ModuleType) -> list[str]:
    """Every British word the checker knows, in every context, with its fix."""
    bad = []
    words = sorted(mod.BRITISH.items())
    for label, make, shape in CONTEXTS:
        lines = [make(w) for w, _ in words]
        found = scan(mod, lines)
        missed = [
            w
            for n, (w, a) in enumerate(words, 1)
            if found.get(n) != [(shape(w), cased(a, shape(w)))]
        ]
        if missed:
            bad.append(f"every listed word caught in {label} (missed {missed[:5]})")
    return bad


def inflections(mod: ModuleType) -> list[str]:
    lines = [f"The {b} here." for b, _ in INFLECTION_ROWS]
    found = scan(mod, lines)
    missed = [
        f"{b}->{found.get(n)}"
        for n, (b, a) in enumerate(INFLECTION_ROWS, 1)
        if found.get(n) != [(b, a)]
    ]
    return [f"inflections caught (missed {missed[:8]})"] if missed else []


def american_left_alone(mod: ModuleType) -> list[str]:
    words = AMERICAN.split()
    found = scan(mod, [f"The {w} here." for w in words] + CLEAN)
    return [f"no false positives (flagged {sorted(found.items())[:5]})"] * bool(found)


def case_folding(mod: ModuleType) -> list[str]:
    word = "behaviour"  # spelling-ok
    found = scan(mod, [word, word.capitalize(), word.upper()])
    return [] if len(found) == 3 else [f"case variants caught ({found})"]


def spelling_ok(mod: ModuleType) -> list[str]:
    lines = [
        "The colour is quoted.  <!-- spelling-ok -->",  # spelling-ok
        "The colour is not.",  # spelling-ok
        "spelling ok is not the marker: colour",  # spelling-ok
    ]
    found = scan(mod, lines)
    return [] if sorted(found) == [2, 3] else [f"spelling-ok is per line ({found})"]


def allowlist(mod: ModuleType) -> list[str]:
    allow = ["the 'cancelled' state"]  # spelling-ok
    lines = [
        "if result == the 'cancelled' state:",  # spelling-ok
        "if result == the 'cancelled' state: the behaviour too",  # spelling-ok
        "if result == 'cancelled':",  # spelling-ok
    ]
    found = scan(mod, lines, allow)
    british = ("behaviour", "cancelled")  # spelling-ok
    want = {2: [(british[0], "behavior")], 3: [(british[1], "canceled")]}
    return [] if found == want else [f"an allowed phrase exempts only itself ({found})"]


def fixes(mod: ModuleType) -> list[str]:
    text = (
        "Behaviour, BEHAVIOUR and behaviour;\n"  # spelling-ok
        "a colourPicker and MAX_COLOURS.\n"  # spelling-ok
        "The colour stays.  <!-- spelling-ok -->\n"  # spelling-ok
        "See https://example.org/colour for it.\n"  # spelling-ok
        "Keep the 'cancelled' state but fix the centre.\n"  # spelling-ok
        "Unrecognised judgements.\n"  # spelling-ok
    )
    want = (
        "Behavior, BEHAVIOR and behavior;\n"
        "a colorPicker and MAX_COLORS.\n"
        "The colour stays.  <!-- spelling-ok -->\n"  # spelling-ok
        "See https://example.org/colour for it.\n"  # spelling-ok
        "Keep the 'cancelled' state but fix the center.\n"  # spelling-ok
        "Unrecognized judgments.\n"
    )
    got = fixed(mod, text, ["the 'cancelled' state"])  # spelling-ok
    return [] if got == want else [f"--fix keeps case and exemptions ({got!r})"]


PROPERTIES = [
    every_word,
    inflections,
    american_left_alone,
    case_folding,
    spelling_ok,
    allowlist,
    fixes,
]


def run_properties(mod: ModuleType) -> list[str]:
    return [problem for prop in PROPERTIES for problem in prop(mod)]


# ---------------------------------------------------------------------------
# The sections run against the real checker.
# ---------------------------------------------------------------------------


def real_checker() -> None:
    print("The real checker")
    for prop in PROPERTIES:
        problems = prop(cs)
        check(prop.__name__.replace("_", " "), not problems, "; ".join(problems))
    check(
        "the word list is not trivially small",
        len(cs.BRITISH) > 500,
        str(len(cs.BRITISH)),
    )
    check(
        "#169: the plural that was missed is listed",
        cs.BRITISH.get("judgements") == "judgments",  # spelling-ok
    )


def skipping() -> None:
    print("What is skipped, and nothing else")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        british = "The colour.\n"  # spelling-ok
        names = [f"{d}/a.md" for d in sorted(cs.SKIP_DIRS)]
        near = [
            "sites/a.md",
            "builder/a.md",
            "website/a.md",
            "docs/build.md",
            "docs/site/notes.md" if "site" not in cs.SKIP_DIRS else "docs/sitemap.md",
            "my.git/a.md",
            "docs/a.md",
        ]
        for rel in names + near:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(british, encoding="utf-8")
        nested = root / "docs" / "node_modules" / "pkg" / "a.md"
        nested.parent.mkdir(parents=True)
        nested.write_text(british, encoding="utf-8")

        saved = cs.ROOT
        cs.ROOT = root
        try:
            found = {str(p.relative_to(root)) for p in cs.targets([])}
        finally:
            cs.ROOT = saved
        leaked = [n for n in names if n in found]
        check("every SKIP_DIRS directory is skipped", not leaked, str(leaked))
        check(
            "a SKIP_DIRS name nested deeper is skipped",
            "docs/node_modules/pkg/a.md" not in found,
        )
        missing = [n for n in near if n not in found]
        check("a name that only resembles one is checked", not missing, str(missing))

    for rel in sorted(cs.QUOTED_VERBATIM):
        check(f"quoted verbatim is skipped: {rel}", cs.skip(cs.ROOT / rel))
    for rel in [
        "data/other.json",
        "docs/frameworks/other.md",
        "docs/app/other.html",
        "app/js/10-frameworks/10-chai/06-other.js",
    ]:
        check(f"its neighbor is checked: {rel}", not cs.skip(cs.ROOT / rel))
    check("the checker itself is skipped", cs.skip(SCRIPT))
    check("this test is not skipped", not cs.skip(Path(__file__)))
    check(
        "a file outside the repository is checked",
        not cs.skip(Path(tempfile.gettempdir()) / "x.md"),
    )
    problems = cs.check(Path(__file__), cs.load_allowlist())
    check("this test file passes its own checker", not problems, str(problems[:2]))


def command_line() -> None:
    print("The command")
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.md"
        good = Path(tmp) / "good.md"
        bad.write_text("Our judgements.\n", encoding="utf-8")  # spelling-ok
        good.write_text("Our judgments.\n", encoding="utf-8")

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(SCRIPT), *args],
                capture_output=True,
                text=True,
                check=False,
            )

        hit = run(str(bad))
        check("a British spelling exits nonzero", hit.returncode == 1, hit.stderr)
        check("and names the file and the word", "bad.md:1:5" in hit.stderr, hit.stderr)
        clean = run(str(good))
        check("clean input exits zero", clean.returncode == 0, clean.stderr)
        both = run(str(good), str(bad))
        check("one bad file among good ones fails", both.returncode == 1)
        fix = run("--fix", str(bad))
        check("--fix exits zero", fix.returncode == 0, fix.stderr)
        check(
            "--fix rewrote the file",
            bad.read_text(encoding="utf-8") == "Our judgments.\n",
        )
        check("and the file is clean after", run(str(bad)).returncode == 0)


# ---------------------------------------------------------------------------
# Mutation tests: break a copy of the checker, demand the properties notice.
# ---------------------------------------------------------------------------

MUTATIONS: list[tuple[str, str, str]] = [
    # (what is broken, text in the checker, replacement)
    ("a root is dropped", '"behavi",', ""),  # spelling-ok
    ("an explicit word is dropped", '"judgement": "judgment",', ""),  # spelling-ok
    ("case folding is off", "BRITISH.get(word.lower())", "BRITISH.get(word)"),
    ("spelling-ok is ignored", "if MARKER in line:", "if False:"),
    (
        "any mention of spelling exempts a line",
        "if MARKER in line:",
        'if MARKER.split("-")[0] in line:',
    ),
    ("the allowlist is ignored", "for phrase in allow:", "for phrase in ():"),
    (
        "an allowed phrase exempts its whole line",
        "for phrase in allow:",
        "for phrase in ([] if any(p in line for p in allow) else allow):",
    ),
    (
        "inflections are not generated",
        "for ending_b, ending_a in endings",
        "for ending_b, ending_a in endings[:1]",
    ),
    (
        "prefixes are not generated",
        "for prefix in prefixes",
        "for prefix in prefixes[:1]",
    ),
    (
        "identifiers are not split",
        "WORD.finditer(scannable)",
        "WHOLE.finditer(scannable)",
    ),
    ("URLs are not blanked", "scannable = URLISH.sub(blank, scannable)", "pass"),
    ("--fix ignores case", "return american.upper()", "return american"),
]


def mutations() -> None:
    print("Mutation tests: a broken checker is noticed")
    source = SCRIPT.read_text(encoding="utf-8")
    for n, (what, old, new) in enumerate(MUTATIONS):
        present = old in source
        check(f"mutation applies: {what}", present, f"{old!r} not in the checker")
        if not present:
            continue
        mutant = load(source.replace(old, new), name=f"check_spelling_mutant_{n}")
        try:
            problems = run_properties(mutant)
        except Exception as error:  # a crash is not a mutation worth the name
            check(f"the mutant runs: {what}", False, repr(error))
            continue
        check(f"noticed: {what}", bool(problems), "every property still passed")

    with tempfile.TemporaryDirectory() as tmp:
        mutant = load(
            source.replace("rel in QUOTED_VERBATIM or ", ""), "check_spelling_mutant_q"
        )
        quoted = sorted(cs.QUOTED_VERBATIM)[0]
        check("noticed: QUOTED_VERBATIM ignored", not mutant.skip(ROOT / quoted))
        mutant = load(
            source.replace("if resolved == SELF:", "if False:"),
            "check_spelling_mutant_s",
        )
        check(
            "noticed: the checker no longer skips itself",
            not mutant.skip(Path(tmp) / "check_spelling.py"),
        )


def main() -> int:
    real_checker()
    skipping()
    command_line()
    mutations()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("spelling guardrail checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
