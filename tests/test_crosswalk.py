#!/usr/bin/env python3
"""docs/crosswalk.md and OPTICA's framework definition cannot disagree (#174, D-84).

The crosswalk page described the corrected mapping (0 equivalent, 61 partial,
16 OPTICA-only, 36 CHAI criteria cited) while the definition the dashboard and
the generated OPTICA checklist are drawn from still held the earlier pass (3
equivalent, 60 partial, 14 OPTICA-only, 35 cited). Nothing connected the two.
scripts/gen_crosswalk.py now writes the page's item table from the definition
and checks every count and correction the page states against it. This suite:

* runs the check on the committed page and definitions, and finds nothing;
* shows the check finding the original #174 disagreement: the page against the
  definition as it was before the fix;
* breaks the definition one way at a time (one relation, one criterion id, one
  "who answers", an equivalence back, a "not yet recorded" item recorded) and
  demands the check notice, both with the table left stale and with the table
  regenerated, so a regenerated table cannot hide a broken claim;
* breaks the page one way at a time (a headline count, an id in the table, the
  never-cited list, a citation fix, a reworded claim, the markers, the "not yet
  recorded" sentence) and demands the check notice;
* checks the Who enum the checker reads matches the definition's own ``whos``;
* checks the pre-commit hook runs the check when the page, the definitions or
  the checker change, and that ``gen-docs`` rewrites the table.

No browser, database or Docker: nothing here can skip.

    pixi run test-crosswalk
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "gen_crosswalk", ROOT / "scripts" / "gen_crosswalk.py"
)
gen = importlib.util.module_from_spec(spec)
sys.modules["gen_crosswalk"] = gen
spec.loader.exec_module(gen)

PAGE = gen.PAGE.read_text(encoding="utf-8")
OPTICA = json.loads(gen.OPTICA.read_text(encoding="utf-8"))
CHAI = json.loads(gen.CHAI.read_text(encoding="utf-8"))
OPTICA_DOCS = gen.OPTICA_DOCS.read_text(encoding="utf-8")
PRECOMMIT = ROOT / ".pre-commit-config.yaml"
PIXI = ROOT / "pixi.toml"
# Each item's crossRefs and who answers as the definition held them before #174
# was fixed (commit 255136b): the earlier pass the page had already corrected.
BEFORE_FIX = ROOT / "tests" / "fixtures" / "optica_crossrefs_before_174.json"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def item(defn: dict, num: str) -> dict:
    return next(i for s in defn["sections"] for i in s["items"] if i["num"] == num)


def problems(page: str = PAGE, optica: dict = OPTICA) -> list[str]:
    return gen.check(page, optica, CHAI, OPTICA_DOCS)


def regenerated(optica: dict) -> str:
    """The page as `pixi run gen-crosswalk` would write it from `optica`."""
    return gen.splice(PAGE, gen.render_table(gen.load_items(optica)))


def definition_mutation(
    name: str, mutate: Callable[[dict], None], expect: str, stale_only: bool = False
) -> None:
    """Break a copy of OPTICA's definition; the check must notice, and name `expect`.

    Run twice: with the committed page (the table is now stale), and with the
    table regenerated from the broken definition. Unless `stale_only` (a change
    no sentence on the page speaks to), the regenerated run must still fail,
    on a claim, so regenerating the table cannot hide a contradiction."""
    broken = copy.deepcopy(OPTICA)
    mutate(broken)
    stale = problems(PAGE, broken)
    check(
        f"{name}: noticed with the table stale",
        any("stale" in p for p in stale),
        f"{stale}",
    )
    fresh = problems(regenerated(broken), broken)
    if stale_only:
        check(f"{name}: the regenerated table alone agrees", fresh == [], f"{fresh}")
    else:
        check(
            f"{name}: noticed with the table regenerated",
            any(expect in p for p in fresh),
            f"wanted {expect!r} in {fresh}",
        )


def page_mutation(name: str, old: str, new: str, expect: str) -> None:
    """Edit the page once; the check must notice, and name `expect`."""
    count = PAGE.count(old)
    if count != 1:
        check(f"{name}: the text is on the page once", False, f"{count}x {old!r}")
        return
    found = problems(PAGE.replace(old, new), OPTICA)
    check(name, any(expect in p for p in found), f"wanted {expect!r} in {found}")


def main() -> int:
    print("The committed page agrees with the committed definitions")
    found = problems()
    check("no problems", found == [], "\n    ".join(found))
    check(
        "the table on the page is the definition's",
        gen.table_region(PAGE) == gen.render_table(gen.load_items(OPTICA)),
    )
    items = gen.load_items(OPTICA)
    rows = gen.render_table(items).count("\n") - 1
    check("the table has a row per item", rows == len(items), f"{rows}")

    print("The original #174 disagreement is found")
    before = copy.deepcopy(OPTICA)
    earlier = json.loads(BEFORE_FIX.read_text(encoding="utf-8"))["items"]
    for section in before["sections"]:
        for raw in section["items"]:
            raw.update(earlier[raw["num"]])
    old = problems(regenerated(before), before)
    for expect in (
        "headline Equivalent: the page says 0, the definition gives 3",
        "criteria cited: the page says 36, the definition gives 35",
        "items citing s3-7",
        "equivalent rows (app/frameworks/optica/docs.toml)",
    ):
        check(f"names {expect!r}", any(expect in p for p in old), f"{old}")

    print("A broken definition is noticed")
    definition_mutation(
        "one relation changed (2.2 to partial)",
        lambda d: item(d, "2.2")["crossRefs"].update(relation="partial", ids=["s1-2"]),
        "headline Partial",
    )
    definition_mutation(
        "an equivalence back (12.1)",
        lambda d: item(d, "12.1")["crossRefs"].update(relation="equivalent"),
        "headline Equivalent",
    )
    definition_mutation(
        "one id removed (s3-7 from 11.6)",
        lambda d: item(d, "11.6")["crossRefs"]["ids"].remove("s3-7"),
        "s3-7 at 11.6",
    )
    definition_mutation(
        "one id added (s1-5 at 1.1, a criterion the page says is never cited)",
        lambda d: item(d, "1.1")["crossRefs"]["ids"].append("s1-5"),
        "criteria never cited",
    )
    definition_mutation(
        "one id swapped (s4-3 to s4-1 at 7.1)",
        lambda d: item(d, "7.1")["crossRefs"].update(ids=["s4-1"]),
        "criteria of 7.1",
    )
    definition_mutation(
        "who answers changed (11.3 back to adopter)",
        lambda d: item(d, "11.3").update(who="adopter"),
        "who answers 11.3",
    )
    definition_mutation(
        "a not-yet-recorded item recorded (5.3)",
        lambda d: item(d, "5.3")["crossRefs"].update(relation="partial", ids=["s3-2"]),
        "5.3 is named as not yet recorded",
    )
    # An id the page's prose never speaks to: only the table can notice, which is
    # why the table is on the page. Regenerating it is then the reviewable change.
    definition_mutation(
        "one id swapped where no sentence looks (s3-4 to s3-1 at 4.4)",
        lambda d: item(d, "4.4")["crossRefs"].update(ids=["s3-1"]),
        "",
        stale_only=True,
    )

    print("A broken page is noticed")
    page_mutation(
        "a headline count changed",
        "| Partial          |        61 |",
        "| Partial          |        60 |",
        "headline Partial",
    )
    row = next(line for line in PAGE.splitlines() if line.startswith("| 1.1 |"))
    page_mutation(
        "an id in the table changed", row, row.replace("s1-4", "s1-5"), "stale"
    )
    page_mutation(
        "a relation in the table changed",
        next(line for line in PAGE.splitlines() if line.startswith("| 2.2 |")),
        "| 2.2 | adopter | partial | s1-2 |",
        "stale",
    )
    page_mutation(
        "the never-cited list changed",
        "**s1-5, s3-5, s4-8, s5-4, s6-5**",
        "**s1-5, s3-5, s4-8, s5-4**",
        "criteria never cited",
    )
    page_mutation(
        "a citation fix moved",
        "+s3-7 at 11.3 and 11.6",
        "+s3-7 at 11.4 and 11.6",
        "+s3-7 at 11.4",
    )
    page_mutation(
        "a chapter's criteria count changed",
        "| 11 | Monitoring plan      |  6 | s6; s3         |    5 |",
        "| 11 | Monitoring plan      |  6 | s6; s3         |    4 |",
        "criteria in chapter 11",
    )
    page_mutation(
        "the producer split changed",
        "|    29 |   38% |",
        "|    30 |   38% |",
        "items answered by developer",
    )
    page_mutation(
        "a claim reworded so the checker cannot read it",
        "36 of 41 criteria are cited somewhere",
        "Thirty-six of the criteria are cited somewhere",
        "no longer states how many CHAI criteria are cited",
    )
    page_mutation(
        "the table's markers removed",
        gen.END,
        "",
        "between exactly one pair of markers",
    )
    page_mutation(
        "a recorded item named as not yet recorded",
        "recorded there: 5.3 and 7.4 are partial",
        "recorded there: 5.3, 7.2 and 7.4 are partial",
        "7.2 is named as not yet recorded",
    )

    print("The checker's closed sets match the definition")
    check(
        "Who is the definition's whos",
        sorted(w["value"] for w in OPTICA["whos"]) == sorted(gen.Who),
        f"{OPTICA['whos']}",
    )
    check(
        "every relation has a page label",
        set(gen.RELATION_LABEL) == set(gen.CrossRefRelation),
    )
    check(
        "the number words parse",
        gen.number("Twenty-three") == 23 and gen.number("16") == 16,
    )
    check(
        "an item range expands",
        gen.item_nums("10.5-10.7, 11.3 and 11.4")
        == ["10.5", "10.6", "10.7", "11.3", "11.4"],
    )

    print("The check runs when it should")
    hooks = {
        h.get("id"): h
        for repo in yaml.safe_load(PRECOMMIT.read_text(encoding="utf-8"))["repos"]
        for h in repo.get("hooks", [])
    }
    hook = hooks.get("check-crosswalk", {})
    check("the check-crosswalk hook exists", bool(hook))
    check("it runs the check", hook.get("entry") == "pixi run check-crosswalk")
    pattern = re.compile(hook.get("files", "(?!)"))
    for path in (
        "docs/crosswalk.md",
        "app/frameworks/optica/framework.json",
        "app/frameworks/chai/framework.json",
        "app/frameworks/optica/docs.toml",
        "scripts/gen_crosswalk.py",
        "scripts/framework_enums.py",
    ):
        check(f"runs on {path}", bool(pattern.search(path)))
    check("does not run on an unrelated file", not pattern.search("README.md"))
    tasks = tomllib.loads(PIXI.read_text(encoding="utf-8"))["tasks"]
    check(
        "check-crosswalk checks",
        tasks.get("check-crosswalk") == "python scripts/gen_crosswalk.py --check",
    )
    check(
        "gen-docs rewrites the table",
        "gen-crosswalk" in tasks.get("gen-docs", {}).get("depends-on", []),
    )

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
