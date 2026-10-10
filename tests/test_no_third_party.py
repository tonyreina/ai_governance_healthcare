#!/usr/bin/env python3
"""The dashboard and its exports must not contact a third party.

This is a tool whose subject is where regulated data goes, run on networks that
often filter egress. A webfont link meant every page load -- and every open of
an exported report, which is the artifact that gets emailed around a hospital
-- announced itself to Google.

It is also what lets the Content-Security-Policy in proxy/Caddyfile be as
tight as it is.

    pixi run test-no-3p
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def external(urls: list[str]) -> list[str]:
    out = []
    for url in urls:
        scheme = urlsplit(url).scheme
        if scheme in ("http", "https"):
            out.append(url)
    return out


# What loads without a click: a stylesheet, script, image, font, frame or beacon. A
# link the reader chooses to follow (`<a href>`) is not a request the page makes, so it
# is allowed in an export (a report may link to the evidence it cites).
RESOURCE = re.compile(
    r"""(?:\bsrc\s*=|<link\b|@import|\burl\(|\bsrcset\s*=|\bposter\s*=|<object\b|<embed\b)"""
    r"""[^>]*?https?://""",
    re.I,
)


def resource_urls(text: str) -> list[str]:
    """Anything in an export that a viewer would fetch on its own."""
    return [m.group(0)[:80] for m in RESOURCE.finditer(text)]


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        requested: list[str] = []
        page.on("request", lambda r: requested.append(r.url))

        page.goto(APP.as_uri())
        page.wait_for_timeout(1200)

        off_origin = external(requested)
        check(
            "loading the dashboard makes no external request",
            not off_origin,
            ", ".join(off_origin[:3]),
        )

        print("Every screen, dialog, language and export")
        walk = browser.new_page()
        seen: list[str] = []
        walk.on("request", lambda r: seen.append(r.url))
        walk.goto(APP.as_uri())
        walk.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        walk.evaluate("loadSamples()")
        walk.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        # A deployed, a piloted and an early project, each with OPTICA on, so every view
        # exists: the setup page, the six stages, the checkpoints, the model card, the
        # report, the change log and the OPTICA chapters.
        views_seen = 0
        for index in (0, 1, 2):
            walk.evaluate(f"openProject([...PROJECTS.keys()][{index}], 'setup')")
            walk.evaluate("setFrameworkEnabled('optica', true)")
            for view in walk.evaluate("activeViews().map(v => v.id)"):
                walk.evaluate("(v) => go(v)", view)
                walk.wait_for_timeout(15)
                views_seen += 1
            walk.evaluate(
                "renderLabel(); document.getElementById('panel').classList.add('open')"
            )
        check("every view was visited", views_seen > 60, str(views_seen))
        walk.evaluate("goHome()")
        walk.evaluate("UI.q = 'sepsis'; UI.qAll = true; updateDashboard()")
        walk.evaluate(
            "openProject([...PROJECTS.keys()][0], 'setup'); openDeleteDialog()"
        )
        walk.keyboard.press("Escape")
        # The picker in the header, and every language it offers.
        for locale in walk.evaluate("LOCALE_CHOICES"):
            walk.evaluate(
                "(l) => { setLocale(l); relocalize(); go('report'); }", locale
            )
            walk.wait_for_timeout(30)
        walk.evaluate("setLocale('en'); relocalize();")
        outputs = walk.evaluate(
            """() => ({
                html: exportHTML(), md: exportMD(), csv: exportCSV(),
                json: JSON.stringify(projectJSON(S)),
            })"""
        )
        # The PDF is the report loaded into a frame of the page: its requests count too.
        walk.evaluate("exportPDF()")
        walk.wait_for_timeout(500)
        # A tool the user can press that talks to nothing: import, search, add, archive.
        walk.evaluate("goHome()")
        walk.wait_for_timeout(200)
        offsite = external(seen)
        check(
            "no screen, dialog, language or export makes a request to another host",
            not offsite,
            ", ".join(offsite[:3]),
        )
        check(
            "and the page made no request at all once loaded, apart from its own file",
            all(urlsplit(u).scheme in ("file", "data", "blob", "about") for u in seen),
            ", ".join(
                u
                for u in seen
                if urlsplit(u).scheme not in ("file", "data", "blob", "about")
            )[:100],
        )

        print("What the exports would fetch when opened")
        for name in ("html", "md", "csv", "json"):
            found = resource_urls(outputs[name])
            check(
                f"the {name} export loads no outside resource",
                not found,
                "; ".join(found[:2]),
            )
        check(
            "the Markdown export has no image (an image is a request when it is read)",
            not re.search(r"(?<!\\)!\[", outputs["md"]),
        )
        reader = browser.new_page()
        opened: list[str] = []
        reader.on("request", lambda r: opened.append(r.url))
        saved = Path(tempfile.mkdtemp(prefix="chai-3p-")) / "report.html"
        saved.write_text(outputs["html"], encoding="utf-8")
        reader.goto(saved.as_uri())
        reader.wait_for_timeout(500)
        check(
            "opening the saved report makes no request to another host",
            not external(opened),
            ", ".join(external(opened)[:3]),
        )

        print("The check notices a request, and a resource (mutation)")
        # The page's own policy refuses these requests (connect-src and img-src are
        # 'self'), which is the point of it. The probe bypasses the policy so that this
        # test shows its own detector can see a request, whatever stopped it.
        probe = browser.new_context(bypass_csp=True).new_page()
        probed: list[str] = []
        probe.on("request", lambda r: probed.append(r.url))
        probe.goto(APP.as_uri())
        probe.evaluate("fetch('https://tracker.example/x').catch(() => {})")
        probe.evaluate("new Image().src = 'https://tracker.example/p.gif'")
        probe.wait_for_timeout(300)
        check(
            "a fetch and an image to another host are both seen",
            len(external(probed)) >= 2,
            str(probed),
        )
        check(
            "a stylesheet link, an image and a CSS url() in an export are noticed",
            len(
                resource_urls(
                    '<link rel=stylesheet href="https://x.example/a.css"><img src="https://x.example/p.png"><style>a{background:url(https://x.example/b.png)}</style>'
                )
            )
            == 3,
        )
        check(
            "a plain hyperlink in a report is not a resource",
            not resource_urls(
                '<a href="https://hospital.example/doc.pdf">the validation report</a>'
            ),
        )

        # The export is generated from the live page, so check its text too.
        page.evaluate(
            """() => {
                S = normalize(blankProject("Sepsis early warning"));
                CUR = "x";
            }"""
        )
        html = page.evaluate("() => exportHTML()")
        check(
            "the HTML export links no external stylesheet",
            "<link" not in html.lower() or "fonts.googleapis" not in html,
            "export still references an external origin",
        )
        check(
            "the HTML export has no http(s) resource URLs at all",
            not resource_urls(html),
            "; ".join(resource_urls(html)[:2]),
        )
        check("the export still carries its inline styles", "<style>" in html)
        check(
            "the export still names the project",
            "Sepsis early warning" in html,
        )

        # Rendering must not have fallen back to a serif default.
        family = page.evaluate("() => getComputedStyle(document.body).fontFamily")
        check(
            "body still resolves a sans-serif stack",
            "sans-serif" in family or "system-ui" in family,
            family,
        )
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("no third-party contact checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
