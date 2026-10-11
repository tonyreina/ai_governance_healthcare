#!/usr/bin/env python3
"""docs/crosswalk.md agrees with OPTICA's framework definition (#174, D-84).

The crosswalk page is the reviewed OPTICA-to-CHAI mapping; OPTICA's definition
(app/frameworks/optica/framework.json) is what the dashboard's "covered by CHAI"
chips and the generated OPTICA checklist are drawn from. The two disagreed for
months (#174), because nothing connected them. This script connects them:

* It writes the page's item-by-item table (between the two markers below) from
  the definition, so the per-item view on the page *is* the definition.
* With ``--check`` it also reads every count, list and named correction the
  page's prose states (the headline relations, the CHAI criteria cited and never
  cited, the per-stage and per-chapter tables, the corrections applied and
  rejected, the producer split, the relay of completion stages) and recomputes
  each from the definition. A sentence that no longer says what the checker
  reads is a failure too, so rewording a claim means updating its check.

Items the page marks as reviewed but "not yet recorded" in the definition (its
section 7 says which) are read as the page states their relation; the definition
must still hold them as OPTICA-only with no criteria, so recording them means
removing them from that sentence. Counts that depend on their unknown criteria
are checked as a lower bound only.

    pixi run gen-crosswalk      # rewrite the table
    pixi run check-crosswalk    # the table is current and every claim holds
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from framework_enums import CrossRefRelation

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "crosswalk.md"
OPTICA = ROOT / "app" / "frameworks" / "optica" / "framework.json"
CHAI = ROOT / "app" / "frameworks" / "chai" / "framework.json"
OPTICA_DOCS = ROOT / "app" / "frameworks" / "optica" / "docs.toml"

BEGIN = (
    "<!-- Generated from app/frameworks/optica/framework.json by"
    " scripts/gen_crosswalk.py (pixi run gen-crosswalk). Do not edit by hand. -->"
)
END = "<!-- End of the generated table. -->"
DASH = "—"


class Who(StrEnum):
    """Who can answer an OPTICA item: the values of its definition's ``whos``."""

    ADOPTER = "adopter"
    DEVELOPER = "developer"
    EITHER = "either"


RELATION_LABEL = {
    CrossRefRelation.EQUIVALENT: "equivalent",
    CrossRefRelation.PARTIAL: "partial",
    CrossRefRelation.OPTICA_ONLY: "OPTICA-only",
}

# A table's totals row: "Total items" or "Total".
TOTAL_ROW = re.compile(r"total(?: items)?", re.IGNORECASE)

# How the producer table on the page names each party.
PRODUCER_ROW = (
    ("vendor", Who.DEVELOPER),
    ("adopting", Who.ADOPTER),
    ("either", Who.EITHER),
)

NUMBER_WORDS = {
    word: n
    for n, word in enumerate(
        re.split(
            r"\s+",
            "zero one two three four five six seven eight nine ten eleven twelve"
            " thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
            " twenty-one twenty-two twenty-three",
        )
    )
}


@dataclass(frozen=True)
class Item:
    num: str
    chapter: int
    who: Who
    stakeholder: str
    stage: str
    relation: CrossRefRelation
    ids: tuple[str, ...]


def load_items(optica: dict) -> dict[str, Item]:
    items = {}
    for section in optica["sections"]:
        for raw in section["items"]:
            refs = raw.get("crossRefs") or {}
            items[raw["num"]] = Item(
                num=raw["num"],
                chapter=int(section["n"]),
                who=Who(raw["who"]),
                stakeholder=raw["attrs"]["stakeholder"],
                stage=raw["attrs"]["stage"],
                relation=CrossRefRelation(refs.get("relation", "optica-only")),
                ids=tuple(refs.get("ids", ())),
            )
    return items


def chai_stages(chai: dict) -> dict[str, list[str]]:
    """CHAI's stages ("s1") and the criteria in each, in order."""
    return {s["id"]: [i["id"] for i in s["items"]] for s in chai["sections"]}


# --- the generated table ------------------------------------------------------


def render_table(items: dict[str, Item]) -> str:
    rows = [
        "| Item | Who answers | Relation to CHAI | CHAI criteria |",
        "| ---- | ----------- | ---------------- | ------------- |",
    ]
    for it in items.values():
        ids = ", ".join(it.ids) or DASH
        rows.append(f"| {it.num} | {it.who} | {RELATION_LABEL[it.relation]} | {ids} |")
    return "\n".join(rows)


class PageError(ValueError):
    """The page has lost the markers the table is written between."""


def _bounds(page: str) -> tuple[int, int]:
    start, end = page.find(BEGIN), page.find(END)
    if start < 0 or end < start or page.count(BEGIN) != 1 or page.count(END) != 1:
        raise PageError(
            "docs/crosswalk.md must hold the generated table between exactly one"
            f" pair of markers:\n  {BEGIN}\n  {END}"
        )
    return start + len(BEGIN), end


def table_region(page: str) -> str:
    start, end = _bounds(page)
    return page[start:end].strip("\n")


def splice(page: str, table: str) -> str:
    start, end = _bounds(page)
    return page[:start] + "\n\n" + table + "\n\n" + page[end:]


# --- reading the page's claims -------------------------------------------------


def number(word: str) -> int:
    word = word.strip("*").lower()
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


def item_nums(text: str) -> list[str]:
    """Item numbers in prose: "1.1, 9.3 and 12.1", "10.5-10.7"."""
    out: list[str] = []
    for m in re.finditer(r"(\d+)\.(\d+)(?:-(\d+)\.(\d+))?", text):
        if m.group(3):
            if m.group(1) != m.group(3):
                raise ValueError(f"a range across chapters: {m.group(0)}")
            first, last = int(m.group(2)), int(m.group(4))
            out += [f"{m.group(1)}.{k}" for k in range(first, last + 1)]
        else:
            out.append(f"{m.group(1)}.{m.group(2)}")
    return out


def criterion_ids(text: str) -> list[str]:
    return re.findall(r"s\d-\d", text)


def section_text(page: str, number_: str) -> str:
    """The body of "## <number_>. ..." up to the next level-two heading."""
    m = re.search(
        rf"^## {re.escape(number_)}\. .*?$(.*?)(?=^## |\Z)", page, re.M | re.S
    )
    return m.group(1) if m else ""


def table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        rows.append([c.strip().strip("*").strip() for c in line.strip("|").split("|")])
    return rows


def flat(text: str) -> str:
    return " ".join(text.split())


class Report:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def expect(self, what: str, claimed: object, actual: object) -> None:
        if claimed != actual:
            self.problems.append(
                f"{what}: the page says {claimed}, the definition gives {actual}"
            )

    def find(self, pattern: str, text: str, what: str) -> re.Match[str] | None:
        m = re.search(pattern, text)
        if m is None:
            self.problems.append(
                f"the page no longer states {what} in the form the checker reads"
                " (update scripts/gen_crosswalk.py with the new wording)"
            )
        return m


def check(page: str, optica: dict, chai: dict, optica_docs: str = "") -> list[str]:
    """Every problem with the page against the definitions; empty means agreed."""
    r = Report()
    recorded = load_items(optica)
    stages = chai_stages(chai)
    criteria = [c for ids in stages.values() for c in ids]
    text = flat(page)

    # The generated table is the definition, byte for byte.
    try:
        if table_region(page) != render_table(recorded):
            r.problems.append(
                "the item-by-item table is stale: run `pixi run gen-crosswalk`"
            )
    except PageError as exc:
        r.problems.append(str(exc))

    # Items reviewed on the page but not yet recorded in the definition.
    pending: set[str] = set()
    m = r.find(
        r"not yet recorded there: (.+?) are partial on this page",
        text,
        "which reviewed items are not yet recorded in the definition",
    )
    if m:
        pending = set(item_nums(m.group(1)))
        for num in sorted(pending):
            it = recorded.get(num)
            if it is None:
                r.problems.append(f"{num} is named as not yet recorded, and is no item")
            elif it.relation is not CrossRefRelation.OPTICA_ONLY or it.ids:
                r.problems.append(
                    f"{num} is named as not yet recorded, but the definition records"
                    f" it ({it.relation}, {list(it.ids)}): remove it from that sentence"
                )
    items = {
        num: replace(it, relation=CrossRefRelation.PARTIAL) if num in pending else it
        for num, it in recorded.items()
    }

    total = len(items)
    relations = Counter(it.relation for it in items.values())
    cited = {c for it in items.values() for c in it.ids}
    only = {n for n, it in items.items() if it.relation is CrossRefRelation.OPTICA_ONLY}
    chapters = sorted({it.chapter for it in items.values()})
    dev = {n for n, it in items.items() if it.who is Who.DEVELOPER}

    def citing(criterion: str) -> set[str]:
        return {n for n, it in items.items() if criterion in it.ids}

    def relation_of(label: str) -> CrossRefRelation:
        return CrossRefRelation(label.lower())

    # The opening paragraph.
    if m := r.find(
        r"OPTICA checklist \((\d+) items in (\d+) chapters", text, "the item count"
    ):
        r.expect("OPTICA items", int(m.group(1)), total)
        r.expect("OPTICA chapters", int(m.group(2)), len(chapters))
    if m := r.find(
        r"CHAI assurance criteria \((\d+) criteria across (\w+) lifecycle stages",
        text,
        "the CHAI criterion count",
    ):
        r.expect("CHAI criteria", int(m.group(1)), len(criteria))
        r.expect("CHAI stages", number(m.group(2)), len(stages))

    # 1. Headline numbers: the "Corrected" column.
    seen: set[CrossRefRelation] = set()
    for row in table_rows(section_text(page, "1"))[1:]:
        if len(row) != 3:
            continue
        label, corrected = row[0], row[1].strip("*")
        if TOTAL_ROW.fullmatch(label):
            r.expect("headline total", int(corrected), total)
            continue
        if label.lower() in set(CrossRefRelation):
            rel = relation_of(label)
            seen.add(rel)
            r.expect(f"headline {label}", int(corrected), relations[rel])
    for rel in CrossRefRelation:
        if rel not in seen:
            r.problems.append(f"the headline table has no row for {rel}")
    if "**There are no equivalences left.**" in text:
        r.expect("equivalences", 0, relations[CrossRefRelation.EQUIVALENT])

    if m := r.find(
        r"(\d+) of (\d+) criteria are cited somewhere in the corrected crosswalk"
        r" \((\d+\.\d)%\)",
        text,
        "how many CHAI criteria are cited",
    ):
        r.expect("criteria cited", int(m.group(1)), len(cited))
        r.expect("criteria in all", int(m.group(2)), len(criteria))
        r.expect("share cited", m.group(3), f"{100 * len(cited) / len(criteria):.1f}")
    if m := r.find(
        r"(\w+) criteria are never cited: \*\*(.+?)\*\*",
        text,
        "the criteria never cited",
    ):
        never = criterion_ids(m.group(2))
        r.expect("criteria never cited", sorted(never), sorted(set(criteria) - cited))
        r.expect("count of criteria never cited", number(m.group(1)), len(never))

    # The effective-coverage table: n and Cited per CHAI stage.
    for row in table_rows(section_text(page, "1")):
        if len(row) == 6 and re.match(r"s\d ", row[0]):
            stage = row[0].split()[0]
            ids = stages.get(stage, [])
            r.expect(f"criteria in {stage}", int(row[1]), len(ids))
            r.expect(f"criteria cited in {stage}", int(row[2]), len(cited & set(ids)))
        elif len(row) == 6 and TOTAL_ROW.fullmatch(row[0]):
            r.expect("criteria in the stage table", int(row[1]), len(criteria))
            r.expect("criteria cited in the stage table", int(row[2]), len(cited))

    # Corrections applied.
    if m := r.find(
        r"(\w+) relation relabels \((.+?)\), plus (\d+\.\d+) retained as (\S+?) ",
        text,
        "the relation relabels",
    ):
        relabeled = 0
        for part in m.group(2).split("; "):
            g = re.fullmatch(r"(.+?) (?:down|up) from (\S+) to (\S+)", part)
            if g is None:
                r.problems.append(f"a relabel the checker cannot read: {part!r}")
                continue
            for num in item_nums(g.group(1)):
                relabeled += 1
                r.expect(
                    f"relation of {num}",
                    g.group(3),
                    RELATION_LABEL[items[num].relation],
                )
        r.expect("relabels", number(m.group(1)), relabeled)
        r.expect(
            f"relation of {m.group(3)}",
            m.group(4),
            RELATION_LABEL[items[m.group(3)].relation],
        )
    if m := r.find(r"(\w+) citation fixes \((.+?)\)\.", text, "the citation fixes"):
        fixes = 0
        for signed, where in re.findall(
            r"((?:[+-]s\d-\d(?: and )?)+) at ((?:\d+\.\d+(?: and )?)+)", m.group(2)
        ):
            for sign, criterion in re.findall(r"([+-])(s\d-\d)", signed):
                for num in item_nums(where):
                    fixes += 1
                    r.expect(
                        f"{sign}{criterion} at {num}",
                        sign == "+",
                        criterion in items[num].ids,
                    )
        r.expect("citation fixes", number(m.group(1)), fixes)
    if m := r.find(
        r"(\w+) producer reassignments \((.+?) from (\w+) to (\w+)\)",
        text,
        "the producer reassignments",
    ):
        moved = item_nums(m.group(2))
        r.expect("producer reassignments", number(m.group(1)), len(moved))
        for num in moved:
            r.expect(f"who answers {num}", m.group(4), items[num].who)

    # Corrections rejected, and the extensions.
    for m in re.finditer(r"(\d+\.\d+) stays partial", text):
        r.expect(
            f"relation of {m.group(1)}",
            RELATION_LABEL[CrossRefRelation.PARTIAL],
            RELATION_LABEL[items[m.group(1)].relation],
        )
    if m := r.find(
        r"(\d+\.\d+) therefore remains partial on (s\d-\d) alone",
        text,
        "7.1's one anchor",
    ):
        it = items[m.group(1)]
        r.expect(f"criteria of {it.num}", [m.group(2)], list(it.ids))
        r.expect(
            f"relation of {it.num}",
            RELATION_LABEL[CrossRefRelation.PARTIAL],
            RELATION_LABEL[it.relation],
        )
    for m in re.finditer(r"why (\d+\.\d+) does become OPTICA-only", text):
        r.expect(
            f"relation of {m.group(1)}",
            RELATION_LABEL[CrossRefRelation.OPTICA_ONLY],
            RELATION_LABEL[items[m.group(1)].relation],
        )
    for m in re.finditer(r"\*(s\d-\d) at (\d+\.\d+): rejected\.\*", text):
        r.expect(
            f"{m.group(1)} at {m.group(2)}", False, m.group(1) in items[m.group(2)].ids
        )
    if m := r.find(
        r"(s\d-\d) is carried by (.+?) only\.", text, "which items carry s3-7"
    ):
        r.expect(
            f"items citing {m.group(1)}",
            sorted(item_nums(m.group(2))),
            sorted(citing(m.group(1))),
        )
    if m := r.find(
        r"OPTICA (\d+\.\d+(?:,? (?:and )?\d+\.\d+)*) are moved from (\w+) to role-dual",
        text,
        "the role-dual extension",
    ):
        for num in item_nums(m.group(1)):
            r.expect(f"who answers {num}", Who.EITHER, items[num].who)
    if m := r.find(r"(s\d-\d) is added to (\d+\.\d+)", text, "the s2-7 extension"):
        r.expect(
            f"{m.group(1)} at {m.group(2)}", True, m.group(1) in items[m.group(2)].ids
        )
    if r.find(
        r"the producer column becomes a pure function of OPTICA's own stakeholder"
        r" assignment",
        text,
        "that who answers follows from the stakeholder",
    ):
        whos: dict[str, set[Who]] = {}
        for it in items.values():
            whos.setdefault(it.stakeholder, set()).add(it.who)
        for stakeholder, found in sorted(whos.items()):
            r.expect(f"who answers for the {stakeholder}", 1, len(found))

    # 2. Chapter by chapter.
    rows = [row for row in table_rows(section_text(page, "2")) if row[0].isdigit()]
    r.expect("chapters in the chapter table", [int(row[0]) for row in rows], chapters)
    for row in rows:
        if len(row) != 7:
            r.problems.append(f"a chapter row the checker cannot read: {row}")
            continue
        ch = int(row[0])
        mine = [it for it in items.values() if it.chapter == ch]
        ids = {c for it in mine for c in it.ids}
        r.expect(f"items in chapter {ch}", int(row[2]), len(mine))
        r.expect(
            f"CHAI stages of chapter {ch}",
            sorted(row[3].replace(";", " ").split()),
            sorted({c.split("-")[0] for c in ids}),
        )
        if any(it.num in pending for it in mine):
            # Their criteria are not recorded, so the definition's count is a floor.
            if int(row[4]) < len(ids):
                r.expect(f"criteria in chapter {ch} (at least)", int(row[4]), len(ids))
        else:
            r.expect(f"criteria in chapter {ch}", int(row[4]), len(ids))
        none = sum(it.relation is CrossRefRelation.OPTICA_ONLY for it in mine)
        r.expect(f"unanchored items in chapter {ch}", int(row[5]), none)
    if m := r.find(
        r"\*\*Chapters ([\d, and]+?) are where OPTICA is effectively alone\.\*\*"
        r" (\w+) of OPTICA's (\d+) unanchored items sit in these four chapters.*?"
        r" The other (\w+) are scattered through chapters (.+?)\.",
        text,
        "where the unanchored items sit",
    ):
        alone = {int(c) for c in re.findall(r"\d+", m.group(1))}
        rest = {int(c) for c in re.findall(r"\d+", m.group(5))}
        r.expect("unanchored items", int(m.group(3)), len(only))
        r.expect(
            "unanchored items in those four chapters",
            number(m.group(2)),
            sum(items[n].chapter in alone for n in only),
        )
        r.expect(
            "the other chapters' unanchored items",
            number(m.group(4)),
            sum(items[n].chapter in rest for n in only),
        )
        r.expect(
            "chapters holding unanchored items",
            sorted(alone | rest),
            sorted({items[n].chapter for n in only}),
        )

    # 3. What OPTICA asks that CHAI never does.
    alone_text = flat(section_text(page, "3").split("**What CHAI asks")[0])
    if m := r.find(r"\((\d+) items, grouped\)", alone_text, "the OPTICA-only count"):
        r.expect("OPTICA-only items listed", int(m.group(1)), len(only))
    grouped = [
        num
        for group in re.findall(r"\*[^*]+\* \(([\d., ]+)\)", alone_text)
        for num in item_nums(group)
    ]
    r.expect("OPTICA-only items in the groups", sorted(grouped), sorted(only))
    r.expect(
        "items listed twice in the groups",
        [],
        sorted(n for n, k in Counter(grouped).items() if k > 1),
    )

    # 4. The producer split.
    who_count = Counter(it.who for it in items.values())
    producer_rows = 0
    for row in table_rows(section_text(page, "4"))[1:]:
        if len(row) != 3:
            continue
        for word, who in PRODUCER_ROW:
            if word in row[0].lower():
                producer_rows += 1
                r.expect(f"items answered by {who}", int(row[1]), who_count[who])
                r.expect(
                    f"share answered by {who}",
                    row[2],
                    f"{round(100 * who_count[who] / total)}%",
                )
                break
    r.expect("rows in the producer table", len(PRODUCER_ROW), producer_rows)
    if m := r.find(
        r"all (\d+) items at completion stage (\w) are assigned to the AI solution"
        r" developer",
        text,
        "the developer's stage",
    ):
        at_stage = [it for it in items.values() if it.stage == m.group(2)]
        r.expect(f"items at stage {m.group(2)}", int(m.group(1)), len(at_stage))
        r.expect(
            f"stage {m.group(2)} items not answered by the developer",
            [],
            [it.num for it in at_stage if it.who is not Who.DEVELOPER],
        )
    if m := r.find(
        r"the (\w+) MLOps-expert items \((.+?)\)", text, "the role-dual items"
    ):
        dual = item_nums(m.group(2))
        r.expect("role-dual items", number(m.group(1)), len(dual))
        r.expect(
            "items either party answers",
            sorted(dual),
            sorted(n for n, it in items.items() if it.who is Who.EITHER),
        )
    if m := r.find(
        r"\*\*(\w+) of the (\d+) vendor items have no CHAI anchor at all\*\* \((.+?)\)",
        text,
        "the vendor items with no anchor",
    ):
        listed = item_nums(m.group(3))
        r.expect("vendor items", int(m.group(2)), len(dev))
        r.expect("vendor items with no anchor", number(m.group(1)), len(listed))
        r.expect(
            "which vendor items have no anchor", sorted(listed), sorted(dev & only)
        )
    vendor_only = sorted(c for c in cited if citing(c) <= dev)
    adopter_only = sorted(c for c in cited if not citing(c) & dev)
    if m := r.find(
        r"only through items the vendor alone can answer\*\*: (.+?)\. (\S+) are"
        r" reachable only through items on the adopting side, including the"
        r" role-dual MLOps ones, and (\w+) through both",
        text,
        "which criteria only one party can reach",
    ):
        routes = re.findall(r"(s\d-\d) \(via (.+?)\)", m.group(1))
        r.expect(
            "criteria only the vendor reaches",
            sorted(c for c, _ in routes),
            vendor_only,
        )
        for criterion, via in routes:
            r.expect(
                f"items citing {criterion}",
                sorted(item_nums(via)),
                sorted(citing(criterion)),
            )
        r.expect(
            "criteria only the adopting side reaches",
            number(m.group(2)),
            len(adopter_only),
        )
        r.expect(
            "criteria both reach",
            number(m.group(3)),
            len(cited) - len(vendor_only) - len(adopter_only),
        )

    # 5. The relay of completion stages, and the most-cited criterion.
    order = sorted({it.stage for it in items.values()})
    if m := r.find(
        r"OPTICA's (\w+) completion stages are not a lifecycle", text, "the stage count"
    ):
        r.expect("completion stages", number(m.group(1)), len(order))
    if m := r.find(
        r"relay that orders \*who answers next\* - (.+?)\. The two", text, "the relay"
    ):
        r.expect(
            "items per completion stage",
            [int(n) for n in re.findall(r"\((\d+)(?: items)?\)", m.group(1))],
            [sum(it.stage == s for it in items.values()) for s in order],
        )
    if m := r.find(
        r"most-cited criterion of all, (s\d-\d), is anchored by (\w+) OPTICA items"
        r" spread across stages (.+?)\.",
        text,
        "the most-cited criterion",
    ):
        counts = Counter(c for it in items.values() for c in it.ids)
        top = max(counts.values())
        r.expect(
            "the most-cited criterion",
            [m.group(1)],
            sorted(c for c, k in counts.items() if k == top),
        )
        r.expect(f"items citing {m.group(1)}", number(m.group(2)), counts[m.group(1)])
        r.expect(
            f"stages citing {m.group(1)}",
            sorted(re.findall(r"\b[A-G]\b", m.group(3))),
            sorted({items[n].stage for n in citing(m.group(1))}),
        )

    # 6. The verdict.
    if m := r.find(
        r"With (\w+) equivalences across (\d+) items", text, "the equivalence count"
    ):
        r.expect(
            "equivalences", number(m.group(1)), relations[CrossRefRelation.EQUIVALENT]
        )
        r.expect("items", int(m.group(2)), total)
    if m := r.find(
        r"expect to obtain (\d+) answers from the vendor, of which (\w+) correspond to"
        r" nothing CHAI ever asked for, and to write (\d+) OPTICA items",
        text,
        "what a CHAI shop must add",
    ):
        r.expect("answers from the vendor", int(m.group(1)), len(dev))
        r.expect(
            "vendor answers with no CHAI anchor", number(m.group(2)), len(dev & only)
        )
        r.expect("OPTICA items with no CHAI source", int(m.group(3)), len(only))

    # The generated OPTICA checklist's own words (its docs.toml).
    if "There are no *equivalent* rows" in optica_docs:
        r.expect(
            "equivalent rows (app/frameworks/optica/docs.toml)",
            0,
            Counter(it.relation for it in recorded.values())[
                CrossRefRelation.EQUIVALENT
            ],
        )
    return r.problems


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail if the table is stale or any claim disagrees",
    )
    args = parser.parse_args(argv)
    page = PAGE.read_text(encoding="utf-8")
    optica = read_json(OPTICA)
    if args.check:
        problems = check(
            page, optica, read_json(CHAI), OPTICA_DOCS.read_text(encoding="utf-8")
        )
        for problem in problems:
            print(f"docs/crosswalk.md: {problem}", file=sys.stderr)
        if problems:
            return 1
        print("docs/crosswalk.md agrees with OPTICA's definition")
        return 0
    try:
        fresh = splice(page, render_table(load_items(optica)))
    except PageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if fresh != page:
        PAGE.write_text(fresh, encoding="utf-8")
        print("wrote docs/crosswalk.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
