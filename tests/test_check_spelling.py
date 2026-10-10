#!/usr/bin/env python3
"""The British-spelling guard, tested as a guardrail (#169).

scripts/check_spelling.py runs in pre-commit and CI and had no tests, so nothing
showed it failing. It missed a plural in docs/developing.md because only the
singular was listed: a word list of exact forms catches the forms someone
thought to type, and every other inflection of the same root passes in silence.

What is pinned, both ways:

* every word the checker generates, and every word of the table, is caught in
  prose, in a code comment, in a string, and as a part of an identifier
  (snake_case, camelCase, kebab-case), in lower, Title and UPPER case;
* a table written by hand, independently of the checker, is caught with the
  American form it names. It names every EXPLICIT word, and a form of every
  stem, ending and prefix of every family and of every segment (the medical
  family among them), and the tests demand it does, so dropping any part of the
  checker leaves a row uncaught; no EXPLICIT word may also be generated, so
  dropping one is always noticed;
* a British word written with a ligature ("oe" or "ae" as one letter) is caught;
* American words, and American words a careless new stem would generate
  ("precise", "compelled", "lustring", "Haemophilus"), are not flagged;
* a slash in prose (two words joined by "/") is not a path, while a URL, ./, ../, an
  absolute path and a path with a file extension are;
* `spelling-ok` exempts its own line and no other; a `.spelling-allow` entry
  exempts its exact phrase, in its own case, only in the files its glob names,
  and an entry with no glob is refused;
* a file that is not UTF-8 is reported, not passed;
* targets() and skip() read every kind of file we write (.py, .js, .json, .toml,
  .yml, .yaml, .sql, .md, a Caddyfile and a Dockerfile, app/i18n/en.json) and
  none of our real files is skipped, while translations, SKIP_DIRS,
  QUOTED_VERBATIM, the allowlist and the checker itself are;
* --fix rewrites in place, keeping case, and leaves exempt text alone;
* the command exits nonzero on a hit, or a file it cannot read, and zero on
  clean input.

Then the checker is broken on purpose (a word, stem, ending, prefix or segment
dropped; a stem added that generates an American word; case folding off; an
exemption widened, unscoped or disabled; a file kind no longer read) and the
same assertions must notice. A check never shown to fail is a claim, not a
control.

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
from concurrent.futures import ProcessPoolExecutor
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
    # A mutant lives in a temporary directory, so it would take that for the
    # repository root and judge every real path as outside it. Point it home.
    module.ROOT = ROOT
    module.ALLOWLIST = ROOT / ".spelling-allow"
    return module


cs = load()

# ---------------------------------------------------------------------------
# Test data. Each row is "british american"; the trailing marker exempts the
# line from the checker this file is testing. Written by hand, not derived from
# the checker, so it is an independent account of what must be caught.
# ---------------------------------------------------------------------------

TABLE = """
# Every EXPLICIT word, by name. The tests demand this is exactly EXPLICIT, so a
# word dropped from the checker, or added without being written down here, fails.
judgement judgment  spelling-ok
judgements judgments  spelling-ok
judgemental judgmental  spelling-ok
misjudgement misjudgment  spelling-ok
misjudgements misjudgments  spelling-ok
abridgement abridgment  spelling-ok
acknowledgement acknowledgment  spelling-ok
acknowledgements acknowledgments  spelling-ok
catalogue catalog  spelling-ok
catalogues catalogs  spelling-ok
catalogued cataloged  spelling-ok
cataloguing cataloging  spelling-ok
cataloguer cataloger  spelling-ok
cataloguers catalogers  spelling-ok
grey gray  spelling-ok
greys grays  spelling-ok
greyed grayed  spelling-ok
greying graying  spelling-ok
greyer grayer  spelling-ok
greyest grayest  spelling-ok
greyish grayish  spelling-ok
greyness grayness  spelling-ok
greyscale grayscale  spelling-ok
fulfil fulfill  spelling-ok
fulfils fulfills  spelling-ok
fulfilment fulfillment  spelling-ok
fulfilments fulfillments  spelling-ok
enrol enroll  spelling-ok
enrols enrolls  spelling-ok
enrolment enrollment  spelling-ok
enrolments enrollments  spelling-ok
instal install  spelling-ok
instals installs  spelling-ok
instalment installment  spelling-ok
instalments installments  spelling-ok
instil instill  spelling-ok
instils instills  spelling-ok
skilful skillful  spelling-ok
skilfully skillfully  spelling-ok
unskilful unskillful  spelling-ok
wilful willful  spelling-ok
wilfully willfully  spelling-ok
woollen woolen  spelling-ok
woollens woolens  spelling-ok
ageing aging  spelling-ok
learnt learned  spelling-ok
unlearnt unlearned  spelling-ok
towards toward  spelling-ok
amongst among  spelling-ok
whilst while  spelling-ok
enquiry inquiry  spelling-ok
enquiries inquiries  spelling-ok
programme program  spelling-ok
programmes programs  spelling-ok
storey story  spelling-ok
storeys stories  spelling-ok
tyre tire  spelling-ok
tyres tires  spelling-ok
plough plow  spelling-ok
ploughs plows  spelling-ok
ploughed plowed  spelling-ok
ploughing plowing  spelling-ok
aluminium aluminum  spelling-ok
artefact artifact  spelling-ok
artefacts artifacts  spelling-ok
draught draft  spelling-ok
draughts drafts  spelling-ok
draughty drafty  spelling-ok
kerb curb  spelling-ok
kerbs curbs  spelling-ok
lustre luster  spelling-ok
lustres lusters  spelling-ok
manoeuvre maneuver  spelling-ok
manoeuvres maneuvers  spelling-ok
manoeuvred maneuvered  spelling-ok
manoeuvring maneuvering  spelling-ok
manoeuvrable maneuverable  spelling-ok
manoeuvrability maneuverability  spelling-ok
mould mold  spelling-ok
moulds molds  spelling-ok
moulded molded  spelling-ok
moulding molding  spelling-ok
mouldings moldings  spelling-ok
mouldy moldy  spelling-ok
moult molt  spelling-ok
moults molts  spelling-ok
moulted molted  spelling-ok
moulting molting  spelling-ok
smoulder smolder  spelling-ok
smoulders smolders  spelling-ok
smouldered smoldered  spelling-ok
smouldering smoldering  spelling-ok
moustache mustache  spelling-ok
moustaches mustaches  spelling-ok
practise practice  spelling-ok
practised practiced  spelling-ok
practises practices  spelling-ok
practising practicing  spelling-ok
sceptic skeptic  spelling-ok
sceptics skeptics  spelling-ok
sceptical skeptical  spelling-ok
sceptically skeptically  spelling-ok
scepticism skepticism  spelling-ok
speciality specialty  spelling-ok
specialities specialties  spelling-ok
cheque check  spelling-ok
cheques checks  spelling-ok
pyjamas pajamas  spelling-ok
aeroplane airplane  spelling-ok
aeroplanes airplanes  spelling-ok
tumourigenic tumorigenic  spelling-ok
tumourigenicity tumorigenicity  spelling-ok
tumourigenesis tumorigenesis  spelling-ok

# -our: a form of every stem, every ending and every prefix.
ardour ardor  spelling-ok
armoured armored  spelling-ok
behaviour behavior  spelling-ok
behaviours behaviors  spelling-ok
behavioural behavioral  spelling-ok
behaviourally behaviorally  spelling-ok
behaviourism behaviorism  spelling-ok
behaviourist behaviorist  spelling-ok
behaviourists behaviorists  spelling-ok
misbehaviour misbehavior  spelling-ok
candour candor  spelling-ok
clamouring clamoring  spelling-ok
colour color  spelling-ok
colourings colorings  spelling-ok
colourful colorful  spelling-ok
colourfully colorfully  spelling-ok
colourless colorless  spelling-ok
colourise colorize  spelling-ok
colourised colorized  spelling-ok
colourising colorizing  spelling-ok
discoloured discolored  spelling-ok
watercolours watercolors  spelling-ok
multicoloured multicolored  spelling-ok
demeanour demeanor  spelling-ok
endeavours endeavors  spelling-ok
endeavoured endeavored  spelling-ok
favoured favored  spelling-ok
favouring favoring  spelling-ok
favourable favorable  spelling-ok
favourably favorably  spelling-ok
unfavourable unfavorable  spelling-ok
favourite favorite  spelling-ok
favourites favorites  spelling-ok
fervour fervor  spelling-ok
flavours flavors  spelling-ok
harbour harbor  spelling-ok
honoured honored  spelling-ok
honourable honorable  spelling-ok
dishonour dishonor  spelling-ok
humour humor  spelling-ok
humourless humorless  spelling-ok
labourer laborer  spelling-ok
labourers laborers  spelling-ok
laboured labored  spelling-ok
neighbourhood neighborhood  spelling-ok
neighbourhoods neighborhoods  spelling-ok
neighbouring neighboring  spelling-ok
neighbourly neighborly  spelling-ok
neighbours neighbors  spelling-ok
odours odors  spelling-ok
parlour parlor  spelling-ok
rancour rancor  spelling-ok
rigour rigor  spelling-ok
rumoured rumored  spelling-ok
saviour savior  spelling-ok
savoury savory  spelling-ok
splendour splendor  spelling-ok
succour succor  spelling-ok
tumour tumor  spelling-ok
tumours tumors  spelling-ok
valour valor  spelling-ok
vapours vapors  spelling-ok
vigour vigor  spelling-ok

# -re
calibre caliber  spelling-ok
centre center  spelling-ok
centres centers  spelling-ok
centred centered  spelling-ok
centring centering  spelling-ok
epicentre epicenter  spelling-ok
decentred decentered  spelling-ok
recentred recentered  spelling-ok
fibres fibers  spelling-ok
goitre goiter  spelling-ok
litres liters  spelling-ok
meagre meager  spelling-ok
metres meters  spelling-ok
kilometres kilometers  spelling-ok
centimetre centimeter  spelling-ok
millimetre millimeter  spelling-ok
micrometre micrometer  spelling-ok
nanometre nanometer  spelling-ok
ochre ocher  spelling-ok
sabres sabers  spelling-ok
sceptre scepter  spelling-ok
sombre somber  spelling-ok
spectre specter  spelling-ok
theatres theaters  spelling-ok

# -ce
defence defense  spelling-ok
defences defenses  spelling-ok
defenceless defenseless  spelling-ok
self-defence self-defense  spelling-ok
licences licenses  spelling-ok
licenced licensed  spelling-ok
licencing licensing  spelling-ok
sublicence sublicense  spelling-ok
offences offenses  spelling-ok
pretence pretense  spelling-ok

# -ise
anaesthetise anesthetize  spelling-ok
anaesthetised anesthetized  spelling-ok
anesthetise anesthetize  spelling-ok
anonymised anonymized  spelling-ok
apologised apologized  spelling-ok
authorising authorizing  spelling-ok
unauthorised unauthorized  spelling-ok
preauthorisation preauthorization  spelling-ok
capitalise capitalize  spelling-ok
categorisation categorization  spelling-ok
catheterise catheterize  spelling-ok
catheterisation catheterization  spelling-ok
centralised centralized  spelling-ok
characterisation characterization  spelling-ok
mischaracterised mischaracterized  spelling-ok
civilisation civilization  spelling-ok
colonise colonize  spelling-ok
conceptualise conceptualize  spelling-ok
containerised containerized  spelling-ok
contextualise contextualize  spelling-ok
criticising criticizing  spelling-ok
customised customized  spelling-ok
digitise digitize  spelling-ok
emphasising emphasizing  spelling-ok
overemphasise overemphasize  spelling-ok
energise energize  spelling-ok
equalise equalize  spelling-ok
familiarise familiarize  spelling-ok
fantasise fantasize  spelling-ok
finalised finalized  spelling-ok
formalise formalize  spelling-ok
generalisation generalization  spelling-ok
globalisation globalization  spelling-ok
harmonise harmonize  spelling-ok
hospitalised hospitalized  spelling-ok
hypothesise hypothesize  spelling-ok
idealised idealized  spelling-ok
immunise immunize  spelling-ok
immunisation immunization  spelling-ok
incentivise incentivize  spelling-ok
initialising initializing  spelling-ok
internalise internalize  spelling-ok
itemised itemized  spelling-ok
jeopardise jeopardize  spelling-ok
legalise legalize  spelling-ok
legitimise legitimize  spelling-ok
localisation localization  spelling-ok
marginalised marginalized  spelling-ok
materialise materialize  spelling-ok
maximise maximize  spelling-ok
memorise memorize  spelling-ok
metabolise metabolize  spelling-ok
minimises minimizes  spelling-ok
mobilise mobilize  spelling-ok
modernise modernize  spelling-ok
monetise monetize  spelling-ok
nationalised nationalized  spelling-ok
neutralise neutralize  spelling-ok
normaliser normalizer  spelling-ok
operationalise operationalize  spelling-ok
optimiser optimizer  spelling-ok
optimisers optimizers  spelling-ok
optimisation optimization  spelling-ok
organise organize  spelling-ok
organisational organizational  spelling-ok
organisations organizations  spelling-ok
reorganised reorganized  spelling-ok
disorganised disorganized  spelling-ok
parameterised parameterized  spelling-ok
parametrise parametrize  spelling-ok
patronising patronizing  spelling-ok
penalise penalize  spelling-ok
personalised personalized  spelling-ok
polarisation polarization  spelling-ok
popularise popularize  spelling-ok
prioritising prioritizing  spelling-ok
prioritisation prioritization  spelling-ok
privatise privatize  spelling-ok
pseudonymisation pseudonymization  spelling-ok
publicise publicize  spelling-ok
randomised randomized  spelling-ok
rationalise rationalize  spelling-ok
realising realizing  spelling-ok
realisation realization  spelling-ok
recognising recognizing  spelling-ok
recognisable recognizable  spelling-ok
unrecognised unrecognized  spelling-ok
sanitiser sanitizer  spelling-ok
scrutinise scrutinize  spelling-ok
sensitise sensitize  spelling-ok
serialiser serializer  spelling-ok
deserialise deserialize  spelling-ok
deserialised deserialized  spelling-ok
socialise socialize  spelling-ok
specialising specializing  spelling-ok
specialisation specialization  spelling-ok
stabilise stabilize  spelling-ok
standardising standardizing  spelling-ok
nonstandardised nonstandardized  spelling-ok
sterilised sterilized  spelling-ok
subsidise subsidize  spelling-ok
summarises summarizes  spelling-ok
symbolise symbolize  spelling-ok
sympathise sympathize  spelling-ok
synchronise synchronize  spelling-ok
synthesising synthesizing  spelling-ok
theorise theorize  spelling-ok
tokeniser tokenizer  spelling-ok
trivialise trivialize  spelling-ok
utilisation utilization  spelling-ok
underutilised underutilized  spelling-ok
vaporise vaporize  spelling-ok
vascularise vascularize  spelling-ok
vascularisation vascularization  spelling-ok
victimised victimized  spelling-ok
virtualisation virtualization  spelling-ok
visualise visualize  spelling-ok
weaponised weaponized  spelling-ok

# -yse
analyse analyze  spelling-ok
analyser analyzer  spelling-ok
analysers analyzers  spelling-ok
analysing analyzing  spelling-ok
reanalysed reanalyzed  spelling-ok
overanalyse overanalyze  spelling-ok
psychoanalyse psychoanalyze  spelling-ok
catalyse catalyze  spelling-ok
dialyse dialyze  spelling-ok
electrolyse electrolyze  spelling-ok
hydrolysed hydrolyzed  spelling-ok
paralysed paralyzed  spelling-ok

# -ll
cancelling canceling  spelling-ok
channelled channeled  spelling-ok
counsellor counselor  spelling-ok
counsellors counselors  spelling-ok
dialled dialed  spelling-ok
duelling dueling  spelling-ok
enamelled enameled  spelling-ok
equalled equaled  spelling-ok
fuelling fueling  spelling-ok
funnelled funneled  spelling-ok
initialled initialed  spelling-ok
jeweller jeweler  spelling-ok
jewellery jewelry  spelling-ok
labelled labeled  spelling-ok
labeller labeler  spelling-ok
labellings labelings  spelling-ok
relabelled relabeled  spelling-ok
mislabelled mislabeled  spelling-ok
levelled leveled  spelling-ok
libellous libelous  spelling-ok
marvellous marvelous  spelling-ok
marvellously marvelously  spelling-ok
modelling modeling  spelling-ok
modeller modeler  spelling-ok
modellers modelers  spelling-ok
panellist panelist  spelling-ok
panellists panelists  spelling-ok
pedalling pedaling  spelling-ok
quarrelling quarreling  spelling-ok
unravelled unraveled  spelling-ok
revelling reveling  spelling-ok
rivalled rivaled  spelling-ok
shovelled shoveled  spelling-ok
signalling signaling  spelling-ok
snorkelling snorkeling  spelling-ok
spiralling spiraling  spelling-ok
stencilled stenciled  spelling-ok
swivelled swiveled  spelling-ok
totalled totaled  spelling-ok
towelling toweling  spelling-ok
travellers travelers  spelling-ok
tunnelling tunneling  spelling-ok
yodelling yodeling  spelling-ok

# Segments, the medical family among them: every segment, and the inflections
# a list of exact forms missed.
haemorrhage hemorrhage  spelling-ok
haemorrhages hemorrhages  spelling-ok
haemorrhagic hemorrhagic  spelling-ok
haematoma hematoma  spelling-ok
haematomas hematomas  spelling-ok
haematocrit hematocrit  spelling-ok
haematuria hematuria  spelling-ok
haematology hematology  spelling-ok
haematologist hematologist  spelling-ok
haemodialysis hemodialysis  spelling-ok
haemodynamic hemodynamic  spelling-ok
haemoglobin hemoglobin  spelling-ok
haemolysis hemolysis  spelling-ok
haemophilia hemophilia  spelling-ok
haemostasis hemostasis  spelling-ok
haemoptysis hemoptysis  spelling-ok
haemorrhoids hemorrhoids  spelling-ok
oedema edema  spelling-ok
oedemas edemas  spelling-ok
oedematous edematous  spelling-ok
oesophagus esophagus  spelling-ok
oesophageal esophageal  spelling-ok
oesophagitis esophagitis  spelling-ok
oestrogen estrogen  spelling-ok
oestradiol estradiol  spelling-ok
foetus fetus  spelling-ok
foetuses fetuses  spelling-ok
foetal fetal  spelling-ok
caesarean cesarean  spelling-ok
caesareans cesareans  spelling-ok
anaemia anemia  spelling-ok
anaemic anemic  spelling-ok
leukaemia leukemia  spelling-ok
leukaemias leukemias  spelling-ok
septicaemia septicemia  spelling-ok
septicaemic septicemic  spelling-ok
ischaemia ischemia  spelling-ok
ischaemic ischemic  spelling-ok
hypoglycaemia hypoglycemia  spelling-ok
hyperglycaemia hyperglycemia  spelling-ok
glycaemic glycemic  spelling-ok
bacteraemia bacteremia  spelling-ok
toxaemia toxemia  spelling-ok
uraemia uremia  spelling-ok
hypoxaemia hypoxemia  spelling-ok
anaesthesia anesthesia  spelling-ok
anaesthetic anesthetic  spelling-ok
anaesthetist anesthetist  spelling-ok
diarrhoea diarrhea  spelling-ok
diarrhoeal diarrheal  spelling-ok
gonorrhoea gonorrhea  spelling-ok
dyspnoea dyspnea  spelling-ok
apnoea apnea  spelling-ok
paediatric pediatric  spelling-ok
paediatrician pediatrician  spelling-ok
orthopaedic orthopedic  spelling-ok
orthopaedist orthopedist  spelling-ok
encyclopaedia encyclopedia  spelling-ok
gynaecology gynecology  spelling-ok
gynaecologic gynecologic  spelling-ok
gynaecologist gynecologist  spelling-ok
coeliac celiac  spelling-ok
faeces feces  spelling-ok
faecal fecal  spelling-ok
aetiology etiology  spelling-ok
sulphur sulfur  spelling-ok
sulphate sulfate  spelling-ok
sulphuric sulfuric  spelling-ok
"""

# The ligatures, read as their two letters.
LIGATURE_ROWS = [
    ("manœuvre", "maneuver"),  # spelling-ok
    ("œdema", "edema"),  # spelling-ok
    ("fœtus", "fetus"),  # spelling-ok
    ("anæmia", "anemia"),  # spelling-ok
    ("Œdema", "Edema"),  # spelling-ok
]

# American words, and words that merely contain a British string, which the
# checker must leave alone. Several are inflections of an American root that
# look like a British one ("enrolled" holds a British root; "analyses" is the
# plural of "analysis"); several would be generated by a careless new stem
# ("precise" by an -ise stem "prec", "compelled" by a doubled-l stem "compel");
# and several contain a British medical segment's letters ("aerial", "Caesar",
# "Haemophilus"). Some are left out of the checker on purpose (the -ogue words,
# "burnt", "glamour"); the docstring of the checker says why.
AMERICAN = """
enrolled enrolling enrollment installed installing installment installation
installs instill fulfilled fulfilling analyses paralyses programmed programming
programmer cancellation licensed licensee license practices practiced catalog
dialogue analogue monologue prologue epilogue analog colored meter center
theater offense defense pretense behavior organize organization greyhound
Kerberos parameter diameter tour contour devour concentrate excelled
controlled compelled propelled rebelled patrolled advise revise supervised
exercise enterprise compromise surprised televised advertise precise concise
chastise comprise premise expertise acre genre massacre mediocre ogre glamour
specter caliber scepter luster lustring sabotage theatrical fibrous metric
modeled labeled travel signal channel dialed fueled panelist woolen woolly
while among toward judgment acknowledgment specialty skeptical mold molt
smolder plow draft artifact story learned aging ageism inquiry burnt dreamt
spelt rancorous vigorous humorous odorous laborious
aerial aerobic aesthetic archaeology academia Caesar coelacanth coelom
Haemophilus Haemonchus paean onomatopoeia phoenix Oedipus coefficient coed
algae larvae vertebrae formulae maestro Michael Israel amoeba hemorrhage
edema esophagus fetus feces celiac apnea sulfur estrogen pediatric anesthesia
"""

# Ordinary American lines that must stay clean: URLs and paths among them.
CLEAN = [
    "The organization analyzes behavior and favors a gray, centered layout.",
    "See https://example.org/colour/behaviour for the source.",  # spelling-ok
    "Read docs/organisation/centre.md first.",  # spelling-ok
    "Run ./colour/tool or ../behaviour/tool.",  # spelling-ok
    "It lives in /srv/colour/data on the host.",  # spelling-ok
    "Edit app/i18n/colour.json, then reload.",  # spelling-ok
]

# Prose with a slash is prose, not a path: each British word is still caught.
SLASHED_PROSE = [
    ("Pick a colour/flavour for it.", ["colour", "flavour"]),  # spelling-ok
    ("Notes on labour/delivery.", ["labour"]),  # spelling-ok
    ("the centre/periphery split", ["centre"]),  # spelling-ok
]


def rows(table: str) -> list[tuple[str, str]]:
    out = []
    for line in table.strip().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        british, american = line.split()[:2]
        out.append((british, american))
    return out


TABLE_ROWS = rows(TABLE)


def words_of(rows_: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Each row as the single words it is made of (a hyphenated row, split)."""
    out = []
    for british, american in rows_:
        for b, a in zip(british.split("-"), american.split("-"), strict=True):
            if b != a:
                out.append((b, a))
    return out


HIT = re.compile(r":(\d+):(\d+): British spelling '([^']+)' -- use '([^']+)'")


def scan(
    mod: ModuleType,
    lines: list[str],
    allow: list[tuple[str, str]] | None = None,
    name: str = "sample.md",
) -> dict:
    """Run mod.check on a file of `lines`; return {line number: [(word, fix)]}."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        problems = mod.check(path, allow or [])
    found: dict[int, list[tuple[str, str]]] = {}
    for msg in problems:
        m = HIT.search(msg)
        if m:
            found.setdefault(int(m.group(1)), []).append((m.group(3), m.group(4)))
    return found


def fixed(
    mod: ModuleType, text: str, allow: list[tuple[str, str]] | None = None
) -> str:
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
    """Every British word the checker generates, and every word of the table (the
    segment words are not generated), in every context, with its fix."""
    bad = []
    words = sorted(set(mod.BRITISH.items()) | set(words_of(TABLE_ROWS)))
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


def table(mod: ModuleType) -> list[str]:
    """Every row of the hand-written table is caught, with the American form the
    table names. A word, stem, ending, prefix or segment dropped from the checker
    leaves its row uncaught."""
    lines = [f"The {b} here." for b, _ in TABLE_ROWS]
    found = scan(mod, lines)
    missed = []
    for n, (b, a) in enumerate(TABLE_ROWS, 1):
        want = [
            (wb, wa)
            for wb, wa in zip(b.split("-"), a.split("-"), strict=True)
            if wb != wa
        ]
        if found.get(n) != want:
            missed.append(f"{b}->{found.get(n)}")
    return [f"the table is caught (missed {missed[:8]})"] if missed else []


def ligatures(mod: ModuleType) -> list[str]:
    found = scan(mod, [f"The {b} here." for b, _ in LIGATURE_ROWS])
    want = {n: [row] for n, row in enumerate(LIGATURE_ROWS, 1)}
    bad = [] if found == want else [f"ligatures are caught ({found})"]
    text = "A manœuvre and an œdema.\n"  # spelling-ok
    got = fixed(mod, text)
    if got != "A maneuver and an edema.\n":
        bad.append(f"--fix respells a ligature ({got!r})")
    return bad


def american_left_alone(mod: ModuleType) -> list[str]:
    words = AMERICAN.split()
    found = scan(mod, [f"The {w} here." for w in words] + CLEAN)
    named = {n: (words + CLEAN)[n - 1] for n in found}
    return [f"no false positives (flagged {sorted(named.items())[:5]})"] * bool(found)


def slashes_in_prose(mod: ModuleType) -> list[str]:
    found = scan(mod, [line for line, _ in SLASHED_PROSE])
    got = {n: [w for w, _ in hits] for n, hits in found.items()}
    want = {n: words for n, (_, words) in enumerate(SLASHED_PROSE, 1)}
    return [] if got == want else [f"a slash in prose is not a path ({got})"]


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


GHA = "cancelled"  # spelling-ok
PHRASE = f"the '{GHA}' state"


def allowlist(mod: ModuleType) -> list[str]:
    """An allowed phrase exempts itself, exactly as written, in the files its glob
    names, and nothing else."""
    bad = []
    allow = [("*.md", PHRASE)]
    lines = [
        f"if result == {PHRASE}:",
        f"if result == {PHRASE}: the behaviour too",  # spelling-ok
        "if result == 'cancelled':",  # spelling-ok
        "if result == the 'Cancelled' state:",  # spelling-ok
        "if result == THE 'CANCELLED' STATE:",  # spelling-ok
    ]
    found = scan(mod, lines, allow)
    british = ("behaviour", "cancelled", "Cancelled", "CANCELLED")  # spelling-ok
    want = {
        2: [(british[0], "behavior")],
        3: [(british[1], "canceled")],
        4: [(british[2], "Canceled")],
        5: [(british[3], "CANCELED")],
    }
    if found != want:
        bad.append(f"an allowed phrase exempts only itself, in its own case ({found})")

    # Scoped: allowed in a workflow, not in Markdown or Python.
    for name, scope, exempt in [
        ("ci.yml", "*.yml", True),
        ("notes.md", "*.yml", False),
        ("tool.py", ".github/workflows/*.yml", False),
        ("tool.py", "*.py", True),
    ]:
        hits = scan(mod, [f"x = {PHRASE}"], [(scope, PHRASE)], name=name)
        if bool(hits) == exempt:
            verb = "exempts" if exempt else "does not exempt"
            bad.append(f"the glob {scope!r} {verb} {name}")

    # A line with no glob is refused, not read as allowed everywhere.
    for text in [f"{GHA}()", f"'{GHA}'", f": {GHA}()", "*.yml:"]:
        try:
            mod.parse_allowlist(text)
        except ValueError:
            continue
        bad.append(f"an unscoped allowlist line is refused ({text!r})")
    try:
        parsed = mod.parse_allowlist(
            f"# a comment\n\n.github/workflows/*.yml: {GHA}()\n*.py: X\n"
        )
    except ValueError as error:
        parsed = repr(error)
    want_parsed = [
        (".github/workflows/*.yml", f"{GHA}()"),
        ("*.py", "X"),
    ]  # spelling-ok
    if parsed != want_parsed:
        bad.append(f"a scoped allowlist line is read ({parsed})")
    return bad


def unreadable(mod: ModuleType) -> list[str]:
    """A file that is not UTF-8 is reported, not passed in silence."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "latin1.md"
        path.write_bytes("The colour of café.\n".encode("latin-1"))  # spelling-ok
        problems = mod.check(path, [])
    ok = len(problems) == 1 and "UTF-8" in problems[0]
    return [] if ok else [f"a file that is not UTF-8 is reported ({problems})"]


def fixes(mod: ModuleType) -> list[str]:
    text = (
        "Behaviour, BEHAVIOUR and behaviour;\n"  # spelling-ok
        "a colourPicker and MAX_COLOURS.\n"  # spelling-ok
        "The colour stays.  <!-- spelling-ok -->\n"  # spelling-ok
        "See https://example.org/colour for it.\n"  # spelling-ok
        f"Keep {PHRASE} but fix the centre.\n"  # spelling-ok
        "Unrecognised judgements.\n"  # spelling-ok
        "Haemorrhagic oedematous foetuses.\n"  # spelling-ok
    )
    want = (
        "Behavior, BEHAVIOR and behavior;\n"
        "a colorPicker and MAX_COLORS.\n"
        "The colour stays.  <!-- spelling-ok -->\n"  # spelling-ok
        "See https://example.org/colour for it.\n"  # spelling-ok
        f"Keep {PHRASE} but fix the center.\n"
        "Unrecognized judgments.\n"
        "Hemorrhagic edematous fetuses.\n"
    )
    got = fixed(mod, text, [("*.md", PHRASE)])
    return [] if got == want else [f"--fix keeps case and exemptions ({got!r})"]


# Files of every kind the checker must read, each with a British word in it.
SCANNED = [
    "pkg/module.py",
    "app/js/50-view/10-panel.js",
    "data/table.json",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "compose.yaml",
    "Caddyfile",
    "proxy/Caddyfile",
    "proxy/Dockerfile",
    "app/i18n/en.json",
    "app/i18n/framework/en.json",
    "docs/developing.md",
    "scripts/tool.py",
    "server/schema.sql",
]
# Translations, which the checker must not judge by English spelling (#80).
NOT_SCANNED = ["app/i18n/de.json", "app/i18n/framework/fr.json"]


def scanned(mod: ModuleType) -> list[str]:
    """targets() and skip() together: which files a whole-repository run reads."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel in SCANNED + NOT_SCANNED:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            word = "colour"  # spelling-ok
            json_file = rel.endswith(".json")
            body = f'{{"note": "the {word}"}}\n' if json_file else f"# the {word}\n"
            path.write_text(body, encoding="utf-8")
        saved = mod.ROOT
        mod.ROOT = root
        try:
            reported = {
                str(p.relative_to(root))
                for p in mod.targets([])
                if not mod.skip(p) and mod.check(p, [])
            }
        finally:
            mod.ROOT = saved
    bad = []
    missed = [rel for rel in SCANNED if rel not in reported]
    if missed:
        bad.append(f"every kind of file is read (missed {missed})")
    judged = [rel for rel in NOT_SCANNED if rel in reported]
    if judged:
        bad.append(f"a translation is not judged by English spelling ({judged})")
    return bad


# Real files of ours, which must never be skipped.
REAL = [
    "app/js/00-core/00-util.js",
    "app/i18n/en.json",
    "docs/developing.md",
    "scripts/check_enums.py",
    "proxy/Caddyfile",
    "compose.yaml",
    ".github/workflows/test.yml",
    "tests/test_check_spelling.py",
]


def real_files_read(mod: ModuleType) -> list[str]:
    skipped = [rel for rel in REAL if mod.skip(ROOT / rel)]
    return [f"our own files are not skipped ({skipped})"] if skipped else []


PROPERTIES = [
    every_word,
    table,
    ligatures,
    american_left_alone,
    slashes_in_prose,
    case_folding,
    spelling_ok,
    allowlist,
    unreadable,
    fixes,
    scanned,
    real_files_read,
]


def run_properties(mod: ModuleType) -> list[str]:
    return [problem for prop in PROPERTIES for problem in prop(mod)]


# ---------------------------------------------------------------------------
# The sections run against the real checker.
# ---------------------------------------------------------------------------


def decompositions(mod: ModuleType, word: str) -> list[tuple[str, str, str, str]]:
    """Every (family, prefix, stem, ending) that generates `word`."""
    out = []
    for family, (endings, prefixes, stems) in mod.FAMILIES.items():
        for prefix in prefixes:
            for stem in stems:
                for ending_b, _ in endings:
                    if prefix + stem + ending_b == word:
                        out.append((family, prefix, stem, ending_b))
    return out


def coverage() -> None:
    """The table is an independent account of the checker, so it must name every
    part of it. These read the checker's lists only to ask whether the table
    covers them; whether each row is caught is the table property's job."""
    print("The table covers every part of the checker")
    british = [w for w, _ in words_of(TABLE_ROWS)]
    explicit = {b for b, _ in TABLE_ROWS if b in cs.EXPLICIT}
    check(
        "every EXPLICIT word is in the table",
        explicit == set(cs.EXPLICIT),
        str(sorted(set(cs.EXPLICIT) - explicit)),
    )
    wrong = [b for b, a in TABLE_ROWS if b in cs.EXPLICIT and cs.EXPLICIT[b] != a]
    check("and the table agrees with EXPLICIT on each", not wrong, str(wrong))

    parts = [d for w in british for d in decompositions(cs, w)]
    for family, (endings, prefixes, stems) in cs.FAMILIES.items():
        used = [d for d in parts if d[0] == family]
        missing = [s for s in stems if s not in {d[2] for d in used}]
        check(f"{family}: a form of every stem", not missing, str(missing))
        missing = [e for e, _ in endings if e not in {d[3] for d in used}]
        check(f"{family}: a form of every ending", not missing, str(missing))
        missing = [p for p in prefixes if p not in {d[1] for d in used}]
        check(f"{family}: a form of every prefix", not missing, str(missing))
    missing = [b for b, _ in cs.SEGMENTS if not any(b in w for w in british)]
    check("a form of every segment", not missing, str(missing))

    redundant = [
        w
        for w in cs.EXPLICIT
        if w in cs.generate(cs.FAMILIES, {}) or any(b in w for b, _ in cs.SEGMENTS)
    ]
    check(
        "no EXPLICIT word is also generated, so dropping one is noticed",
        not redundant,
        str(redundant),
    )


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
    check("the allowlist is skipped", cs.skip(ROOT / ".spelling-allow"))
    check(
        "its neighbor is checked: .spelling-allow.md",
        not cs.skip(ROOT / ".spelling-allow.md"),
    )
    check("this test is not skipped", not cs.skip(Path(__file__)))
    check(
        "a file outside the repository is checked",
        not cs.skip(Path(tempfile.gettempdir()) / "x.md"),
    )
    whole = {str(p.relative_to(ROOT)) for p in cs.targets([])}
    missing = [rel for rel in REAL if rel not in whole]
    check("a whole-repository run reads our own files", not missing, str(missing))
    problems = cs.check(Path(__file__), cs.load_allowlist())
    check("this test file passes its own checker", not problems, str(problems[:2]))


def command_line() -> None:
    print("The command")
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.md"
        good = Path(tmp) / "good.md"
        latin = Path(tmp) / "latin1.md"
        bad.write_text("Our judgements.\n", encoding="utf-8")  # spelling-ok
        good.write_text("Our judgments.\n", encoding="utf-8")
        latin.write_bytes("Our café.\n".encode("latin-1"))

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
        unread = run(str(latin))
        check(
            "a file that is not UTF-8 exits nonzero, and says so",
            unread.returncode == 1 and "UTF-8" in unread.stderr,
            unread.stderr,
        )
        unfixed = run("--fix", str(latin))
        check("--fix on a file it cannot read exits nonzero", unfixed.returncode == 1)
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
    ("'aluminium' is dropped", '"aluminium": "aluminum",', ""),  # spelling-ok
    ("'whilst' is dropped", '"whilst": "while",', ""),  # spelling-ok
    ("'ageing' is dropped", '"ageing": "aging",', ""),  # spelling-ok
    ("'oesophagus' is dropped", '("oesoph", "esoph"),', ""),  # spelling-ok
    ("'haemorrhage' is dropped (its segment)", '("haem", "hem"),', ""),  # spelling-ok
    ("the -aemia segment is dropped", '("aemi", "emi"),', ""),  # spelling-ok
    ("the -yse stem 'catal' is dropped", '"catal", ', ""),
    ("the -ise stem 'immun' is dropped", '"immun",', ""),
    ("the -our stem 'ferv' is dropped", '"ferv",', ""),
    ("the -re stem 'scept' is dropped", '"scept",', ""),
    ("the ending -ourise is dropped", '("ourise", "orize"),', ""),  # spelling-ok
    (
        "the ending -isational is dropped",
        '("isational", "izational"),',
        "",
    ),  # spelling-ok
    ("the ending -llist is dropped", '("list", "ist"),', ""),
    ("the -ce prefix 'sub' is dropped", '("", "sub"),', '("",),'),
    (
        "a segment's ending is not respelled",
        "return BRITISH.get(respelled, respelled)",
        "return respelled",
    ),
    ("a genus is respelled", "if key.startswith(GENERA):", "if False:"),
    # A new stem that generates an American word must be noticed.
    ("the -ise stem 'prec' is added", '"priorit",', '"priorit", "prec",'),
    ("the -ll stem 'compel' is added", '"counsel",', '"counsel", "compel",'),
    ("the -re stem 'lust' is added", '"lit",', '"lit", "lust",'),
    ("case folding is off", "key = word.lower().translate", "key = word.translate"),
    (
        "ligatures are not read",
        "key = word.lower().translate(LIGATURES)",
        "key = word.lower()",
    ),
    (
        "ligatures are not letters",
        'WORD = re.compile(r"[A-ZŒÆ]+(?![a-zœæ])|[A-ZŒÆ]?[a-zœæ]+")',
        'WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")',
    ),
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
        "an allowed phrase matches in any case",
        'scannable = scannable.replace(phrase, " " * len(phrase))',
        "scannable = re.sub(re.escape(phrase), blank, scannable, flags=re.I)",
    ),
    (
        "an allowlist glob is ignored",
        "for glob, phrase in allow if where.match(glob)]",
        "for glob, phrase in allow]",
    ),
    (
        "an unscoped allowlist line is accepted",
        "if not sep or not glob or not phrase.strip():",
        "if False:",
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
    ("URLs are not blanked", "scannable = blank_urls(scannable)", "pass"),
    (
        "any run with a slash is a path",
        'if path.startswith(("./", "../", "/")) or any(',
        "if True or any(",
    ),
    (
        "a file that is not UTF-8 is passed in silence",
        "except UnicodeDecodeError as error:\n        return [",
        "except UnicodeDecodeError as error:\n        return [] if True else [",
    ),
    ("--fix ignores case", "return american.upper()", "return american"),
    ("'.js' is not read", '".js",', ""),
    ("'.py' is not read", '".py",', ""),
    (
        "a Caddyfile is not read",
        'CHECK_NAMES = {"Caddyfile", "Dockerfile", "Makefile"}',
        'CHECK_NAMES = {"Dockerfile", "Makefile"}',
    ),
    ("app/ is a SKIP_DIRS directory", '"backups",', '"backups", "app",'),
    (
        "docs/developing.md is quoted verbatim",
        '"docs/app/index.html",',
        '"docs/app/index.html", "docs/developing.md",',
    ),
    (
        "en.json is treated as a translation",
        '\n        and parts[2] != f"{Locale.EN}.json"',
        "",
    ),
]


def run_mutant(n: int) -> tuple[list[str], str]:
    """The problems the properties find in mutant `n`, or the error it raised."""
    _, old, new = MUTATIONS[n]
    source = SCRIPT.read_text(encoding="utf-8")
    mutant = load(source.replace(old, new), name=f"check_spelling_mutant_{n}")
    try:
        return run_properties(mutant), ""
    except Exception as error:  # a crash is not a mutation worth the name
        return [], repr(error)


def mutations() -> None:
    print("Mutation tests: a broken checker is noticed")
    source = SCRIPT.read_text(encoding="utf-8")
    applies = [source.count(old) == 1 for _, old, _ in MUTATIONS]
    for (what, old, _), present in zip(MUTATIONS, applies, strict=True):
        check(f"mutation applies once: {what}", present, f"{old!r} not once")
    # Each mutant runs every property over every word, so they run in parallel.
    todo = [n for n, present in enumerate(applies) if present]
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(run_mutant, todo))
    for n, (problems, error) in zip(todo, results, strict=True):
        what = MUTATIONS[n][0]
        if error:
            check(f"the mutant runs: {what}", False, error)
            continue
        check(f"noticed: {what}", bool(problems), "every property still passed")

    mutant = load(
        source.replace("rel in QUOTED_VERBATIM or ", ""), "check_spelling_mutant_q"
    )
    quoted = sorted(cs.QUOTED_VERBATIM)[0]
    check("the real checker skips a quoted file", cs.skip(ROOT / quoted))
    check("noticed: QUOTED_VERBATIM ignored", not mutant.skip(ROOT / quoted))
    mutant = load(
        source.replace("if resolved == SELF:", "if False:"),
        "check_spelling_mutant_s",
    )
    check(
        "noticed: the checker no longer skips itself",
        not mutant.skip(mutant.SELF),
    )
    mutant = load(
        source.replace("if resolved == ALLOWLIST.resolve():", "if False:"),
        "check_spelling_mutant_a",
    )
    check(
        "noticed: the allowlist is no longer skipped",
        not mutant.skip(ROOT / ".spelling-allow"),
    )


def main() -> int:
    real_checker()
    coverage()
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
