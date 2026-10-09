#!/usr/bin/env python3
"""Evidence references: links and file fingerprints, never the file (R-61, D-70).

A reference is a title, a link and, optionally, a file that is fingerprinted in
the browser. Three things have to stay true, and this is where each is shown:

  * a link a person types becomes a link only if it is http or https, with no
    credentials, so a reference cannot carry script into a reviewer's session;
  * the file is read here and its bytes go nowhere: the record keeps a name, a
    size and a SHA-256 that matches what Python's hashlib says, whichever way the
    page computed it;
  * the references appear in every export, and in Markdown a hostile title or
    address cannot break out of the link.

    pixi run test-refs
"""

from __future__ import annotations

import hashlib
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


def wait_until(page, expr: str, timeout: float = 10.0) -> None:
    import time

    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(f"() => !!({expr})"):
            return
        page.wait_for_timeout(100)
    raise TimeoutError(expr)


ACCEPTED = [
    ("https://example.org/a?b=1#c", "https://example.org/a?b=1#c"),
    ("http://example.org", "http://example.org/"),
    ("  https://example.org/x  ", "https://example.org/x"),
    ("HTTPS://EXAMPLE.ORG/Path", "https://example.org/Path"),
]
REFUSED = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "java\nscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://example.org/x",
    "//evil.example/x",
    "/relative/path",
    "https://user:pw@example.org/",
    "https://user@example.org/",
    "https://exa mple.org/",
    "https://example.org/\u0000",
    "https://",
    "",
    "https://example.org/" + "a" * 2100,
]
SIZES = [0, 1, 55, 56, 63, 64, 65, 119, 120, 1000, 100_000]


def way_out(source: str) -> list[str]:
    """Anything in the code (comments aside) that could carry data off the page."""
    code = "\n".join(
        ln for ln in source.splitlines() if not ln.strip().startswith(("*", "/*", "//"))
    )
    return re.findall(
        r"\b(fetch|XMLHttpRequest|sendBeacon|FormData|WebSocket|EventSource|STORE)\b",
        code,
    )


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        requests: list[str] = []
        page.on("request", lambda r: requests.append(r.url))
        page.goto(APP.as_uri())
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")

        # ---- the address rule ------------------------------------------
        print("the address rule")
        for raw, want in ACCEPTED:
            got = page.evaluate("v => safeUrl(v)", raw)
            check(f"accepts {raw[:40]!r}", got == want, repr(got))
        for raw in REFUSED:
            got = page.evaluate("v => safeUrl(v)", raw)
            check(f"refuses {raw[:40]!r}", got == "", repr(got))

        # ---- the fingerprint -------------------------------------------
        print("the fingerprint")
        for how in ("Web Crypto", "the page's own SHA-256"):
            if how != "Web Crypto":
                page.evaluate(
                    "() => Object.defineProperty(crypto, 'subtle',"
                    " {value: undefined, configurable: true})"
                )
            bad = []
            for n in SIZES:
                data = bytes((i * 7 + 3) % 256 for i in range(n))
                got = page.evaluate(
                    "async (a) => hashFile(new File([new Uint8Array(a)], 'x.bin'))",
                    list(data),
                )
                if got != hashlib.sha256(data).hexdigest():
                    bad.append(n)
            check(f"{how} matches hashlib at every size", not bad, str(bad))
        page.evaluate("() => { delete crypto.subtle; }")

        # ---- the page, as a person uses it -----------------------------
        page.evaluate("loadSamples()")
        wait_until(page, "PROJECTS && PROJECTS.size > 0")
        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        item = None
        page.evaluate(f"openProject({pid!r}, 's1')")
        page.wait_for_timeout(300)
        item = page.evaluate("allItems()[0].id")
        page.evaluate(f"openItems.add({item!r}); renderMain(false)")
        box = f'[data-refs="items.{item}"]'
        before = len(requests)
        check("the block is on the item", page.query_selector(box) is not None)

        page.fill(f"{box} [data-refin=title]", "Validation report v2")
        page.fill(f"{box} [data-refin=url]", "https://example.org/report?id=7")
        page.fill(f"{box} [data-refin=date]", "2026-03-04")
        page.click(f"{box} [data-addref]")
        wait_until(page, f"refList(S.items['{item}']).length === 1")
        link = page.query_selector(f"{box} .refs-list a")
        check("a link was made", link is not None)
        if link:
            check(
                "it opens in a new tab without the opener or a referrer",
                link.get_attribute("target") == "_blank"
                and set((link.get_attribute("rel") or "").split())
                >= {"noopener", "noreferrer", "nofollow"},
                link.get_attribute("rel") or "",
            )
            check(
                "its address is printed beside it",
                "https://example.org/report?id=7" in page.inner_text(f"{box} .ref-url"),
            )

        # A file: the digest is the one hashlib gives, and the bytes stay here.
        payload = b"%PDF-1.7 synthetic evidence \x00\xff" * 50
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "validation.pdf"
            f.write_bytes(payload)
            page.set_input_files(f"{box} [data-refin=file]", str(f))
            page.click(f"{box} [data-addref]")
            wait_until(page, f"refList(S.items['{item}']).length === 2")
            refs = page.evaluate(f"refList(S.items['{item}'])")
            filed = next(r for r in refs if r["file"])
            check(
                "the stored SHA-256 is hashlib's",
                filed["file"]["sha256"] == hashlib.sha256(payload).hexdigest(),
                str(filed["file"]),
            )
            check(
                "the stored file is a name, a size and a digest, nothing else",
                set(filed["file"]) == {"name", "size", "sha256"}
                and filed["file"]["size"] == len(payload)
                and filed["file"]["name"] == "validation.pdf",
            )
            blob = page.evaluate("() => JSON.stringify(S)")
            check("no bytes of the file are in the record", "synthetic" not in blob)
            check(
                "adding a file made no network request",
                requests[before:] == [],
                str(requests[before:]),
            )

            # Verify: the same file matches, a different one does not.
            def verify(path: Path) -> str:
                with page.expect_file_chooser() as fc:
                    page.click(
                        f"{box} [data-verifyref={filed['id']!r}]".replace("'", '"')
                    )
                fc.value.set_files(str(path))
                page.wait_for_timeout(400)
                return page.inner_text("#toast")

            check("the same file matches", "matches" in verify(f), "")
            g = Path(tmp) / "other.pdf"
            g.write_bytes(payload + b"!")
            check("a changed file does not", "differs" in verify(g), "")

        # The block is read-only text everywhere a reader sees it.
        check(
            "references are not form fields in the log",
            page.evaluate(
                f"describeValue('items.{item}.refs.rabcdef12', "
                "{title:'T', url:'https://e.org/'})"
            ).startswith("“T”"),
        )

        # ---- exports ---------------------------------------------------
        print("the exports")
        md = page.evaluate("exportMD()")
        check(
            "Markdown carries the link and the digest",
            "[Validation report v2](https://example.org/report?id=7)" in md
            and hashlib.sha256(payload).hexdigest() in md,
        )
        data = page.evaluate("projectJSON(S)")
        row = next(c for c in data["checklist"] if c["id"] == item)
        check(
            "JSON lists them under the criterion",
            len(row["references"]) == 2
            and any(
                r["url"] == "https://example.org/report?id=7" for r in row["references"]
            ),
            str(row["references"]),
        )
        html = page.evaluate("exportHTML()")
        check(
            "the HTML report shows them, links closed against the opener",
            'href="https://example.org/report?id=7"' in html
            and 'rel="noopener noreferrer nofollow"' in html,
        )

        # ---- hostile values --------------------------------------------
        print("hostile values")
        hostile = {
            "rbad000001": {
                "title": "]( javascript:alert(1) ) [x",
                "url": "https://a.example/x)(<b>",
                "at": "1",
            },
            "rbad000002": {
                "title": "<img src=x onerror=window.__pwned=1>",
                "url": "javascript:alert(1)",
                "at": "2",
            },
            "rbad000003": {
                "title": "x",
                "url": "https://ok.example/",
                "file": {"name": "<b>", "size": "NaN", "sha256": "zz"},
                "at": "3",
            },
            "__proto__": {"title": "p", "url": "https://p.example/"},
            "notanid": {"title": "n", "url": "https://n.example/"},
        }
        page.evaluate(
            "([id, refs]) => { S.items[id].refs = JSON.parse(refs); }",
            [item, json.dumps(hostile)],
        )
        md = page.evaluate("exportMD()")
        mine = [
            x for x in md.splitlines() if "Reference" in x or "javascript" in x.lower()
        ]
        check(
            "a stored javascript: address is never made a link",
            "](javascript" not in md.lower()
            and 'href="javascript' not in page.evaluate("exportHTML()").lower(),
            str(mine[:3]),
        )
        link_lines = [x for x in md.splitlines() if "](https://a.example/x" in x]
        check(
            "parentheses and brackets in an address cannot end the link early",
            bool(link_lines)
            and "x)(" not in link_lines[0].split(") ")[0]
            and "x%29%28%3Cb%3E)" in link_lines[0],
            link_lines[0] if link_lines else md[-300:],
        )
        listed = page.evaluate(f"refList(S.items['{item}']).map(r => r.id)")
        check(
            "entries that are not references are dropped",
            listed == ["rbad000001", "rbad000002", "rbad000003"],
            str(listed),
        )
        bad3 = page.evaluate(f"refList(S.items['{item}'])[2].file")
        check("a malformed file fingerprint is dropped", bad3 is None, str(bad3))
        page.evaluate("renderMain(false)")
        page.wait_for_timeout(200)
        check(
            "no script ran and no element was injected from a title",
            page.evaluate("() => (window.__pwned || 0)") == 0
            and page.query_selector(f"{box} img") is None,
        )

        # ---- remove, and the history -----------------------------------
        print("remove")
        page.evaluate(f"S.items['{item}'].refs = {{}}")
        page.evaluate(
            f"edit('items.{item}.refs.rgood00001', "
            "{title: 'Keep', url: 'https://keep.example/', at: '9', file: null})"
        )
        page.evaluate("renderMain(false)")
        page.wait_for_timeout(200)
        page.click(f'{box} [data-delref="rgood00001"]')
        page.wait_for_timeout(200)
        check(
            "removing writes a null at that key",
            page.evaluate(f"S.items['{item}'].refs.rgood00001") is None
            and page.evaluate(f"refList(S.items['{item}']).length") == 0,
        )
        page.evaluate(f"flushChanges(CUR, 'items.{item}.refs.rgood00001')")
        wait_until(page, "LOG.some(e => /evidence reference/.test(e.text))")
        check("the history says an evidence reference changed", True)

        check("no page errors", not errors, "; ".join(errors))
        browser.close()

    # ---- the file never leaves: the code that reads it has no way out -----
    src = (ROOT / "app/js/00-core/55-refs.js").read_text()
    check(
        "the reference code has no way to send anything",
        not way_out(src),
        str(way_out(src)),
    )

    # ---- mutations: each guard must notice when it is broken -----------
    print("mutations")
    check(
        "a fetch in the reference code is noticed",
        bool(way_out("await fetch(u, {body: bytes})")),
        "",
    )
    check(
        "a beacon in the reference code is noticed",
        bool(way_out("navigator.sendBeacon(u, f)")),
        "",
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(APP.as_uri())
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        probe = (
            "() => refList({refs: {rabcdef123: {title: 't',"
            " url: 'javascript:alert(1)'}}})[0].url"
        )
        check("safeUrl turns javascript: into no link", page.evaluate(probe) == "", "")
        page.evaluate("() => { window.safeUrl = s => String(s); }")
        check(
            "with safeUrl weakened, the same probe shows the hole",
            page.evaluate(probe) == "javascript:alert(1)",
            page.evaluate(probe),
        )
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
