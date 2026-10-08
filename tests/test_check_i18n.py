#!/usr/bin/env python3
"""check-i18n notices every way a catalog goes wrong (#80).

The real catalogs must pass, and each rule is shown failing on a copy broken in the
way it guards against. A check that is never shown to fail is a claim, not a control.

    pixi run test-check-i18n
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "check_i18n", ROOT / "scripts" / "check_i18n.py"
)
ci = importlib.util.module_from_spec(spec)
sys.modules["check_i18n"] = ci
spec.loader.exec_module(ci)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def load(locale: str) -> dict:
    return json.loads(
        (ROOT / "app" / "i18n" / f"{locale}.json").read_text(encoding="utf-8")
    )


def main() -> int:
    print("The real catalogs")
    check("check-i18n passes on the repository", ci.main() == 0)

    en = load("en")
    fr = load("fr")
    safety = set(en["@meta"]["safety"])
    check("French is clean", not ci.catalog_problems("fr", fr, en, safety))

    def broken(mutate) -> list[str]:
        cat = copy.deepcopy(fr)
        mutate(cat)
        return ci.catalog_problems("fr", cat, en, safety)

    print("Each rule notices (mutation)")
    check("a missing key", bool(broken(lambda c: c.pop("dash.title"))))
    check("an extra key", bool(broken(lambda c: c.update({"dash.nothing": "x"}))))
    check(
        "a dropped placeholder",
        bool(broken(lambda c: c.update({"dash.sponsor": "Commanditaire"}))),
    )
    check(
        "an invented placeholder",
        bool(broken(lambda c: c.update({"dash.title": "Projets {count}"}))),
    )
    check(
        "markup in a value",
        bool(broken(lambda c: c.update({"dash.title": "<b>x</b>"}))),
    )
    check(
        "a wrong locale tag",
        bool(broken(lambda c: c["@meta"].update({"locale": "de"}))),
    )
    check("a missing language name", bool(broken(lambda c: c["@meta"].pop("name"))))
    check(
        "a reviewer for a key that is not safety-bearing",
        bool(
            broken(
                lambda c: c["@meta"]["reviewers"].update({"dash.title": "A. Person"})
            )
        ),
    )
    check(
        "an empty reviewer",
        bool(broken(lambda c: c["@meta"]["reviewers"].update({"safety.scope": " "}))),
    )
    check(
        "a reviewer for a safety key is accepted",
        not broken(
            lambda c: c["@meta"]["reviewers"].update(
                {"safety.scope": "A. Person, 2026-10-08"}
            )
        ),
    )

    plural_en = dict(
        en, **{"x.count": {"one": "{count} thing", "other": "{count} things"}}
    )
    plural_ru = dict(
        load("ru"), **{"x.count": {"one": "{count} вещь", "other": "{count} вещей"}}
    )
    check(
        "a plural missing a form the language needs (Russian: few, many)",
        any(
            "plural forms" in p
            for p in ci.catalog_problems("ru", plural_ru, plural_en, safety)
        ),
    )
    check(
        "a plural given as a plain string",
        any("plural" in p for p in ci.catalog_problems(
            "fr", dict(fr, **{"x.count": "{count} choses"}), plural_en, safety)),
    )  # fmt: skip
    check(
        "a language with no plural rules",
        any("plural rules" in p for p in ci.catalog_problems(
            "xx", dict(fr, **{"@meta": dict(fr["@meta"], locale="xx")}), en, safety)),
    )  # fmt: skip

    print("The source and the app")
    check(
        "a safety key that does not exist",
        bool(
            ci.source_problems(
                dict(en, **{"@meta": dict(en["@meta"], safety=["no.such"])})
            )
        ),
    )
    check(
        "a plural with no 'other' form",
        bool(ci.source_problems(dict(en, **{"x.n": {"one": "a"}}))),
    )
    texts = {"a.js": 't("dash.title"); t("dash.nosuch");'}
    found = ci.usage_problems(
        {"@meta": {}, "dash.title": "x", "dash.unused": "y"}, texts
    )
    check(
        "a key the app asks for that does not exist", any("nosuch" in p for p in found)
    )
    check("a key nothing uses", any("unused" in p for p in found))
    check(
        "a CSS selector or an event name is not taken for a key",
        not ci.usage_problems(
            {"@meta": {}}, {"a.js": '"header.top" "project.created"'}
        ),
    )

    print("English set on screen at run time, outside t()")
    rl = ci.runtime_literal_problems
    for label, js in [
        ("a toast", 'toast("Example filled in");'),
        ("a label a handler swaps", 'btn.textContent=open?"Hide details":"More";'),
        (
            "a tooltip set by code",
            'frame.setAttribute("title", "Report for printing");',
        ),
        ("an error screen", 'fatalError("Cannot load", detail);'),
        ("the mode indicator", 'setMode("Access ended","ro");'),
    ]:
        check(f"{label} is noticed (mutation)", bool(rl({"a.js": js})))
    check(
        "the same through t() passes",
        not rl({"a.js": 'toast(t("toast.example")); b.textContent=t("ci.hide");'}),
    )
    check(
        "a value that is not language passes",
        not rl({"a.js": 'el.textContent = "\u2713"; toast(msg);'}),
    )
    check(
        "i18n-ok needs a reason",
        bool(rl({"a.js": 'toast("Hi there"); // i18n-ok:'}))
        and not rl({"a.js": 'toast("ChatGPT"); // i18n-ok: a product name'}),
    )

    print("Framework catalogs (D-60)")
    fw_en = {"chai.item.a": "Criterion", "chai.item.b": "Another"}
    full = {str(loc): dict(fw_en) for loc in ci.Locale}
    check("a complete set passes", not ci.framework_problems(fw_en, full))
    gap = {**full, "fr": {"chai.item.a": "Critère"}}
    check("a missing framework key", bool(ci.framework_problems(fw_en, gap)))
    extra = {**full, "fr": {**fw_en, "chai.item.z": "x"}}
    check("an extra framework key", bool(ci.framework_problems(fw_en, extra)))
    empty = {**full, "fr": {**fw_en, "chai.item.a": " "}}
    check("an empty translation", bool(ci.framework_problems(fw_en, empty)))
    markup = {**full, "fr": {**fw_en, "chai.item.a": "<b>x</b>"}}
    check("markup in a translation", bool(ci.framework_problems(fw_en, markup)))
    lacking = {k: v for k, v in full.items() if k != "ru"}
    check(
        "a language with no framework file", bool(ci.framework_problems(fw_en, lacking))
    )

    print("The spelling check leaves translations alone, and only them")
    spec2 = importlib.util.spec_from_file_location(
        "check_spelling", ROOT / "scripts" / "check_spelling.py"
    )
    cs = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(cs)
    check("a French catalog is skipped", cs.skip(ROOT / "app" / "i18n" / "fr.json"))
    check(
        "the English source is checked", not cs.skip(ROOT / "app" / "i18n" / "en.json")
    )
    check(
        "a framework translation is skipped",
        cs.skip(ROOT / "app" / "i18n" / "framework" / "fr.json"),
    )
    check(
        "the framework's English source is checked",
        not cs.skip(ROOT / "app" / "i18n" / "framework" / "en.json"),
    )
    check(
        "a JSON file elsewhere is checked",
        not cs.skip(ROOT / "schema" / "project.schema.json"),
    )
    check(
        "a nested file under app/i18n is checked (mutation)",
        not cs.is_translation("app/i18n/drafts/fr.json"),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("check-i18n tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
