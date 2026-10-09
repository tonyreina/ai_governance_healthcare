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
* the published GitHub Pages copy, which cannot set headers, gets the same policy as a
  meta tag from scripts/pages_policy.py at publish time (#157): served with no header
  at all it boots and refuses the same three injections, and the file in the
  repository, which a Claude artifact also runs, is left without one.

    pixi run test-csp
"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
import tempfile
import time
from pathlib import Path

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
    """The dashboard, served with `csp` as its response header."""
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
    if csp:  # the proxy's header; Pages sends none
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
        "compose mounts it",
        "./proxy/csp.caddy:/etc/caddy/csp.caddy" in (ROOT / "compose.yaml").read_text(),
    )
    check(
        "and the cloud image copies it",
        "COPY proxy/csp.caddy /etc/caddy/csp.caddy"
        in (ROOT / "proxy" / "Dockerfile").read_text(),
    )

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

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

    print("The published GitHub Pages copy")
    sys.path.insert(0, str(ROOT / "scripts"))
    import pages_policy

    source = APP.read_text(encoding="utf-8")
    published = pages_policy.apply(source, pages_policy.meta_policy(CSP_FILE))
    check(
        "the repository's file has no policy tag, so a Claude artifact is unaffected",
        'http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src'
        not in source,
    )
    check(
        "the published copy carries the policy as its first <head> child",
        re.search(
            r"<head[^>]*>\s*<meta http-equiv=\"Content-Security-Policy\"", published
        )
        is not None,
    )
    check(
        "and the tag drops the one directive a meta tag cannot carry",
        "frame-ancestors" not in published.split("</head>")[0],
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page, violations = open_under(browser, None, published)  # no header
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        check(
            "served with no header it still boots, with no violation",
            not violations,
            str(violations[:2]),
        )
        page.evaluate(
            """() => {
                const s = document.createElement('script');
                s.textContent = 'window.__pwned++';
                document.body.appendChild(s);
                const d = document.createElement('div');
                d.innerHTML = '<img src=x onerror="window.__pwned++">';
                document.body.appendChild(d);
                const a = document.createElement('a');
                a.href = 'javascript:window.__pwned++';
                document.body.appendChild(a);
                a.click();
            }"""
        )
        page.wait_for_timeout(300)
        check(
            "and refuses an injected script, handler and javascript: link",
            page.evaluate("window.__pwned") == 0,
        )
        ctx.close()
        ctx, page, _ = open_under(browser, None, source)
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        page.evaluate(
            """() => {
                const s = document.createElement('script');
                s.textContent = 'window.__pwned++';
                document.body.appendChild(s);
            }"""
        )
        page.wait_for_timeout(200)
        check(
            "without the tag, the same injection DOES run (the test can fail)",
            page.evaluate("window.__pwned") == 1,
        )
        ctx.close()
        browser.close()
    for label, mutate in [
        (
            "a page whose script the policy does not name",
            lambda h: h.replace("const esc =", "const esc2 =", 1),
        ),
        (
            "a page that already carries a policy tag",
            lambda h: h.replace(
                "<head>",
                '<head><meta http-equiv="Content-Security-Policy" content="x">',
                1,
            ),
        ),
        (
            "a page with no <head>",
            lambda h: re.sub(r"<head(?:\s[^>]*)?>", "", h, count=1, flags=re.I),
        ),
    ]:
        try:
            pages_policy.apply(mutate(source), pages_policy.meta_policy(CSP_FILE))
            check(f"the step refuses {label}", False, "it did not")
        except SystemExit:
            check(f"the step refuses {label}", True)
    check(
        "the Pages workflow runs the step after the build",
        "scripts/pages_policy.py site/app/index.html"
        in (ROOT / ".github" / "workflows" / "pages.yml").read_text(),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("csp checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
