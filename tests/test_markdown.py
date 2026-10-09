#!/usr/bin/env python3
"""Restricted Markdown in notes: formatting yes, markup never (R-62, D-71).

The evidence and rationale fields take a small subset (bold, italic, lists and
http(s) links). Both outputs, the HTML a reader sees and the Markdown a file
carries, are written from one parsed tree, so what has to hold is stated in
terms of that tree:

  * the examples below read the way a person expects;
  * for ANY text, the HTML contains only the tags the subset has, every link is
    http or https, and no attribute but the three on a link exists (a fuzz over
    the characters that matter, and the attack strings);
  * the Markdown never contains raw HTML, an image, a heading or a table row
    that the text did not start, and its links are the HTML's links;
  * it is fast on input built to make a regular expression crawl;
  * and a mutation shows the checks notice when the rules are weakened.

    pixi run test-markdown
"""

from __future__ import annotations

import random
import re
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def wait_until(page, expr: str, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(f"() => !!({expr})"):
            return
        page.wait_for_timeout(100)
    raise TimeoutError(expr)


MD_EXAMPLES = [
    ("**bold** and *it*", "**bold** and *it*"),
    ("a | b", "a \\| b"),
    ("- one\n- two", "\u2022 one \u2022 two"),
    ("line one\nline two", "line one line two"),
    ("<b>x</b>", "\\<b\\>x\\</b\\>"),
    (
        "![i](https://t.example/p.png)",
        "\\![i](https://t.example/p.png) \\(https://t.example/p.png\\)",
    ),
    ("[a](https://x.example/p(q))", "\\[a\\]\\(https://x.example/p\\(q\\)\\)"),
    ("[a](javascript:1)", "\\[a\\]\\(javascript:1\\)"),
]
LINK_ATTRS = 'target="_blank" rel="noopener noreferrer nofollow"'

EXAMPLES = [
    ("plain words", "<p><bdi>plain words</bdi></p>"),
    (
        "**bold** and *italic*",
        "<p><bdi><strong>bold</strong> and <em>italic</em></bdi></p>",
    ),
    ("_italic_ here", "<p><bdi><em>italic</em> here</bdi></p>"),
    ("snake_case_name stays", "<p><bdi>snake_case_name stays</bdi></p>"),
    ("2 * 3 * 4", "<p><bdi>2 * 3 * 4</bdi></p>"),
    ("**unclosed", "<p><bdi>**unclosed</bdi></p>"),
    ("line one\nline two", "<p><bdi>line one<br>line two</bdi></p>"),
    ("para one\n\npara two", "<p><bdi>para one</bdi></p><p><bdi>para two</bdi></p>"),
    ("- a\n- b", "<ul><li><bdi>a</bdi></li><li><bdi>b</bdi></li></ul>"),
    ("1. a\n2. b", "<ol><li><bdi>a</bdi></li><li><bdi>b</bdi></li></ol>"),
    ("* star\n+ plus", "<ul><li><bdi>star</bdi></li><li><bdi>plus</bdi></li></ul>"),
    (
        "intro\n- a\noutro",
        "<p><bdi>intro</bdi></p><ul><li><bdi>a</bdi></li></ul><p><bdi>outro</bdi></p>",
    ),
    (
        "[report](https://example.org/r)",
        f'<p><bdi><a href="https://example.org/r" {LINK_ATTRS}>report</a> '
        '<span class="md-url">(https://example.org/r)</span></bdi></p>',
    ),
    (
        "[https://example.org/](https://example.org/)",
        f'<p><bdi><a href="https://example.org/" {LINK_ATTRS}>https://example.org/</a></bdi></p>',
    ),
    ("[x](javascript:alert(1))", "<p><bdi>[x](javascript:alert(1))</bdi></p>"),
    ("[x](data:text/html,hi)", "<p><bdi>[x](data:text/html,hi)</bdi></p>"),
    ("[x](//evil.example)", "<p><bdi>[x](//evil.example)</bdi></p>"),
    (
        "[x](https://u:p@evil.example/)",
        "<p><bdi>[x](https://u:p@evil.example/)</bdi></p>",
    ),
    (
        "![alt](https://t.example/p.png)",
        '<p><bdi>!<a href="https://t.example/p.png" '
        + LINK_ATTRS
        + '>alt</a> <span class="md-url">(https://t.example/p.png)</span></bdi></p>',
    ),
    (
        "<b>x</b> <script>1</script>",
        "<p><bdi>&lt;b&gt;x&lt;/b&gt; &lt;script&gt;1&lt;/script&gt;</bdi></p>",
    ),
    ("# not a heading", "<p><bdi># not a heading</bdi></p>"),
    ("| a | b |\n|---|---|", "<p><bdi>| a | b |<br>|---|---|</bdi></p>"),
    ("> not a quote", "<p><bdi>&gt; not a quote</bdi></p>"),
    ("\\*literal\\*", "<p><bdi>*literal*</bdi></p>"),
    (
        "**bold *and italic***",
        "<p><bdi><strong>bold <em>and italic</em></strong></bdi></p>",
    ),
    ("a & b \"q\" 'r'", "<p><bdi>a &amp; b &quot;q&quot; &#39;r&#39;</bdi></p>"),
]

ATTACKS = [
    "[a](javascript:window.__pwned++)",
    '[a](https://x.example/"onmouseover="window.__pwned++)',
    "[a](https://x.example/'><img src=x onerror=window.__pwned++>)",
    "**<img src=x onerror=window.__pwned++>**",
    "[<img src=x onerror=window.__pwned++>](https://x.example/)",
    "- <script>window.__pwned++</script>\n- [x](javascript:1)",
    "![i](https://tracker.example/p.png)",
    "[a](https://x.example/)[b](https://y.example/)",
    "[a]( https://x.example/ )",
    "[a](https://x.example/a b)",
    "**[a](https://x.example/)**",
    "[**a**](https://x.example/)",
    "[a](https://x.example/a)b)",
    '<a href="javascript:1">x</a>',
    "\u2028# heading\u2029- item",
    "\\[a](javascript:1)",
]

ALPHABET = [
    *list("*_[]()\n -1.<>&\"'!#|\\:/https"),
    "](",
    "javascript:",
    "https://x.example/",
    "**",
    "- ",
    "1. ",
]

# Run in the page: the HTML for a text must hold only these tags and attributes.
STRUCTURE = """
(texts) => {
  const okTags = new Set(["P","UL","OL","LI","STRONG","EM","A","SPAN","BR","BDI"]);
  const bad = [];
  for (const text of texts) {
    const html = "<body>" + mdHTML(text) + "</body>";
    const doc = new DOMParser().parseFromString(html, "text/html");
    for (const el of doc.body.querySelectorAll("*")) {
      if (!okTags.has(el.tagName)) bad.push([text, "tag " + el.tagName]);
      const names = el.getAttributeNames();
      if (el.tagName === "A") {
        const href = el.getAttribute("href") || "";
        if (!/^https?:\\/\\//i.test(href)) bad.push([text, "href " + href]);
        if (names.sort().join() !== "href,rel,target")
          bad.push([text, "attrs " + names]);
      } else if (el.tagName === "SPAN") {
        if (names.join() !== "class" || el.className !== "md-url")
          bad.push([text, "span"]);
      } else if (names.length) bad.push([text, el.tagName + " attrs " + names]);
    }
    if (doc.body.querySelector("img, script, iframe, form, input, svg, style"))
      bad.push([text, "active element"]);
  }
  return bad.slice(0, 5);
}
"""

# The Markdown for a text, and the links in each output.
OUTPUTS = """
(texts) => texts.map(text => {
  const html = "<body>" + mdHTML(text) + "</body>";
  const doc = new DOMParser().parseFromString(html, "text/html");
  return {
    md: mdInlineMarkdown(text),
    hrefs: [...doc.querySelectorAll("a")].map(a => a.getAttribute("href")),
    strong: doc.querySelectorAll("strong").length,
    em: doc.querySelectorAll("em").length,
  };
})
"""


def md_links(md: str) -> list[str]:
    return [
        m.group(1).replace("%28", "(").replace("%29", ")")
        for m in re.finditer(r"(?<!\\)\]\((https?://[^()\s]*)\)", md)
    ]


def md_problems(md: str) -> list[str]:
    bad = []
    if "\n" in md or "\r" in md or "\u2028" in md or "\u2029" in md:
        bad.append("a line break")
    if re.search(r"(?<!\\)<[a-zA-Z/!?]", md):
        bad.append("raw HTML")
    if re.search(r"(?<!\\)!\[", md):
        bad.append("an image")
    if re.search(r"(?<!\\)\]\(\s*(?!https?://)", md, re.I):
        bad.append("a link that is not http(s)")
    if re.search(r"(?<!\\)\|", md):
        bad.append("an unescaped pipe")
    return bad


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(APP.as_uri())
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")

        print("what it reads as")
        for source, want in EXAMPLES:
            got = page.evaluate("s => mdHTML(s)", source)
            check(repr(source[:44]), got == want, got)

        print("any text: only the subset comes out")
        rng = random.Random(7)
        fuzz = [
            "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 40)))
            for _ in range(3000)
        ]
        texts = fuzz + ATTACKS
        bad = page.evaluate(STRUCTURE, texts)
        check(
            "HTML holds only the subset's tags, links and attributes", not bad, str(bad)
        )

        print("the Markdown says the same thing")
        outs = page.evaluate(OUTPUTS, texts)
        problems = [
            (t[:40], md_problems(o["md"]))
            for t, o in zip(texts, outs, strict=True)
            if md_problems(o["md"])
        ]
        check(
            "no raw HTML, image, line break or foreign link",
            not problems,
            str(problems[:3]),
        )
        drift = [
            (t[:40], o["hrefs"], md_links(o["md"]))
            for t, o in zip(texts, outs, strict=True)
            if sorted(o["hrefs"]) != sorted(md_links(o["md"]))
        ]
        check("its links are the HTML's links", not drift, str(drift[:3]))
        for source, want in MD_EXAMPLES:
            got = page.evaluate("s => mdInlineMarkdown(s)", source)
            check(f"Markdown for {source[:36]!r}", got == want, got)

        print("bounded")
        nasty = [
            "*a " * 20000,
            "[" * 30000,
            "[a](" * 10000,
            "**a" * 20000,
            "_a" * 30000,
            "- " * 30000,
            "(" * 100000,
            "*" * 100000,
        ]
        for text in nasty:
            t0 = time.time()
            html = page.evaluate("s => mdHTML(s) + mdInlineMarkdown(s)", text)
            took = time.time() - t0
            check(
                f"{text[:6]!r} x{len(text) // max(1, len(text[:6]))} in under 2 s",
                took < 2.0,
                f"{took:.1f}s",
            )
            check("  and it still escapes", "<script" not in html)
        long_text = "word " * 20000
        html = page.evaluate("s => mdHTML(s)", long_text)
        check("text past the limit is kept, as plain text", html.count("word") == 20000)

        # ---- in the product -------------------------------------------
        print("in the product")
        page.evaluate("loadSamples()")
        wait_until(page, "PROJECTS && PROJECTS.size > 0")
        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        page.evaluate(f"openProject({pid!r}, 's1')")
        page.wait_for_timeout(300)
        item = page.evaluate("allItems()[0].id")
        page.evaluate(f"openItems.add({item!r}); renderMain(false)")
        ta = f"#ev_{item}"
        preview = f"{ta} ~ .md-help [data-mdpreview]"
        check(
            "a note with no formatting shows no preview",
            page.query_selector(preview).is_hidden(),
        )
        page.fill(ta, "plain note")
        check(
            "still none as plain text is typed",
            page.query_selector(preview).is_hidden(),
        )
        page.fill(ta, "**ok** see [report](https://example.org/r)\n- one\n- two")
        page.dispatch_event(ta, "input")
        check("formatting shows a preview", page.query_selector(preview).is_visible())
        check(
            "the preview has the bold, the list and the link",
            page.query_selector(f"{preview} strong") is not None
            and len(page.query_selector_all(f"{preview} li")) == 2
            and page.query_selector(f'{preview} a[href="https://example.org/r"]')
            is not None,
        )
        check(
            "what is stored is the text typed, not markup",
            page.evaluate(f"S.items['{item}'].evidence")
            == "**ok** see [report](https://example.org/r)\n- one\n- two",
        )
        page.evaluate("flushAllChanges && flushAllChanges()")
        page.evaluate(f"S.items['{item}'].status = 'notmet'; go('report')")
        page.wait_for_timeout(200)
        shown = page.evaluate("document.querySelector('#main').innerHTML")
        check(
            "the report shows the bold and the link",
            "<strong>ok</strong>" in shown and 'href="https://example.org/r"' in shown,
        )
        html = page.evaluate("exportHTML()")
        check(
            "the HTML export does too, closed against the opener",
            "<strong>ok</strong>" in html
            and 'rel="noopener noreferrer nofollow"' in html,
        )
        md = page.evaluate("exportMD()")
        check(
            "the Markdown export writes the subset back",
            "**ok**" in md and "[report](https://example.org/r)" in md,
        )
        data = page.evaluate("projectJSON(S)")
        row = next(c for c in data["checklist"] if c["id"] == item)
        check(
            "the JSON keeps the text as typed",
            row["evidence"].startswith("**ok** see [report]"),
        )

        # A checkpoint's rationale is a notes field too.
        page.evaluate(
            "S.gates.A = {decision: 'Proceed', rationale: '*why* [r](https://example.org/g)'}"
        )
        page.evaluate("go('report')")
        page.wait_for_timeout(150)
        check(
            "a checkpoint rationale is formatted in the report",
            "<em>why</em>"
            in page.evaluate("document.querySelector('#main').innerHTML"),
        )
        md = page.evaluate("exportMD()")
        check(
            "and in the Markdown table, on one line",
            "*why* [r](https://example.org/g)" in md,
        )

        # ---- mutations ---------------------------------------------------
        print("mutations")
        page.evaluate("() => { window.safeUrl = s => String(s); }")
        weak = page.evaluate("() => mdHTML('[x](javascript:alert1)')")
        check(
            "with safeUrl weakened the structure check would catch the hole",
            'href="javascript:' in weak
            and bool(page.evaluate(STRUCTURE, ["[x](javascript:alert1)"])),
            weak,
        )
        page2 = browser.new_page()
        with tempfile.TemporaryDirectory() as tmp:
            src = APP.read_text(encoding="utf-8")
            marker = "const esc = s =>"
            assert marker in src
            copy = Path(tmp) / "weak.html"
            copy.write_text(
                src.replace(
                    marker, 'const esc = s => String(s ?? ""); const _e = s =>', 1
                ),
                encoding="utf-8",
            )
            # The page's own policy names the script's hash, so the edited copy
            # would not run; this mutation tests escaping alone.
            copy.write_text(
                re.sub(
                    r'<meta http-equiv="Content-Security-Policy"[^>]*>',
                    "",
                    copy.read_text(encoding="utf-8"),
                    count=1,
                ),
                encoding="utf-8",
            )
            page2.goto(copy.as_uri())
            wait_until(page2, "typeof LOADED !== 'undefined' && LOADED")
            raw = page2.evaluate("() => mdHTML('<img src=x onerror=1>')")
            check(
                "with esc weakened the structure check would catch the tag",
                "<img" in raw
                and bool(page2.evaluate(STRUCTURE, ["<img src=x onerror=1>"])),
                raw,
            )
        check("no page errors", not errors, "; ".join(errors))
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
