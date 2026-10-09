#!/usr/bin/env python3
"""Text a person types must stay text, on every screen and in every export.

A governance record is written by many people and read by a board, an auditor and a
regulator, and the dashboard is one file whose page policy has to allow inline script
(R-01). So one unescaped field is enough for a colleague's text to run as code in the
CMIO's session, or for a link in an exported report to turn on whoever opens it.

This does not trust a list of known-safe fields. It takes a fully populated project and
poisons EVERY string in it: names, evidence, owners, dates, decisions and statuses (the
fields an import can fill with anything), every key's value, an extra key named like the
payload, the change log, the people's names, the search box, the saved interface state,
the legacy record and the import file. Then it renders every screen the project has, and
every export, and asserts that nothing ran, nothing was injected, and the text is still
there as text. A field added tomorrow is covered the day it is added, because the
poison is applied to whatever the document holds.

What counts as injected, in the page and in each export opened in a page of its own:

* a canary (`window.__pwned`) that every script payload increments;
* any element carrying the payloads' marker attribute (`data-inj`), which only exists if
  a payload's markup was parsed as markup;
* a script, iframe, base, meta refresh, form, or stylesheet link that the app did not
  put there; any `on*` attribute; any `javascript:` link or `srcdoc`.

The Markdown export is checked as text: a value must not start a heading, a link to a
script, a table row or raw HTML in whatever reads it. The CSV is checked for cells a
spreadsheet would run as a formula.

    pixi run test-injection
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# U+2028: a line separator JSON allows raw and that Markdown and HTML must not trust.
LSEP = chr(0x2028)
C = "window.__pwned++"
PAYLOADS = [
    f'<img src=x onerror="{C}" data-inj>',
    f'"><svg onload="{C}" data-inj>',
    f"'><script>{C}</script>",
    f'</textarea><img src=x onerror="{C}" data-inj>',
    f'" autofocus onfocus="{C}" data-inj="',
    f"' autofocus onfocus='{C}' data-inj='",
    f'<a href="javascript:{C}" data-inj>x</a>',
    f"javascript:{C}",
    "${" + C + "}",
    "`${" + C + "}`",
    f'<details open ontoggle="{C}" data-inj>',
    f'<iframe srcdoc="<script>parent.{C}</script>" data-inj></iframe>',
    "<style>@import url(//evil.example/x.css)</style>"
    '<base href="//evil.example/" data-inj>',
    '<meta http-equiv="refresh" content="0;url=//evil.example" data-inj>',
    f"\n# injected heading\n[x](javascript:{C})\n| a | b |\n> quote\n- item",
    f"</script><script>{C}</script>",
    '<form action="//evil.example" data-inj>'
    "<input type=submit formaction=//evil.example></form>",
    LSEP + f'<img src=x onerror="{C}" data-inj>',
    "{{constructor.constructor('" + C + "')()}}",
    f'"; {C}; "',
    '=HYPERLINK("https://evil.example","x")',
    "+cmd|' /C calc'!A0",
    "@SUM(1+1)",
    "-2+3",
]

# Injected elements and attributes, in the page or in an export opened by itself.
AUDIT = """(base) => {
  const bad = [];
  if (window.__pwned) bad.push('a payload ran: ' + window.__pwned);
  const n = s => document.querySelectorAll(s).length;
  if (n('[data-inj]')) bad.push('injected markup: ' + n('[data-inj]') + ' element(s)');
  if (n('script') > base.script) bad.push('a script was added');
  if (n('iframe') > base.iframe) bad.push('an iframe was added');
  if (n('base')) bad.push('a base element');
  if (n('meta[http-equiv]')) bad.push('a meta refresh');
  if (n('form') > base.form) bad.push('a form was added');
  if (n('link[rel=stylesheet]')) bad.push('a stylesheet link');
  if (n('[srcdoc]')) bad.push('a srcdoc');
  document.querySelectorAll('a[href]').forEach(a => {
    if (/^\\s*(javascript|data|vbscript):/i.test(a.getAttribute('href')))
      bad.push('a link to ' + a.getAttribute('href').slice(0, 30));
  });
  for (const el of document.querySelectorAll('*'))
    for (const a of el.attributes)
      if (/^on/i.test(a.name)) { bad.push('an ' + a.name + ' attribute'); break; }
  return bad;
}"""

BASE = (
    "() => ({script: document.querySelectorAll('script').length,"
    " iframe: document.querySelectorAll('iframe').length,"
    " form: document.querySelectorAll('form').length})"
)

# Poison every string in a document, the keys' values at every depth, and add a key
# named like the payload where the document keeps a map.
TAINT = """(args) => {
  const [doc, p] = args;
  const taint = v => {
    if (typeof v === 'string') return p;
    if (Array.isArray(v)) return v.map(taint);
    if (v && typeof v === 'object') {
      const o = {};
      for (const [k, x] of Object.entries(v)) o[k] = taint(x);
      o[p] = p;
      return o;
    }
    return v;
  };
  return taint(doc);
}"""


def md_problems(md: str) -> list[str]:
    bad = []
    if re.search(r"(?m)^#\s*injected heading", md):
        bad.append("a value started a heading")
    if re.search(r"(?<!\\)\]\(\s*javascript:", md, re.I):
        bad.append("a link to a script")
    if re.search(r"(?m)^\s*>\s*quote", md):
        bad.append("a value started a quotation")
    if re.search(r"(?m)^\|\s*a\s*\|\s*b\s*\|", md):
        bad.append("a value started a table row")
    if re.search(r"(?<!\\)<[a-zA-Z/!?]", md):
        bad.append("raw HTML")
    if re.search(r"(?<!\\)!\[", md):
        bad.append("an image (a request when it is read)")
    return bad


def csv_problems(text: str) -> list[str]:
    bad = []
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            if cell[:1] in ("=", "+", "-", "@", "\t", "\r"):
                bad.append(cell[:30])
    return bad


def open_app(browser, url: str | None = None):
    ctx = browser.new_context()
    ctx.add_init_script("window.__pwned = 0")
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)[:120]))
    page.goto(url or APP.as_uri())
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    return ctx, page, errors


def audit(page, base, where: str, bad: list[str]) -> None:
    for problem in page.evaluate(AUDIT, base):
        bad.append(f"{where}: {problem}")


def run_payload(
    browser, payload: str, url: str | None = None
) -> tuple[list[str], list[str]]:
    bad: list[str] = []
    ctx, page, errors = open_app(browser, url)
    base = page.evaluate(BASE)
    page.evaluate("loadSamples()")
    page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
    sample = page.evaluate("clone([...PROJECTS.values()][0])")
    doc = page.evaluate(TAINT, [sample, payload])
    doc.pop("id", None)
    page.evaluate(
        "async (d) => { await STORE.create('inj1', d); }",
        doc,
    )
    page.wait_for_function("PROJECTS.has('inj1')", timeout=5000)

    # People's names, the change log, the search box and the saved state.
    page.evaluate(
        """(p) => {
            NAMES[ME.id || 'x'] = p; NAMES['someone'] = p;
            UI.q = p; UI.qAll = true; UI.filter = p;
        }""",
        payload,
    )
    page.evaluate("openProject('inj1', 'setup')")
    page.evaluate("setOpticaEnabled(true)")
    page.evaluate("(p) => writeLog('inj1', p)", payload)
    page.wait_for_timeout(100)
    # The litigation-hold history shows a person's typed reason and the name of whoever
    # wrote it. That section exists only with a server and an owner, so give it both.
    page.evaluate(
        """async (p) => {
            ME.id = 'owner@hospital.example';
            S.access = {owners: [ME.id], writers: [], readers: []};
            STORE.getHold = async () => ({held: true, history: [
              {at: p, by: p, action: 'place', reason: p},
              {at: '2026-01-01T00:00:00Z', by: p, action: p, reason: p}]});
            go('setup');
            await fillHold();
            openHoldDialog('place');
        }""",
        payload,
    )
    page.wait_for_timeout(50)
    audit(page, base, "litigation hold", bad)
    page.keyboard.press("Escape")
    views = page.evaluate("activeViews().map(v => v.id)")
    for view in views:
        page.evaluate("(v) => go(v)", view)
        page.wait_for_timeout(30)
        audit(page, base, f"view {view}", bad)
    page.evaluate(
        "renderLabel(); document.getElementById('panel').classList.add('open')"
    )
    audit(page, base, "model card panel", bad)

    shown = page.evaluate(
        "() => { go('report'); return document.getElementById('main').innerText; }"
    )
    needle = payload.strip().replace(LSEP, "")[:10]
    if needle not in shown:
        bad.append("the payload is not visible as text in the report (vacuous)")

    page.evaluate("goHome()")
    audit(page, base, "dashboard", bad)
    page.evaluate("openProject('inj1', 'setup'); openDeleteDialog()")
    audit(page, base, "delete dialog", bad)
    page.keyboard.press("Escape")

    # The exports, as text and opened in a page of their own.
    out = page.evaluate(
        """() => ({
            html: exportHTML(), md: exportMD(), csv: exportCSV(),
            json: JSON.stringify(projectJSON(S)), slug: slug(S.meta.solution),
        })"""
    )
    for problem in md_problems(out["md"]):
        bad.append(f"markdown export: {problem}")
    for cell in csv_problems(out["csv"]):
        bad.append(f"csv export: a cell a spreadsheet would run: {cell!r}")
    if not re.fullmatch(r"[a-z0-9-]+", out["slug"]):
        bad.append(f"file name: {out['slug']!r}")
    try:
        json.loads(out["json"])
    except ValueError:
        bad.append("json export is not JSON")
    if re.search(r"<script", out["html"], re.I):
        bad.append("html export: carries a script")
    # The PDF is the report loaded into a same-origin frame so it can be printed; the
    # frame gets no script, so even a markup slip there could not run as the app.
    frame = page.evaluate(
        """async () => {
            exportPDF();
            const f = [...document.querySelectorAll('iframe')].pop();
            await new Promise(r => setTimeout(r, 300));
            let ran = 0;
            try { ran = f.contentWindow.__pwned || 0; } catch (e) { ran = -1; }
            const out = {sandbox: f.getAttribute('sandbox') || '', ran};
            f.remove();   // the app's own frame; later audits look for others
            return out;
        }"""
    )
    if "allow-scripts" in frame["sandbox"] or not frame["sandbox"]:
        bad.append(f"pdf frame: not sandboxed without scripts ({frame['sandbox']!r})")
    if frame["ran"]:
        bad.append(f"pdf frame: a payload ran ({frame['ran']})")
    shot = ctx.new_page()
    shot.add_init_script("window.__pwned = 0")
    shot.set_content(out["html"])
    shot.wait_for_timeout(100)
    audit(shot, {"script": 0, "iframe": 0, "form": 0}, "html export", bad)
    shot.close()

    # The import path takes the same poison as a file.
    export = json.loads(out["json"])
    page.evaluate("goHome()")
    page.set_input_files(
        "#importFile",
        {
            "name": "x.json",
            "mimeType": "application/json",
            "buffer": json.dumps(export).encode(),
        },
    )
    page.wait_for_timeout(300)
    page.evaluate("goHome()")
    audit(page, base, "after an import", bad)
    ctx.close()
    return bad, errors


def saved_state_problems(browser, payload: str) -> list[str]:
    """What the browser's own storage can hold: the saved view and the legacy record."""
    bad: list[str] = []
    ctx = browser.new_context()
    ctx.add_init_script("window.__pwned = 0")
    page = ctx.new_page()
    page.goto(APP.as_uri())
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    base = page.evaluate(BASE)
    page.evaluate(
        """(p) => {
            localStorage.setItem('chai-ui-v2', JSON.stringify(
              {view: p, project: p, filter: p, q: p, qAll: p}));
            const legacy = {meta: {solution: p, org: p}, items: {}, gates: {}};
            localStorage.setItem('chai-review-v1', JSON.stringify(legacy));
        }""",
        payload,
    )
    page.reload()
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    page.wait_for_timeout(200)
    audit(page, base, "saved state and the legacy record", bad)
    ctx.close()
    return bad


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        print("Every string poisoned, every screen and export audited")
        all_errors: set[str] = set()
        for payload in PAYLOADS:
            bad, errors = run_payload(browser, payload)
            bad += saved_state_problems(browser, payload)
            all_errors.update(errors)
            check(f"{payload[:48]!r}", not bad, "; ".join(sorted(set(bad))[:4]))
        check(
            "no screen threw on a field it did not expect",
            not all_errors,
            "; ".join(sorted(all_errors)[:3]),
        )

        print("The rules notice injection (mutation)")
        for label, markup in [
            ("an event handler", f'<img src=x onerror="{C}" data-inj>'),
            ("a script link", '<a href="javascript:void(0)">x</a>'),
            ("a base element", '<base href="//evil.example/">'),
            ("a meta refresh", '<meta http-equiv="refresh" content="0;url=/">'),
        ]:
            ctx, page, _ = open_app(browser)
            base = page.evaluate(BASE)
            # Insert and audit in one step: a meta refresh navigates the page away.
            found = page.evaluate(
                "([m, base, audit]) => { const d = document.createElement('div');"
                " d.innerHTML = m; document.body.appendChild(d);"
                " return eval('(' + audit + ')')(base); }",
                [markup, base, AUDIT],
            )
            check(f"the audit notices {label}", bool(found), str(found))
            ctx.close()
        check(
            "the Markdown rules notice a heading, a script link and raw HTML",
            len(md_problems("# injected heading\n[a](javascript:1)\n<img src=x>")) == 3
            and not md_problems(r"a \<img src=x\> \[a\]\(javascript:1\)"),
        )
        check(
            "the CSV rule notices a formula cell",
            csv_problems('a,"=1+1"\r\n') == ["=1+1"],
        )

        print("Dropping the escape is caught (mutation)")
        html = APP.read_text(encoding="utf-8")
        weak = re.sub(
            r"const esc = s => String\(s \?\? \"\"\)\.replace\([^\n]*",
            'const esc = s => String(s ?? "");',
            html,
            count=1,
        )
        check("the mutation replaced the escape", weak != html)
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "weak.html"
            copy.write_text(weak, encoding="utf-8")
            bad, _ = run_payload(browser, PAYLOADS[0], copy.as_uri())
        check(
            "an app that does not escape is rejected",
            bool(bad),
            "nothing was noticed",
        )
        ctx.close()
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("injection checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
