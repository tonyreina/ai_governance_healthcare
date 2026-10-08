#!/usr/bin/env python3
"""Framework content is translated, marked, and never drifts from its source (#80).

The CHAI and OPTICA content lives in the framework definitions (app/js/10-frameworks/),
which stay the English source of truth. app/i18n/framework/en.json is that English,
keyed by stable ids, and each other language's file translates those keys.

* The English file must equal what the definitions hold right now, so editing a
  criterion without updating the catalogs fails here instead of silently showing a
  stale translation. `--write` regenerates en.json from the definitions.
* A translated framework screen carries a note that the wording is an unofficial
  translation, and a record still stores the English value (a checkpoint decision).

    pixi run test-framework-i18n
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
SOURCE = ROOT / "app" / "i18n" / "framework" / "en.json"

# The English source strings, keyed by stable id, read from the live definitions.
EXTRACT = """() => {
  const out = {};
  for (const [k, p] of Object.entries(PRINCIPLES)) out[`chai.principle.${k}`] = p.name;
  for (const s of STAGES) {
    out[`chai.stage.${s.id}.title`] = s.title;
    out[`chai.stage.${s.id}.blurb`] = s.blurb;
    for (const it of s.items) out[`chai.item.${it.id}`] = it.text;
  }
  for (const [k, g] of Object.entries(GATES)) {
    out[`chai.gate.${k}.title`] = g.title;
    out[`chai.gate.${k}.q`] = g.q;
    out[`chai.gate.${k}.help`] = g.help;
    for (const o of g.options) out[`chai.option.${o}`] = o;
  }
  for (const [d, s] of Object.entries(SHORT_DECISION)) out[`chai.short.${d}`] = s;
  CARD.forEach((sec, i) => {
    out[`chai.card.sec.${i}`] = sec.sec;
    for (const f of sec.fields) {
      out[`chai.card.${f[0]}.label`] = f[1];
      if (f[2]) out[`chai.card.${f[0]}.hint`] = f[2];
    }
  });
  for (const c of METRIC_CATS) out[`chai.metricCat.${c}`] = c;
  return out;
}"""

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
        live = page.evaluate(EXTRACT)
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
        page.evaluate("openProject([...PROJECTS.keys()][0], STAGES[0].id)")
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

        print("In English, nothing changes and no note is shown")
        page.evaluate("setLocale('en'); relocalize(); go(STAGES[0].id);")
        page.wait_for_timeout(200)
        check("no translation note in English", page.locator(".fw-note").count() == 0)
        check(
            "the English criterion is the definition's",
            page.evaluate("STAGES[0].items[0].text") in page.inner_text("#main"),
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
