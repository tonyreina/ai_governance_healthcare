#!/usr/bin/env python3
"""The page policy refuses script that the page did not ship (#154).

Escaping is the first barrier against text a person typed becoming code, and
tests/test_injection.py shows it holds. This is the second, independent one. The proxy
serves `script-src 'sha256-…'`, the hash of the dashboard's one inline script, with no
`'unsafe-inline'`, so a script, an event handler or a `javascript:` URL that reaches the
page by any other route is refused by the browser, whatever the page failed to escape.

The hash changes with every build, so scripts/build_app.py generates proxy/csp.caddy
from the built page, the Caddyfile imports it, compose mounts it and the cloud image
copies it.

What is asserted:

* the generated policy names the hash of the page's actual script, and is not stale;
* the Caddyfile, compose and the proxy image all use that file, and none still says
  `'unsafe-inline'` for script;
* in a real browser, given that policy as the response header, the dashboard boots with
  no violation, and an injected inline script, an inline event handler and a
  `javascript:` link are each refused (and reported as violations);
* given a policy with the wrong hash, the dashboard does not boot (the check can fail);
* the exported report carries a policy of its own, so a saved report opened from disk
  cannot run script either;
* the page carries the same policy itself, as a meta tag first in its <head>, so it also
  holds on the static example page and in a copy opened from disk, which cannot set
  headers: served with no header at all it boots and refuses the same three injections,
  and a meta policy naming a different script stops it from booting.

    pixi run test-csp
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from browser_engine import engine_name, launch
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
CSP_FILE = ROOT / "proxy" / "csp.caddy"
URL = "https://dashboard.test/app/index.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def policy() -> str:
    return re.search(
        r'Content-Security-Policy "([^"]+)"', CSP_FILE.read_text(encoding="utf-8")
    ).group(1)


def script_hash(html: str) -> str:
    """The hash of the page's script, worked out here and not by the build, so the
    build's own parser is checked against a second way of reading the page."""
    start = html.index("<script>") + len("<script>")
    text = html[start : html.index("</script>", start)]
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def wait_until(page, expression: str, timeout: float = 15.0) -> None:
    """Poll with page.evaluate. page.wait_for_function evaluates its argument with
    the page's own `eval`, which this policy forbids (see tests/test_stack.py)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(150)
    raise TimeoutError(f"still false after {timeout}s: {expression}")


def open_under(browser, csp: str | None, html: str | None = None):
    """The dashboard, served with `csp` as its header (none, as on a static host)."""
    ctx = browser.new_context()
    page = ctx.new_page()
    violations: list[str] = []
    page.expose_function("reportViolation", lambda text: violations.append(text))
    page.add_init_script(
        """document.addEventListener('securitypolicyviolation', e =>
             window.reportViolation(e.violatedDirective + ' ' + e.blockedURI));
           window.__pwned = 0;"""
    )
    html = html if html is not None else APP.read_text(encoding="utf-8")
    headers = {"content-type": "text/html; charset=utf-8"}
    if csp:
        headers["content-security-policy"] = csp
    page.route(URL, lambda route: route.fulfill(status=200, body=html, headers=headers))
    # A static host: there is no API here, which the app takes as browser-only mode.
    page.route("**/api/**", lambda route: route.fulfill(status=404, body=""))
    page.goto(URL)
    return ctx, page, violations


def main() -> int:
    html = APP.read_text(encoding="utf-8")
    csp = policy()

    print("The generated policy")
    check(
        "names the hash of the page's one script",
        script_hash(html) in csp,
        f"{script_hash(html)} not in {csp}",
    )
    check(
        "and gives script no 'unsafe-inline'",
        "unsafe-inline" not in csp.split("script-src")[1].split(";")[0],
    )
    check("or 'unsafe-eval'", "unsafe-eval" not in csp)
    check(
        "and still cannot reach another origin",
        all(
            x in csp
            for x in ("default-src 'none'", "connect-src 'self'", "form-action 'none'")
        ),
    )
    caddyfile = (ROOT / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    check(
        "the Caddyfile imports it, and no longer carries its own script policy",
        "import /etc/caddy/csp.caddy" in caddyfile
        and "script-src 'unsafe-inline'" not in caddyfile,
    )
    check(
        "compose mounts it (by default; CSP_FILE names another build's, #168)",
        "${CSP_FILE:-./proxy/csp.caddy}:/etc/caddy/csp.caddy:ro"
        in (ROOT / "compose.yaml").read_text(),
    )
    check(
        "and the cloud image copies it",
        "COPY proxy/csp.caddy /etc/caddy/csp.caddy"
        in (ROOT / "proxy" / "Dockerfile").read_text(),
    )

    # A typo in a CI matrix must not run Chromium twice and call it cross-browser.
    kept = os.environ.get("TEST_BROWSER")
    try:
        os.environ["TEST_BROWSER"] = "firefx"
        try:
            engine_name()
            refused = False
        except SystemExit:
            refused = True
    finally:
        if kept is None:
            os.environ.pop("TEST_BROWSER", None)
        else:
            os.environ["TEST_BROWSER"] = kept
    check("an unknown TEST_BROWSER is an error, not Chromium", refused)

    with sync_playwright() as pw:
        browser = launch(pw)

        print("The dashboard under that policy")
        ctx, page, violations = open_under(browser, csp)
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        page.evaluate("loadSamples()")
        wait_until(page, "PROJECTS && PROJECTS.size >= 10")
        page.evaluate("openProject([...PROJECTS.keys()][0], 'report')")
        page.wait_for_timeout(200)
        check("boots and works with no violation", not violations, str(violations[:3]))

        print("What the policy refuses")
        page.evaluate(
            """() => {
                const s = document.createElement('script');
                s.textContent = 'window.__pwned++';
                document.body.appendChild(s);
            }"""
        )
        page.evaluate(
            """() => {
                const d = document.createElement('div');
                d.innerHTML = '<img src=x onerror="window.__pwned++">';
                document.body.appendChild(d);
            }"""
        )
        page.evaluate(
            """() => {
                const a = document.createElement('a');
                a.href = 'javascript:window.__pwned++';
                document.body.appendChild(a);
                a.click();
            }"""
        )
        page.wait_for_timeout(300)
        check(
            "an injected inline script, handler and javascript: link did not run",
            page.evaluate("window.__pwned") == 0,
            str(page.evaluate("window.__pwned")),
        )
        kinds = " ".join(violations)
        check("each was reported as a violation", "script-src" in kinds, kinds[:120])
        ctx.close()

        print("A wrong hash stops the dashboard (mutation)")
        wrong = csp.replace(
            script_hash(html), "'sha256-" + base64.b64encode(b"x" * 32).decode() + "'"
        )
        check("the mutation changed the policy", wrong != csp)
        ctx, page, _ = open_under(browser, wrong)
        page.wait_for_timeout(1500)
        booted = page.evaluate("typeof LOADED !== 'undefined' && LOADED")
        check(
            "a policy that names a different script does not boot the app", not booted
        )
        ctx.close()

        print("The exported report carries a policy of its own")
        ctx, page, _ = open_under(browser, csp)
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        page.evaluate("loadSamples()")
        wait_until(page, "PROJECTS && PROJECTS.size >= 10")
        page.evaluate("openProject([...PROJECTS.keys()][0], 'report')")
        report = page.evaluate("exportHTML()")
        ctx.close()
        check(
            "it is in the report",
            'http-equiv="Content-Security-Policy"' in report
            and "default-src 'none'" in report,
        )
        ctx = browser.new_context()
        shot = ctx.new_page()
        shot.add_init_script("window.__pwned = 0")
        # Opened from disk, as a recipient would, not written into a blank page.
        saved = Path(tempfile.mkdtemp(prefix="chai-csp-")) / "report.html"
        saved.write_text(report, encoding="utf-8")
        shot.goto(saved.as_uri())
        shot.evaluate(
            """() => {
                const s = document.createElement('script');
                s.textContent = 'window.__pwned++';
                document.body.appendChild(s);
                const d = document.createElement('div');
                d.innerHTML = '<img src=x onerror="window.__pwned++">';
                document.body.appendChild(d);
            }"""
        )
        shot.wait_for_timeout(300)
        check(
            "so a script put into a saved report does not run",
            shot.evaluate("window.__pwned") == 0,
        )
        ctx.close()
        browser.close()

    print(
        "The page's own policy (no header: the static example page, or a file on disk)"
    )
    source = APP.read_text(encoding="utf-8")
    head = source.split("<head>", 1)[1].split("<script", 1)[0]
    tag = re.search(
        r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', head
    )
    check("the page carries a policy tag", tag is not None)
    check(
        "as the first child of <head>, ahead of anything that could load",
        re.match(r"\s*<meta http-equiv=\"Content-Security-Policy\"", head) is not None,
        head[:80],
    )
    meta = tag.group(1) if tag else ""
    check(
        "naming the hash of the page's one script, with no 'unsafe-inline' for script",
        script_hash(source) in meta
        and "unsafe-inline" not in meta.split("script-src")[1].split(";")[0],
    )
    header_only = ("frame-ancestors",)
    check(
        "and the same directives as the proxy's header, but frame-ancestors",
        sorted(meta.split("; "))
        == sorted(d for d in csp.split("; ") if not d.startswith(header_only)),
        f"{meta} | {csp}",
    )
    inject = (
        "() => { const s = document.createElement('script');"
        " s.textContent = 'window.__pwned++'; document.body.appendChild(s);"
        " const d = document.createElement('div');"
        " d.innerHTML = '<img src=x onerror=\"window.__pwned++\">';"
        " document.body.appendChild(d);"
        " const a = document.createElement('a');"
        " a.href = 'javascript:window.__pwned++'; document.body.appendChild(a);"
        " a.click(); }"
    )
    with sync_playwright() as pw:
        browser = launch(pw)
        ctx, page, violations = open_under(browser, None)  # no header at all
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        check(
            "served with no header it boots, with no violation",
            not violations,
            str(violations[:2]),
        )
        page.evaluate(inject)
        page.wait_for_timeout(300)
        check(
            "and refuses an injected script, handler and javascript: link",
            page.evaluate("window.__pwned") == 0,
        )
        ctx.close()
        # The same file opened from disk, as a copy someone saved would be.
        ctx = browser.new_context()
        disk = ctx.new_page()
        disk.add_init_script("window.__pwned = 0")
        disk.goto(APP.as_uri())
        wait_until(disk, "typeof LOADED !== 'undefined' && LOADED")
        disk.evaluate(inject)
        disk.wait_for_timeout(300)
        check(
            "opened from disk it refuses the same injection too",
            disk.evaluate("window.__pwned") == 0,
        )
        ctx.close()
        # Without the tag the same injection runs, so the checks above can fail.
        bare = re.sub(
            r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", source, count=1
        )
        check("the mutation removed the tag", bare != source)
        ctx, page, _ = open_under(browser, None, bare)
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        page.evaluate(inject)
        page.wait_for_timeout(300)
        check(
            "without the tag, the same injection DOES run (the test can fail)",
            page.evaluate("window.__pwned") > 0,
        )
        ctx.close()
        # A tag that names a different script stops the dashboard, as a header does.
        other = "'sha256-" + base64.b64encode(b"y" * 32).decode() + "'"
        ctx, page, _ = open_under(
            browser, None, source.replace(script_hash(source), other, 1)
        )
        page.wait_for_timeout(1200)
        check(
            "a tag naming a different script does not boot the app",
            not page.evaluate("typeof LOADED !== 'undefined' && LOADED"),
        )
        ctx.close()
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("csp checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
