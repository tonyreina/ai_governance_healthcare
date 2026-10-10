#!/usr/bin/env python3
"""Framework content is translated, marked, and never drifts from its source (#80).

The CHAI and OPTICA content lives in the framework definitions
(app/frameworks/<id>/framework.json), which stay the English source of truth,
together with the few strings CHAI's plugin code adds (its model card, metric
categories and TE metrics), which are read from the page.
app/i18n/framework/en.json is that English, keyed by stable ids, and each other
language's file translates those keys.

* The English file must equal what the definitions hold right now, so editing a
  criterion without updating the catalogs fails here instead of silently showing a
  stale translation. `--write` regenerates en.json from the definitions.
* A translated framework screen carries a note that the wording is an unofficial
  translation, and a record still stores the English value (a checkpoint decision).

    pixi run test-framework-i18n
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
SOURCE = ROOT / "app" / "i18n" / "framework" / "en.json"

FRAMEWORKS = ROOT / "app" / "frameworks"

# The strings CHAI's plugin code adds (its model card, metric categories and TE
# metrics). They are not in a definition, so they are read from the live page,
# keyed by stable id.
PLUGIN_EXTRACT = """() => {
  const out = {};
  CARD.forEach((sec, i) => {
    out[`chai.card.sec.${i}`] = sec.sec;
    for (const f of sec.fields) {
      out[`chai.card.${f[0]}.label`] = f[1];
      if (f[2]) out[`chai.card.${f[0]}.hint`] = f[2];
    }
  });
  for (const c of METRIC_CATS) out[`chai.metricCat.${c}`] = c;
  for (const [k, u] of Object.entries(CHAI_TE)) {
    out[`te.usecase.${k}`] = u.label;
    for (const m of u.metrics) out[`te.metric.${m.name}`] = m.name;
  }
  return out;
}"""


def definition(framework: str, root: Path = FRAMEWORKS) -> dict:
    """A framework's definition, app/frameworks/<id>/framework.json."""
    path = root / framework / "framework.json"
    return json.loads(path.read_text(encoding="utf-8"))


def chai_strings(chai: dict) -> dict[str, str]:
    """CHAI's English, keyed by stable id, from its definition."""
    out: dict[str, str] = {}
    for p in chai["categories"]:
        out[f"chai.principle.{p['id']}"] = p["name"]
    for s in chai["sections"]:
        out[f"chai.stage.{s['id']}.title"] = s["title"]
        out[f"chai.stage.{s['id']}.blurb"] = s["blurb"]
        for it in s["items"]:
            out[f"chai.item.{it['id']}"] = it["text"]
    for g in chai["gates"]:
        out[f"chai.gate.{g['id']}.title"] = g["title"]
        out[f"chai.gate.{g['id']}.q"] = g["question"]
        out[f"chai.gate.{g['id']}.help"] = g["help"]
        for o in g["options"]:
            out[f"chai.option.{o['value']}"] = o.get("label", o["value"])
    for g in chai["gates"]:
        for o in g["options"]:
            if "short" in o:
                out[f"chai.short.{o['value']}"] = o["short"]
    return out


def optica_strings(optica: dict) -> dict[str, str]:
    """OPTICA's English, keyed by stable id, from its definition."""
    out: dict[str, str] = {}
    for c in optica["sections"]:
        out[f"optica.chapter.{c['n']}.title"] = c["title"]
        if c.get("purpose"):
            out[f"optica.chapter.{c['n']}.purpose"] = c["purpose"]
        for it in c["items"]:
            out[f"optica.item.{it['id']}"] = it["text"]
    return out


def derived_english(plugin: dict[str, str], root: Path = FRAMEWORKS) -> dict[str, str]:
    """Everything framework/en.json must hold, in its order: CHAI's definition,
    then its plugin code's strings, then OPTICA's definition."""
    return {
        **chai_strings(definition("chai", root)),
        **plugin,
        **optica_strings(definition("optica", root)),
    }


def edited_definition_is_caught(source: dict[str, str], plugin: dict[str, str]) -> bool:
    """Mutation: change one criterion's text in a temporary copy of CHAI's
    definition. What is derived from the copy must differ from en.json in that
    criterion's key, and in no other."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(FRAMEWORKS, root, dirs_exist_ok=True)
        chai = definition("chai", root)
        item = chai["sections"][0]["items"][0]
        item["text"] += " (edited)"
        (root / "chai" / "framework.json").write_text(
            json.dumps(chai, ensure_ascii=False), encoding="utf-8"
        )
        derived = derived_english(plugin, root)
    differ = {
        k for k in source.keys() | derived.keys() if source.get(k) != derived.get(k)
    }
    return differ == {f"chai.item.{item['id']}"}


failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def main() -> int:
    write = "--write" in sys.argv
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        plugin = page.evaluate(PLUGIN_EXTRACT)
        live = derived_english(plugin)
        if write:
            SOURCE.write_text(json.dumps(live, ensure_ascii=False, indent=2) + "\n")
            print(f"  wrote {SOURCE.relative_to(ROOT)} ({len(live)} strings)")
        source = (
            json.loads(SOURCE.read_text(encoding="utf-8")) if SOURCE.exists() else {}
        )
        print("The English source matches the definitions")
        check(
            "framework/en.json is exactly what the definitions hold",
            source == live,
            f"{len(set(live) ^ set(source))} key(s) differ; run with --write",
        )
        edited = dict(live)
        first = next(iter(edited))
        edited[first] = edited[first] + " (edited)"
        check(
            "an edited criterion is noticed (mutation)",
            edited != live and {k for k in edited if edited[k] != live[k]} == {first},
        )
        check(
            "a criterion edited in a definition is noticed (mutation)",
            edited_definition_is_caught(source, plugin),
        )
        stale = {k for k in source if k in live and source[k] != live[k]}
        check(
            "no criterion changed under its translation",
            not stale,
            str(sorted(stale)[:5]),
        )

        print("A translated framework screen")
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("setLocale('de'); relocalize();")
        page.evaluate(
            "openProject([...PROJECTS.keys()][0], ENGINES.chai.sections[0].id)"
        )
        page.wait_for_timeout(200)
        main_text = page.inner_text("#main")
        check(
            "shows the criteria in German",
            tf_de(page, "chai.item.s1-1") in main_text,
            main_text[:120],
        )
        check(
            "and says the wording is an unofficial translation",
            page.locator(".fw-note").count() == 1,
        )
        page.evaluate("go('gA')")
        page.wait_for_timeout(200)
        buttons = page.eval_on_selector_all(
            ".decisions button", "bs => bs.map(b => [b.dataset.d, b.textContent])"
        )
        check(
            "checkpoint options read German and keep the English value",
            [
                "Proceed with conditions",
                tf_de(page, "chai.option.Proceed with conditions"),
            ]
            in buttons,
            str(buttons),
        )
        page.click('.decisions button[data-d="Proceed with conditions"]')
        page.wait_for_timeout(200)
        check(
            "choosing one records the English decision",
            page.evaluate("S.gates.A.decision") == "Proceed with conditions",
        )

        print("CHAI's suggested metrics")
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.evaluate(
            "S.meta.chaiUseCase = 'sepsis-risk-prediction';"
            " go(ENGINES.chai.sections"
            ".find(s => (s.slots || []).includes('chai.metrics')).id);"
        )
        page.wait_for_timeout(200)
        english = "Risk Ratio"
        button = page.locator(f'button[data-te="{english}"]')
        check(
            "a metric name reads German and keeps the English value",
            button.inner_text().strip()
            == tf_de(page, f"te.metric.{english}")
            != english,
            button.inner_text(),
        )
        check(
            "and the use case does too",
            tf_de(page, "te.usecase.sepsis-risk-prediction")
            in page.inner_text("#teUse"),
        )
        check(
            "the list says its names are translated from CHAI's English",
            page.locator(".te-note").count() == 1,
        )
        button.click()
        page.wait_for_timeout(200)
        check(
            "adding one records CHAI's English name",
            english in page.evaluate("S.metrics.map(m => m.name)"),
        )
        check(
            "and puts the cursor in its value, without an error",
            not errors
            and page.evaluate("document.activeElement.dataset.bind || ''").endswith(
                ".value"
            ),
            "; ".join(errors),
        )

        print("OPTICA's questions")
        page.evaluate("setFrameworkEnabled('optica', true); go('o1');")
        page.wait_for_timeout(200)
        text = page.inner_text("#main")
        check(
            "an OPTICA question reads German, with the note",
            tf_de(page, "optica.item.1-1") in text
            and page.locator(".fw-note").count() == 1,
            text[:120],
        )
        check(
            "and so does the chapter title in the rail",
            tf_de(page, "optica.chapter.1.title") in page.inner_text("#rail"),
        )

        print("In English, nothing changes and no note is shown")
        page.evaluate("setLocale('en'); relocalize(); go(ENGINES.chai.sections[0].id);")
        page.wait_for_timeout(200)
        check(
            "no translation note in English",
            page.locator(".fw-note, .te-note").count() == 0,
        )
        check(
            "the English criterion is the definition's",
            page.evaluate("ENGINES.chai.sections[0].items[0].text")
            in page.inner_text("#main"),
        )
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("framework i18n checks passed")
    return 0


def tf_de(page, key: str) -> str:
    return page.evaluate("(k) => FRAMEWORK_I18N.de[k]", key)


if __name__ == "__main__":
    sys.exit(main())
