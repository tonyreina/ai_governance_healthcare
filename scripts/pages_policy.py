#!/usr/bin/env python3
"""Give the published GitHub Pages copy of the dashboard a page policy (#157).

The proxy sends a Content-Security-Policy header that allows the dashboard's one
inline script by hash (proxy/csp.caddy, D-68). GitHub Pages cannot set response
headers, so the demonstration copy would run with no policy at all. A
`<meta http-equiv>` tag carries the same policy, and it is added here, to the built
site, at publish time:

    python scripts/pages_policy.py site/app/index.html

Why not in the page itself: docs/app/index.html is also the file a Claude artifact runs,
and that host injects script of its own, which a policy tag in the page would block. The
tag is added only to the copy the Pages workflow publishes.

The policy is the proxy's, taken from the generated file, minus `frame-ancestors`,
which browsers ignore in a meta tag. The tag goes first in <head>, so it applies to
everything after it, and the script's hash is checked against the page before anything
is written.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_app import CSP_OUT, script_hash

# Names defined by HTML and CSP, not by this repository.
NOT_IN_META = "frame-ancestors"  # a CSP directive browsers ignore in a meta tag
META = "meta"  # an HTML tag name, as html.parser reports it
CSP_HTTP_EQUIV = "content-security-policy"  # the http-equiv value, lower case
POLICY = re.compile(r'Content-Security-Policy "([^"]+)"')


def meta_policy(csp_file: Path) -> str:
    """The proxy's policy, as a meta tag can carry it."""
    found = POLICY.search(csp_file.read_text(encoding="utf-8"))
    if not found:
        raise SystemExit(f"error: no Content-Security-Policy in {csp_file}")
    directives = [
        d.strip()
        for d in found.group(1).split(";")
        if not d.strip().startswith(NOT_IN_META)
    ]
    return "; ".join(d for d in directives if d)


HEAD = "head"  # an HTML tag name, as html.parser reports it


class _Metas(HTMLParser):
    """The page's own <meta> tags, and where its <head> opens. Script text is not parsed
    as markup, so the `<head>` and the policy text that the dashboard writes into the
    reports it exports do not count."""

    def __init__(self) -> None:
        super().__init__()
        self.policies = 0
        self.head_end: tuple[int, int] | None = None  # (line, column) after <head>

    def handle_starttag(self, tag, attrs):
        if tag == HEAD and self.head_end is None:
            line, col = self.getpos()
            self.head_end = (line, col + len(self.get_starttag_text() or ""))
        if (
            tag == META
            and (dict(attrs).get("http-equiv") or "").lower() == CSP_HTTP_EQUIV
        ):
            self.policies += 1


def apply(html: str, policy: str) -> str:
    """The page with the policy as its first <head> child."""
    if script_hash(html) not in policy:
        raise SystemExit(
            "error: the policy does not name this page's script; rebuild with "
            "`pixi run build-app` so proxy/csp.caddy matches"
        )
    metas = _Metas()
    metas.feed(html)
    if metas.policies:
        raise SystemExit("error: the page already carries a Content-Security-Policy")
    if metas.head_end is None:
        raise SystemExit("error: the page has no <head>")
    line, col = metas.head_end
    at = sum(len(x) + 1 for x in html.split("\n")[: line - 1]) + col
    tag = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
    return html[:at] + tag + html[at:]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    page = Path(argv[1])
    page.write_text(
        apply(page.read_text(encoding="utf-8"), meta_policy(CSP_OUT)), encoding="utf-8"
    )
    print(f"{page}: page policy added")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
