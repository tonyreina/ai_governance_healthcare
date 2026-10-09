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
  cannot run script either.

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
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    digest = hashlib.sha256(scripts[0].encode("utf-8")).digest()
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


def open_under(browser, csp: str):
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
    html = APP.read_text(encoding="utf-8")
    page.route(
        URL,
        lambda route: route.fulfill(
            status=200,
            body=html,
            headers={
                "content-type": "text/html; charset=utf-8",
                "content-security-policy": csp,
            },
        ),
    )
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

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("csp checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
