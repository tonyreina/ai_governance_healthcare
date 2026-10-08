#!/usr/bin/env python3
"""The record fingerprint travels with every export (#150).

The fingerprint notice in the dashboard says "A SHA-256 travels in the JSON export for
anyone who needs the stronger property". It did not: the function that computed one
was never called. MD5 has been collision-broken since 2004 and is only a version
fingerprint; SHA-256 is the one to quote if a hash is ever offered as evidence that a
record was not altered. So the JSON export, the HTML and PDF report and the Markdown
report now carry both, computed over the same canonical form the dashboard shows.

What is asserted, in a real browser:

* the dashboard's SHA-256 (written here, because the browser's own is asynchronous and
  the exports are not) agrees with Python's `hashlib` on awkward inputs: the empty
  string, every padding boundary, a long string and non-ASCII text;
* the JSON export carries the project id, an MD5 that equals the one the setup page
  shows, and a SHA-256, and a second implementation (examples/load_export.py, in
  Python, written from the rule and not from the JavaScript) recomputes both from the
  file alone, including for names with accents, CJK and emoji;
* a substantive change moves the fingerprint, and a volatile one (the last-saved
  time) does not;
* editing the exported record is noticed, and so is an export with no fingerprint;
* the HTML and Markdown reports carry the same two digests, in the reader's language
  (the label translates, the digits do not);
* the schema declares the new fields, and the notice's promise is now true.

    pixi run test-fingerprint
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
SCHEMA = ROOT / "schema" / "project.schema.json"
EN = ROOT / "app" / "i18n" / "en.json"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def load_examples():
    spec = importlib.util.spec_from_file_location(
        "load_export", ROOT / "examples" / "load_export.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["load_export"] = module
    spec.loader.exec_module(module)
    return module


# U+2028: JSON permits it raw, and JavaScript and Python must agree on not escaping it.
LS = chr(0x2028)

VECTORS = [
    "",
    "abc",
    "a" * 55,  # one block, the longest that still fits the 0x80 and the length
    "a" * 56,  # forces a second block for the length
    "a" * 63,
    "a" * 64,
    "a" * 65,
    "a" * 1000,
    '{"meta":{"solution":"Sepsis early warning"}}',
    "héllo wörld ✓ 日本語 🎉 " + LS + ' \\ " \n\t',
]

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def state(page, **extra) -> dict:
    """Make the page's current project a fresh one with some awkward content."""
    return page.evaluate(
        """(extra) => {
            S = normalize(blankProject("Sepsis early warning"));
            S.id = "p-fp";
            CUR = "p-fp";
            Object.assign(S.meta, extra.meta || {});
            return {md5: contentHash(S), sha256: sha256(canonicalJSON(S))};
        }""",
        extra,
    )


def main() -> int:
    ex = load_examples()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)

        print("SHA-256 in the dashboard agrees with hashlib")
        got = page.evaluate("(vs) => vs.map(v => sha256(v))", VECTORS)
        for text, digest in zip(VECTORS, got, strict=True):
            want = hashlib.sha256(text.encode("utf-8")).hexdigest()
            check(f"{len(text)} characters", digest == want, f"{digest} != {want}")
        check(
            "and it is not just echoing a constant (mutation)",
            len(set(got)) == len(VECTORS),
        )

        print("The JSON export carries the fingerprint")
        awkward = {
            "meta": {
                "solution": "Sepsis early warning — Sépsis 日本語 🎉",
                "developer": 'Acme "Health" \\ Labs\nLine two\ttabbed',
                "scope": "Zürich, São Paulo; " + LS + " separator",
            }
        }
        shown = state(page, **awkward)
        export = json.loads(page.evaluate("JSON.stringify(projectJSON(S))"))
        fp = export.get("fingerprint") or {}
        check("it has a fingerprint", bool(fp), str(sorted(export)))
        check("with a SHA-256", bool(HEX64.match(fp.get("sha256", ""))), str(fp))
        check("and an MD5", bool(HEX32.match(fp.get("md5", ""))), str(fp))
        check("and the project id", export.get("project_id") == "p-fp")
        check(
            "its MD5 is the one the setup page shows",
            fp.get("md5") == shown["md5"],
            f"{fp.get('md5')} != {shown['md5']}",
        )
        check(
            "its SHA-256 is the dashboard's over the same record",
            fp.get("sha256") == shown["sha256"],
        )
        check(
            "a second implementation recomputes both from the file alone",
            ex.verify_fingerprint(export) is True,
            str(ex.fingerprint(export)),
        )

        print("What moves it, and what does not")
        before = fp["sha256"]
        page.evaluate("S.meta.solution = 'A different solution'")
        moved = json.loads(page.evaluate("JSON.stringify(projectJSON(S))"))
        check(
            "a substantive change moves it",
            moved["fingerprint"]["sha256"] != before
            and moved["fingerprint"]["md5"] != fp["md5"],
        )
        check("and the new one still verifies", ex.verify_fingerprint(moved) is True)
        page.evaluate("S.meta.solution = " + json.dumps(awkward["meta"]["solution"]))
        page.evaluate("S.updatedAt = '2030-01-01T00:00:00Z'; S.updatedBy = 'someone'")
        same = json.loads(page.evaluate("JSON.stringify(projectJSON(S))"))
        check(
            "a new last-saved time does not",
            same["fingerprint"]["sha256"] == before,
            same["fingerprint"]["sha256"],
        )

        print("Editing the file is noticed")
        tampered = copy.deepcopy(export)
        tampered["_state"]["meta"]["scope"] += " (edited)"
        check(
            "an edited record fails to verify", ex.verify_fingerprint(tampered) is False
        )
        retitled = copy.deepcopy(export)
        retitled["project_id"] = "p-other"
        check(
            "so does a different project id", ex.verify_fingerprint(retitled) is False
        )
        legacy = copy.deepcopy(export)
        del legacy["fingerprint"]
        check(
            "an export with no fingerprint is reported as such, not as valid",
            ex.verify_fingerprint(legacy) is None,
        )

        print("The reports carry it, in the reader's language")
        digits = {"sha256": fp["sha256"], "md5": fp["md5"]}
        html = page.evaluate("exportHTML()")
        md = page.evaluate("exportMD()")
        check(
            "the HTML report (which the PDF prints) has both digests",
            digits["sha256"] in html and digits["md5"] in html,
        )
        check(
            "the Markdown report has both digests",
            digits["sha256"] in md and digits["md5"] in md,
        )
        label = page.evaluate("t('export.fingerprint', {sha256: 'X', md5: 'Y'})")
        german = page.evaluate(
            "withLocale('de', () => t('export.fingerprint', {sha256: 'X', md5: 'Y'}))"
        )
        check(
            "the label is a catalog entry that German translates",
            "SHA-256" in label and german != label and "SHA-256" in german,
            f"{label} | {german}",
        )
        page.evaluate("setLocale('de'); relocalize();")
        de_html = page.evaluate("exportHTML()")
        check(
            "a German report has the same digits and the German label",
            digits["sha256"] in de_html and german.split("X")[0].strip() in de_html,
        )
        page.evaluate("setLocale('en'); relocalize();")
        browser.close()

    print("The schema and the notice")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    props = schema.get("properties", {})
    sha = props.get("fingerprint", {}).get("properties", {}).get("sha256", {})
    check("the schema declares project_id", "project_id" in props)
    check(
        "and a SHA-256 of 64 hex digits",
        sha.get("pattern") in ("^[0-9a-f]{64}$", "[0-9a-f]{64}"),
        str(sha),
    )
    check(
        "the schema does not require it, so older exports still validate",
        "fingerprint" not in schema.get("required", []),
    )
    notice = json.loads(EN.read_text(encoding="utf-8"))["fp.warnDetail"]
    check(
        "the notice says a SHA-256 travels in the JSON export, and now it does",
        "A SHA-256 travels in the JSON export" in notice and bool(fp.get("sha256")),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("fingerprint checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
