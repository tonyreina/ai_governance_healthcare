#!/usr/bin/env python3
"""The page says when its server retires records by other rules (#168, D-83).

The server decides when a project is retired, and so when its record comes due for
disposal, from the rules loaded out of the manifest.json built beside the page
(D-76). The build embeds the same manifest's `ruleSetHash` in the page
(`BUILD.ruleSetHash`), and in API mode the page compares it, and its primary, with
`/api/health`'s `retirement_rules` (`{hash, primary, synced}`).

Drives the real built page in Chromium against a stand-in API, and checks:

  - the embedded hash is the manifest's, for the published build and for a build of
    the example framework made into a temporary --out;
  - nothing is shown when the rules agree, when the server sends no
    `retirement_rules` (or null), and from a file (local mode, no server);
  - a different hash, a different primary, and `synced: false` each show a banner
    with its own sentence; a disagreement is an alert (role=alert) and stops a
    decision and a new record, while `synced: false` alone is a status and stops
    nothing;
  - anything but exactly the page's values is a difference: a hash differing in
    one character, a missing hash or primary, a primary the page's is a prefix
    of, a `synced` that is not `true`, and a `retirement_rules` that is not an
    object at all (blocking);
  - each banner's title, visibility and blocking style; the disabled decision
    buttons described by the banner; "other changes still save" said only to a
    person who may edit the open project;
  - the server's words are text, never markup;
  - the banner is inserted empty and filled after, so it is announced; a change
    of language changes its words in place, in one element, for the published
    build and the example; in Hebrew it reads left to right while its sentences
    are English;
  - and mutations of the built pages (MUTATIONS, EXAMPLE_MUTATIONS) each fail
    some check, so the checks are shown to bite.

    pixi run test-rules-banner
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import json
import re
import shutil
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
APP = DOCS / "app" / "index.html"
MANIFEST = DOCS / "app" / "manifest.json"
EXAMPLE_CONFIG = ROOT / "app" / "frameworks" / "example" / "build.json"
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402

failures: list[str] = []


class Run:
    """Collects the failures of one pass over the scenarios."""

    def __init__(self, loud: bool) -> None:
        self.loud = loud
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        if self.loud:
            print(
                f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}"
            )
        if not ok:
            self.failed.append(name)


@contextlib.contextmanager
def serve(directory: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        httpd.allow_reuse_address = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()


ABSENT = object()  # the server sends no retirement_rules at all


def build_stamp(build: dict) -> dict | None:
    """The stamp a build writes on its records: none for the published build (its
    records are CHAI's), its primary for a build of other frameworks (R-67)."""
    return None if build["primary"] == "chai" else {"id": build["primary"]}


def boot(
    browser, url: str, rules: object, stamp: dict | None = None, reader: bool = False
):
    """Boot the page at `url` against a stand-in API whose health reports `rules`.
    With `reader`, the signed-in person may only read the project. Returns the page
    and the list of writes (method, path) it sent."""
    health = {
        "status": "ok",
        "version": "t",
        "database": "up",
        "db_role": "restricted",
        "auth_mode": "proxy-header:proxy",
    }
    if rules is not ABSENT:
        health["retirement_rules"] = rules
    meta: dict = {"solution": "Rules banner project"}
    if stamp:
        meta["framework"] = stamp
    listed: list[dict] = [{"id": "p1", "meta": meta}]
    if reader:
        listed[0]["access"] = {"owners": ["o@b"], "writers": [], "readers": ["a@b"]}
    writes: list[tuple[str, str]] = []
    page = browser.new_page(viewport={"width": 1300, "height": 900})
    page.set_default_timeout(6000)
    page.on(
        "request",
        lambda r: (
            writes.append((r.method, r.url))
            if r.method in ("POST", "PATCH", "DELETE")  # enum-ok: HTTP methods
            and "/api/projects/" in r.url
            and not r.url.endswith("/log")
            else None
        ),
    )
    page.route(
        "**/api/health",
        lambda r: r.fulfill(
            status=200, body=json.dumps(health), content_type="application/json"
        ),
    )
    page.route(
        "**/api/me",
        lambda r: r.fulfill(
            status=200,
            body='{"id":"a@b","name":"A B","email":"a@b","dev":false}',
            content_type="application/json",
        ),
    )
    page.route(
        "**/api/projects",
        lambda r: r.fulfill(
            status=200,
            body=json.dumps(listed),
            content_type="application/json",
        ),
    )
    page.route(
        "**/api/projects/**",
        lambda r: r.fulfill(status=200, body="{}", content_type="application/json"),
    )
    page.route("**/api/events", lambda r: r.abort())
    # Whether the banner got its words after it entered the page: a live region
    # inserted already full is not reliably announced (role=status above all).
    page.add_init_script(
        """(() => {
          window.__rulesFilledLive = null;
          new MutationObserver(records => {
            const b = document.getElementById('rulesBanner');
            if (!b) return;
            for (const r of records) {
              // Seen after the task that inserted it: empty then, filled later.
              if ([...r.addedNodes].includes(b) && window.__rulesFilledLive === null)
                window.__rulesFilledLive = b.textContent === '';
            }
          }).observe(document, {childList: true, subtree: true, characterData: true});
        })()"""
    )
    page.goto(url)
    page.wait_for_function(
        "() => typeof LOADED !== 'undefined' && LOADED", timeout=15000
    )
    page.wait_for_function("() => MODE === Mode.API")
    page.wait_for_timeout(200)
    return page, writes


def banner(page) -> dict | None:
    return page.evaluate(
        """() => {
          const b = document.getElementById('rulesBanner');
          if (!b) return null;
          const head = b.querySelector('b');
          const st = getComputedStyle(b);
          return {
            role: b.getAttribute('role'),
            text: b.textContent,
            title: head ? head.textContent : null,
            lines: [...b.querySelectorAll('[data-rules]')].map(e => e.dataset.rules),
            elements: b.querySelectorAll('img,script,a').length,
            blocking: b.classList.contains('blocking'),
            visible: st.display !== 'none' && st.visibility !== 'hidden'
              && b.getBoundingClientRect().height > 0,
            count: document.querySelectorAll('#rulesBanner').length,
            filledLive: window.__rulesFilledLive,
          };
        }"""
    )


def try_decision(page) -> tuple[bool, bool]:
    """Open the project's first decision and press its first option, even if the
    button was disabled (the handler must refuse too). Returns (the button was
    disabled, the decision was recorded)."""
    page.evaluate("openProject('p1', 'g' + spine().gates()[0].id)")
    page.wait_for_timeout(150)
    return page.evaluate(
        """() => {
          const b = document.querySelector('[data-gate]');
          if (!b) return [null, null];
          const disabled = b.disabled;
          b.disabled = false;
          b.click();
          const g = (S.gates || {})[b.dataset.gate] || {};
          return [disabled, g.decision === b.dataset.d];
        }"""
    )


def decision_described(page) -> list:
    """The aria-describedby of each decision button of the open project, and
    whether each names an element that exists."""
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-gate]')].map(b => {
          const id = b.getAttribute('aria-describedby');
          const ids = id ? id.split(/\\s+/) : [];
          return [id, ids.length > 0 && ids.every(i => document.getElementById(i))];
        })"""
    )


TITLE = "This page and its server disagree about when records are retired."
TITLE_UNSYNCED = "The server's retirement rules were not confirmed against this page."
OTHERS_SAVE = "Other changes still save."


def try_create(page, writes) -> bool:
    """Create a record; whether a POST for it reached the server."""
    before = sum(1 for m, _ in writes if m == "POST")  # enum-ok: HTTP method
    page.evaluate("createProject(blankProject('made under the banner'), 'test')")
    page.wait_for_timeout(300)
    return sum(1 for m, _ in writes if m == "POST") > before  # enum-ok: HTTP method


def scenarios(browser, url: str, build: dict, run: Run) -> None:
    """Every case against the page at `url`, whose build is `build` (its manifest)."""
    check = run.check
    page_hash, primary = build["ruleSetHash"], build["primary"]
    other = "zz-other" if primary != "zz-other" else "zz-another"

    def go(rules, reader=False):
        return boot(browser, url, rules, stamp=build_stamp(build), reader=reader)

    def last_char_differs(h: str) -> str:
        return h[:-1] + ("0" if h[-1] != "0" else "1")

    page, writes = go({"hash": page_hash, "primary": primary, "synced": True})
    check(
        "the page embeds its manifest's rule-set hash",
        page.evaluate("BUILD.ruleSetHash") == page_hash,
        str(page.evaluate("BUILD.ruleSetHash")),
    )
    check("rules that agree show no banner", banner(page) is None, str(banner(page)))
    disabled, recorded = try_decision(page)
    check("and a decision can be recorded", disabled is False and recorded is True)
    check("and a record can be created", try_create(page, writes))
    page.close()

    page, writes = go({"hash": "0" * 64, "primary": primary, "synced": True})
    b = banner(page) or {}
    check("a different hash shows the banner", bool(b), str(b))
    check("as an alert", b.get("role") == "alert", str(b.get("role")))
    check(
        "headed by the disagreement's own title",
        b.get("title") == TITLE,
        str(b.get("title")),
    )
    check("which can be seen", b.get("visible") is True, str(b))
    check("styled as blocking", b.get("blocking") is True, str(b))
    check(
        "filled after it entered the page, so a screen reader announces it",
        b.get("filledLive") is True,
        str(b),
    )
    check(
        "saying the server retires by different rules",
        b.get("lines") == ["hash"]
        and "different rules than this page shows" in b.get("text", "")
        and "manifest.json" in b.get("text", ""),
        str(b),
    )
    check(
        "and that decisions and new records stop",
        "records no decision and creates no new record" in b.get("text", ""),
        b.get("text", ""),
    )
    disabled, recorded = try_decision(page)
    check("its decision buttons are disabled", disabled is True, str(disabled))
    described = decision_described(page)
    check(
        "and each names the banner as what describes it",
        bool(described) and all(d == ["rulesBanner", True] for d in described),
        str(described),
    )
    b = banner(page) or {}
    check(
        "a person who can edit the project is told other changes still save",
        OTHERS_SAVE in b.get("text", "") and b.get("count") == 1,
        str(b),
    )
    check("and a decision is refused even if pressed", recorded is False)
    check(
        "no decision reaches the server",
        not any(m == "PATCH" for m, _ in writes),  # enum-ok: HTTP method
        str(writes),
    )
    check("a new record is refused", not try_create(page, writes), str(writes))
    page.evaluate("edit('meta.sponsor', 'edited under the banner'); flush(CUR)")
    page.wait_for_timeout(300)
    check(
        "other edits still save",
        any(m == "PATCH" for m, _ in writes),  # enum-ok: HTTP method
        str(writes),
    )
    page.close()

    page, writes = go({"hash": "0" * 64, "primary": other, "synced": True})
    b = banner(page) or {}
    check("a different primary shows the banner", bool(b), str(b))
    check("as an alert too", b.get("role") == "alert", str(b.get("role")))
    check(
        "naming both frameworks, in its own sentence",
        b.get("lines") == ["primary"]
        and f'"{other}"' in b.get("text", "")
        and f'"{primary}"' in b.get("text", ""),
        str(b),
    )
    check(
        "the server's framework as the server's, the page's as the page's",
        f'the framework "{other}", but this page was built for "{primary}"'
        in b.get("text", ""),
        b.get("text", ""),
    )
    check("under the disagreement's title", b.get("title") == TITLE, str(b))
    disabled, recorded = try_decision(page)
    check(
        "a decision is refused under another primary",
        disabled is True and recorded is False,
    )
    check("a new record is refused under another primary", not try_create(page, writes))
    page.close()

    page, writes = go({"hash": page_hash, "primary": primary, "synced": False})
    b = banner(page) or {}
    check("unsynced rules show the banner", bool(b), str(b))
    check(
        "as a status, not an alert",
        b.get("role") == "status",
        str(b.get("role")),
    )
    check(
        "headed by its own title, not the disagreement's",
        b.get("title") == TITLE_UNSYNCED,
        str(b.get("title")),
    )
    check(
        "seen, and not styled as blocking",
        b.get("visible") is True and b.get("blocking") is False,
        str(b),
    )
    check(
        "and filled after it entered the page, so it is announced",
        b.get("filledLive") is True,
        str(b),
    )
    check(
        "saying no build's manifest set them",
        b.get("lines") == ["unsynced"]
        and "No build's manifest.json set or confirmed" in b.get("text", ""),
        str(b),
    )
    disabled, recorded = try_decision(page)
    check(
        "and stopping nothing: the rules held are the page's",
        disabled is False and recorded is True,
    )
    check("a record can still be created", try_create(page, writes))
    page.close()

    page, _ = go({"hash": "0" * 64, "primary": other, "synced": False})
    b = banner(page) or {}
    check(
        "both problems at once: both sentences, and an alert",
        b.get("lines") == ["primary", "unsynced"] and b.get("role") == "alert",
        str(b),
    )
    page.close()

    # Every way the server's answer can differ from the page's, however slightly.
    # A missing field, or one of the wrong type, is not taken as agreement.
    for label, rules, lines in (
        (
            "a hash differing in its last character",
            {"hash": last_char_differs(page_hash), "primary": primary, "synced": True},
            ["hash"],
        ),
        (
            "no hash",
            {"primary": primary, "synced": True},
            ["hash"],
        ),
        (
            "no primary",
            {"hash": page_hash, "synced": True},
            ["primary"],
        ),
        (
            "a primary the page's is a prefix of",
            {"hash": page_hash, "primary": primary + "-v2", "synced": True},
            ["primary"],
        ),
        (
            "rules that are a string",
            "not rules",
            ["hash"],
        ),
        ("rules that are true", True, ["hash"]),
        ("rules that are false", False, ["hash"]),
        ("rules that are a number", 0, ["hash"]),
        ("rules that are a list", [page_hash, primary], ["hash"]),
    ):
        page, writes = go(rules)
        b = banner(page) or {}
        check(
            f"{label}: a disagreement, blocking",
            b.get("lines") == lines
            and b.get("role") == "alert"
            and b.get("title") == TITLE
            and b.get("blocking") is True
            and page.evaluate("rulesBlockWrites()"),
            str(b),
        )
        page.close()

    for label, rules in (
        ("no synced field", {"hash": page_hash, "primary": primary}),
        (
            'synced as the string "false"',
            {"hash": page_hash, "primary": primary, "synced": "false"},
        ),
        ("synced as 1", {"hash": page_hash, "primary": primary, "synced": 1}),
    ):
        page, _ = go(rules)
        b = banner(page) or {}
        check(
            f"{label}: unsynced, a status",
            b.get("lines") == ["unsynced"] and b.get("role") == "status",
            str(b),
        )
        page.close()

    # A person who may only read the project is not told their changes save.
    page, writes = go({"hash": "0" * 64, "primary": primary, "synced": True}, True)
    page.evaluate("openProject('p1', 'setup')")
    page.wait_for_timeout(200)
    b = banner(page) or {}
    check(
        "a read-only person is not told other changes still save",
        bool(b)
        and page.evaluate("RO") is True
        and OTHERS_SAVE not in b.get("text", "")
        and "records no decision and creates no new record" in b.get("text", ""),
        str(b),
    )
    page.close()

    for label, rules in (("no retirement_rules", ABSENT), ("null rules", None)):
        page, _ = go(rules)
        check(
            f"a server that sends {label} shows nothing",
            banner(page) is None,
            str(banner(page)),
        )
        page.close()

    hostile = '<img src=x onerror="window.__pwned=1">'
    page, _ = go({"hash": "x", "primary": hostile, "synced": True})
    b = banner(page) or {}
    check(
        "the server's words are text, never markup",
        hostile in b.get("text", "")
        and b.get("elements") == 0
        and not page.evaluate("window.__pwned"),
        str(b),
    )
    page.close()


def load_sweep(browser, run: Run) -> None:
    """What is not a scenario of the API: the file, a change of language."""
    check = run.check
    page = browser.new_page()
    page.goto(APP.as_uri())
    page.wait_for_function(
        "() => typeof LOADED !== 'undefined' && LOADED", timeout=15000
    )
    page.wait_for_timeout(200)
    check(
        "from a file (local mode, no server) nothing is shown",
        page.evaluate(
            "MODE === Mode.LOCAL && RULES_PROBLEMS.length === 0"
            " && !document.getElementById('rulesBanner')"
        ),
    )
    check(
        "and nothing is stopped",
        page.evaluate("!rulesBlockWrites()"),
    )
    page.close()


def language_sweep(browser, url: str, build: dict, run: Run) -> None:
    """A change of language puts the banner's words in the new language, in place.
    The pseudo-locale is used because the banner's sentences are safety-bearing, so
    a real language shows them in English until a reviewer is recorded (D-59)."""
    page, _ = boot(
        browser,
        url,
        {"hash": "0" * 64, "primary": build["primary"], "synced": True},
        stamp=build_stamp(build),
    )
    page.evaluate("window.__rulesBanner = document.getElementById('rulesBanner')")
    page.evaluate("setLocale(Locale.PSEUDO); relocalize()")
    page.wait_for_timeout(200)
    b = banner(page) or {}
    run.check(
        "the banner is drawn again in the new language",
        b.get("lines") == ["hash"]
        and b.get("role") == "alert"
        and "different rules than this page shows" not in b.get("text", "")
        and b.get("count") == 1,
        str(b),
    )
    run.check(
        "in the same element, not removed and inserted again (an alert announced anew)",
        page.evaluate(
            "window.__rulesBanner === document.getElementById('rulesBanner')"
        ),
    )
    # However often it is asked for, there is one banner.
    disagreeing = {"hash": "0" * 64, "primary": build["primary"], "synced": True}
    page.evaluate(
        "relocalize(); relocalize(); showRulesBanner();"
        " checkRetirementRules({retirement_rules:"
        f" {json.dumps(disagreeing)}}})"
    )
    page.wait_for_timeout(200)
    b = banner(page) or {}
    run.check(
        "drawn again and checked again, there is still one banner",
        b.get("count") == 1 and b.get("lines") == ["hash"],
        str(b),
    )
    # Hebrew: the banner's sentences stay English until reviewed, and the banner
    # reads in one direction, not each sentence aligned its own way.
    page.evaluate("setLocale(Locale.HE); relocalize()")
    page.wait_for_timeout(200)
    shape = page.evaluate(
        """() => {
          const b = document.getElementById('rulesBanner');
          const parts = [...b.children];
          return {
            page: document.documentElement.dir,
            ltr: b.matches(':dir(ltr)'),
            same: parts.every(e => e.matches(':dir(ltr)') === b.matches(':dir(ltr)')),
            plaintext: parts.filter(
              e => getComputedStyle(e).unicodeBidi === 'plaintext').length,
          };
        }"""
    )
    run.check(
        "in Hebrew, the English banner reads left to right, every part alike",
        shape == {"page": "rtl", "ltr": True, "same": True, "plaintext": 0},
        str(shape),
    )
    page.close()


CSP_META = re.compile(r'<meta http-equiv="Content-Security-Policy"[^>]*>')

# Each breaks one thing the page must do; each must fail some check above.
MUTATIONS: list[tuple[str, str, str]] = [
    (
        "the hash compared with the wrong field",
        "rules.hash !== build.ruleSetHash",
        "rules.hash !== build.primary",
    ),
    (
        "the primary check skipped",
        "if(rules.primary !== build.primary) out.push(RulesProblem.PRIMARY);\n  else ",
        "",
    ),
    (
        "synced ignored",
        "if(rules.synced !== true) out.push(RulesProblem.UNSYNCED);",
        "",
    ),
    (
        "the decision's refusal dropped",
        'if(rulesBlockWrites()){ toast(t("rules.refused")); return; }',
        "",
    ),
    (
        "the decision buttons left enabled",
        'if(rulesBlockWrites()) root.querySelectorAll("[data-gate]")',
        'if(false) root.querySelectorAll("[data-gate]")',
    ),
    (
        "the new record's refusal dropped",
        'if(rulesBlockWrites()){ toast(t("rules.refused")); return null; }',
        "",
    ),
    (
        "the alert role dropped",
        'el.setAttribute("role", blocking ? "alert" : "status");',
        'el.setAttribute("role", "status");',
    ),
    # Each of these lets through a server that is not the page's.
    (
        "synced compared as not false, rather than as true",
        "rules.synced !== true",
        "rules.synced === false",
    ),
    (
        "synced taken by truthiness",
        "rules.synced !== true",
        "!rules.synced",
    ),
    (
        "a missing hash taken as agreement",
        "rules.hash !== build.ruleSetHash",
        "rules.hash && rules.hash !== build.ruleSetHash",
    ),
    (
        "a missing primary taken as agreement",
        "rules.primary !== build.primary",
        "rules.primary && rules.primary !== build.primary",
    ),
    (
        "the hash compared by its first character",
        "rules.hash !== build.ruleSetHash",
        "String(rules.hash)[0] !== String(build.ruleSetHash)[0]",
    ),
    (
        "the primary compared by prefix",
        "rules.primary !== build.primary",
        "!String(rules.primary).startsWith(build.primary)",
    ),
    (
        "a malformed answer taken as agreement",
        'if(typeof rules !== "object" || Array.isArray(rules))'
        " return [RulesProblem.HASH];",
        'if(typeof rules !== "object" || Array.isArray(rules)) return [];',
    ),
    # Each of these says it wrongly, or hides it.
    (
        "the page's and the server's frameworks swapped in the sentence",
        "{page: BUILD.primary, server: RULES_SERVER_PRIMARY}",
        "{page: RULES_SERVER_PRIMARY, server: BUILD.primary}",
    ),
    (
        "the two titles swapped",
        't(blocking ? "rules.title" : "rules.titleUnsynced")',
        't(blocking ? "rules.titleUnsynced" : "rules.title")',
    ),
    (
        "the title dropped",
        't(blocking ? "rules.title" : "rules.titleUnsynced")',
        '""',
    ),
    (
        "the banner hidden",
        'el.dir = "auto";',
        'el.dir = "auto"; el.style.display = "none";',
    ),
    (
        "the blocking style dropped",
        '(blocking ? " blocking" : "")',
        '""',
    ),
    (
        "other changes said to save to a person who may only read",
        "if(S && !RO) parts",
        "if(true) parts",
    ),
    (
        "what is said to save never brought up to date as a project opens",
        "  fillRulesBanner();   // whether",
        "  // whether",
    ),
    (
        "the disabled decision buttons not described by the banner",
        'e.setAttribute("aria-describedby", "rulesBanner"); ',
        "",
    ),
    (
        "the banner inserted already full",
        "  setTimeout(fillRulesBanner, 50);",
        "  fillRulesBanner();",
    ),
    (
        "the banner removed and inserted again on every redraw",
        'let el = document.getElementById("rulesBanner");',
        'let el = document.getElementById("rulesBanner");'
        " if(el){ el.remove(); el = null; }",
    ),
    (
        "the banner's direction not set from its words",
        'el.dir = "auto";',
        "",
    ),
    (
        "the banner's words never changed once written (a change of language)",
        "if(part.textContent !== text) part.textContent = text;",
        "if(!part.textContent) part.textContent = text;",
    ),
]

# Caught only where the build's primary is not the published one, so run against
# the example's page: the published build's primary and legacy framework are both
# CHAI, and a check against the wrong one would pass there.
EXAMPLE_MUTATIONS: list[tuple[str, str, str]] = [
    (
        "the primary compared with the legacy framework",
        "rules.primary !== build.primary",
        "rules.primary !== build.legacy",
    ),
    (
        "the page's own primary taken from the published build",
        "{page: BUILD.primary, server: RULES_SERVER_PRIMARY}",
        '{page: "chai", server: RULES_SERVER_PRIMARY}',
    ),
]


def mutant(html: str, old: str, new: str) -> str:
    if html.count(old) != 1:
        raise SystemExit(f"mutation target not found exactly once: {old!r}")
    html = html.replace(old, new)
    # The page names its script by hash; a mutated script needs its own policy.
    return CSP_META.sub(lambda _: build_app.csp_meta(html), html, count=1)


def main() -> int:
    published = json.loads(MANIFEST.read_text(encoding="utf-8"))
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as tmp:
        browser = pw.chromium.launch()
        run = Run(loud=True)

        print("The published build")
        with serve(DOCS) as base:
            scenarios(browser, base + "/app/index.html", published, run)
            language_sweep(browser, base + "/app/index.html", published, run)
        load_sweep(browser, run)

        print("A build of the example framework, into a temporary --out")
        out = Path(tmp) / "example"
        code = build_app.main(["--config", str(EXAMPLE_CONFIG), "--out", str(out)])
        run.check("the example builds", code == 0, str(code))
        example = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        run.check(
            "its manifest has its own primary and rule set",
            example["primary"] == "example"
            and example["ruleSetHash"] != published["ruleSetHash"],
            str(example.get("primary")),
        )
        with serve(out) as base:
            scenarios(browser, base + "/index.html", example, run)
            language_sweep(browser, base + "/index.html", example, run)
            # The published build's server, under the example's page.
            page, _ = boot(
                browser,
                base + "/index.html",
                {
                    "hash": published["ruleSetHash"],
                    "primary": published["primary"],
                    "synced": True,
                },
            )
            b = banner(page) or {}
            run.check(
                "the example's page on the published build's server says so",
                b.get("lines") == ["primary"] and '"example"' in b.get("text", ""),
                str(b),
            )
            page.close()
        failures.extend(run.failed)

        print("Mutations of the built pages, each of which must be caught")
        targets = [
            (APP, published, MUTATIONS),
            (out / "index.html", example, EXAMPLE_MUTATIONS),
        ]
        for page_file, build, mutations in targets:
            original = page_file.read_text(encoding="utf-8")
            for name, old, new in mutations:
                site = Path(tmp) / "mutant" / "app"
                if site.exists():
                    shutil.rmtree(site)
                site.mkdir(parents=True)
                (site / "index.html").write_text(mutant(original, old, new), "utf-8")
                quiet = Run(loud=False)
                with serve(site.parent) as base:
                    scenarios(browser, base + "/app/index.html", build, quiet)
                    language_sweep(browser, base + "/app/index.html", build, quiet)
                caught = bool(quiet.failed)
                print(
                    f"  {'PASS' if caught else 'FAIL'}  caught: {name}"
                    + (f" ({quiet.failed[0]})" if caught else "  <- every check passed")
                )
                if not caught:
                    failures.append(f"mutation not caught: {name}")
        browser.close()

    print()
    if failures:
        print(
            f"{len(failures)} check(s) failed: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
