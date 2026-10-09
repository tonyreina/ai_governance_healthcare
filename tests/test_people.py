#!/usr/bin/env python3
"""A user id must become a person wherever the record is shown (#39).

In the server-backed deployment every identity but the viewer's own rendered as the
literal word "someone": in the access list, the sign-off line, the changelog and the
exports. `ApiStore` had no `profiles`, there was no route to ask, and the branch in
resolveNames never ran. An owner doing the periodic access review saw "someone,
someone, someone", and the printed record a committee files said "Recorded by
someone". The server half is tested in server/tests/test_principals.py; this is the
browser half, with the REAL ApiStore and the REAL resolveNames, against a stand-in
for the network.

    pixi run test-people
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []

# What the server's /api/principals would answer: only people it knows, and only
# for the ids asked. Anything else is simply absent.
FAKE_API = """
(() => {
  const DIRECTORY = {
    'ann@h': {id: 'ann@h', name: 'Ann Example', email: 'ann@h'},
    'bob@h': {id: 'bob@h', name: 'Bob Writer', email: 'bob@h.example'},
  };
  globalThis.__asked = [];
  globalThis.fetch = async (url) => {
    const u = new URL(url, location.href);
    if (u.pathname.endsWith('/principals')) {
      const ids = u.searchParams.get('ids').split(',');
      globalThis.__asked.push(ids);
      return new Response(JSON.stringify(ids.map(i => DIRECTORY[i]).filter(Boolean)),
        {status: 200, headers: {'Content-Type': 'application/json'}});
    }
    return new Response('[]', {status: 200});
  };
})()
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def ask(page, script: str):
    try:
        return page.evaluate(script)
    except Exception as exc:
        return {"error": str(exc).splitlines()[0]}


def fresh(browser):
    page = browser.new_page(viewport={"width": 1300, "height": 1000})
    page.set_default_timeout(5000)
    page.goto(APP.as_uri())
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    page.evaluate("loadSamples()")
    page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
    page.evaluate("openProject([...PROJECTS.keys()][0], 'setup')")
    page.wait_for_timeout(200)
    page.evaluate(FAKE_API)
    return page


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        print("ApiStore can ask who people are")
        page = fresh(browser)
        got = ask(
            page,
            """
            (async () => { ME.id = 'ann@h';
              const store = new ApiStore('/api');
              return await store.profiles(['ann@h', 'bob@h', 'ghost@h']); })()
            """,
        )
        check(
            "known ids resolve to a name and email",
            isinstance(got, dict)
            and got.get("bob@h", {}).get("name") == "Bob Writer"
            and got.get("bob@h", {}).get("email") == "bob@h.example",
            str(got),
        )
        check(
            "the viewer is marked as themself",
            got.get("ann@h", {}).get("isMe") is True,
            str(got),
        )
        check("an unknown id is simply absent", "ghost@h" not in got, str(got))
        big = ask(
            page,
            "(async () => { __asked.length = 0; const s = new ApiStore('/api'); "
            "await s.profiles(Array.from({length: 250}, (_, i) => 'u' + i)); "
            "return __asked.map(a => a.length); })()",
        )
        check(
            "a big batch is split to the server's limit of 100",
            isinstance(big, list) and max(big) <= 100 and sum(big) == 250,
            str(big),
        )

        print("The names appear where ids were")
        page.evaluate(
            "MODE = Mode.API; STORE = new ApiStore('/api'); ME.id = 'ann@h'; "
            "for (const k of Object.keys(NAMES)) delete NAMES[k];"
        )
        page.evaluate(
            "document.body.insertAdjacentHTML('beforeend', "
            "'<div id=probe>' + who('bob@h') + ' | ' + who('ann@h') + ' | ' + "
            "who('ghost@h') + ' | ' + who('') + '</div>')"
        )
        ask(page, "resolveNames(document.getElementById('probe'))")
        page.wait_for_timeout(300)
        text = page.evaluate("document.getElementById('probe').textContent")
        check("a known person shows their name", "Bob Writer" in text, text)
        check("the viewer shows as 'you'", "you" in text, text)
        check(
            "a person the server cannot name shows their id, not 'someone'",
            "ghost@h" in text and text.count("someone") <= 1,
            text,
        )

        print("Exports carry the names too")
        page.evaluate(
            "LOG = [{at: '2026-01-15T10:00:00Z', by: 'bob@h',"
            " text: 'Checkpoint decided'}]; "
            "LOG_TOTAL = 1; S.gates = S.gates || {}"
        )
        ask(page, "primeNames(['bob@h', 'ann@h', 'ghost@h'])")
        page.wait_for_timeout(300)
        md = page.evaluate("exportMD()")
        check(
            "the markdown names who recorded a sign-off",
            "Bob Writer" in md and "(someone)" not in md,
            md[md.find("Sign-off history") : md.find("Sign-off history") + 200],
        )
        check(
            "the printable report names them",
            "Bob Writer" in page.evaluate("reportBody(true)"),
        )
        page.evaluate("LOG = [{at: 'x', by: 'ghost@h', text: 'unknown author'}]")
        check(
            "an author the server cannot name is shown by id in the export",
            "ghost@h" in page.evaluate("exportMD()"),
        )

        print("The browser-only mode keeps its behavior")
        page.evaluate("for (const k of Object.keys(NAMES)) delete NAMES[k]")
        page.evaluate("MODE = Mode.LOCAL")
        check(
            "browser-only mode still says 'someone', never an id it made up",
            "someone" in page.evaluate("who('ghost@h')"),
        )
        page.close()

        print("Resolution is not repeated for people already asked about")
        page = fresh(browser)
        page.evaluate("MODE = Mode.API; STORE = new ApiStore('/api'); ME.id = 'ann@h'")
        for _ in range(3):
            ask(page, "primeNames(['ghost@h', 'bob@h'])")
            page.wait_for_timeout(150)
        asks = page.evaluate("__asked.length")
        check("three renders ask the server once", asks == 1, f"asked {asks} times")
        page.close()
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("people checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
