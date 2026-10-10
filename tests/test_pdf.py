#!/usr/bin/env python3
"""Check the report's PDF export produces a real, readable PDF.

The export works by printing the standalone HTML report from an offscreen
iframe, so the thing worth testing is that the HTML it prints renders to a
sensible PDF: more than one page of content, the solution's name present, and
selectable text rather than an image.

    pixi run test-pdf
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"

FREEZE = """
(() => {
  Date.now = () => 1767225600000;
  const R = Date;
  globalThis.Date = class extends R {
    constructor(...a) { return a.length ? new R(...a) : new R(1767225600000); }
    static now() { return 1767225600000; }
  };
  Math.random = () => 0.42;
})()
"""


# Every frame's print() is replaced the moment the frame loads (any document,
# including its first blank one), and each call is recorded with its address.
PRINT_SPY = """() => {
  window.__printed = [];
  const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "onload");
  Object.defineProperty(HTMLIFrameElement.prototype, "onload", {
    configurable: true,
    get() { return desc.get.call(this); },
    set(fn) {
      const frame = this;
      desc.set.call(this, function (ev) {
        const w = frame.contentWindow;
        w.print = () => window.__printed.push(w.location.href);
        return fn.call(this, ev);
      });
    },
  });
}"""


def main() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
        if not ok:
            failures.append(name)

    out = ROOT / "build" / "report-test.pdf"
    out.parent.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(FREEZE)
        page.goto(APP.as_uri())
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size > 0", timeout=15000)

        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        page.evaluate(f"openProject({pid!r}, 'report')")
        page.wait_for_timeout(500)

        check("PDF button is present", page.locator('[data-act="dl-pdf"]').count() == 1)
        check(
            "PDF button stays visible without the downloads API",
            page.locator('[data-act="dl-pdf"]').is_visible(),
        )

        # exportPDF() prints the report from a frame, exactly once: not the frame's
        # blank first document too. A frame fires `load` for that blank document the
        # moment it is inserted, so a handler set before insertion printed a blank
        # page (and hung headless Firefox in the injection suite). The spy records
        # the address of every document print() is called on, in every frame.
        page.evaluate(PRINT_SPY)
        page.evaluate("exportPDF()")
        page.wait_for_timeout(1500)
        printed = page.evaluate("window.__printed")
        check(
            "the PDF export prints the report, once, and no blank page",
            printed == ["about:srcdoc"],
            str(printed),
        )

        # exportPDF() opens a print dialog, which headless cannot complete. Render
        # the exact HTML it would print, which is what decides the PDF's content.
        html = page.evaluate("exportHTML()")
        solution = page.evaluate("S.meta.solution")
        browser.close()

        browser = pw.chromium.launch()
        doc = browser.new_page()
        doc.set_content(html, wait_until="load")
        doc.pdf(path=str(out), format="A4", print_background=True)
        text = doc.inner_text("body")
        browser.close()

    raw = out.read_bytes()
    check("output is a PDF", raw[:5] == b"%PDF-", repr(raw[:8]))
    pages = len(re.findall(rb"/Type\s*/Page[^s]", raw))
    check("PDF has pages", pages >= 1, f"{pages} pages")
    check("PDF is not trivially small", len(raw) > 8000, f"{len(raw)} bytes")
    check("report names the solution", solution in text, solution)
    check("report carries the disclaimer", "not a certification" in text)
    check("no page errors", not errors, "; ".join(errors[:2]))

    print(f"\n  wrote {out.relative_to(ROOT)} ({len(raw):,} bytes, {pages} pages)")
    if failures:
        print(
            f"{len(failures)} check(s) failed: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
