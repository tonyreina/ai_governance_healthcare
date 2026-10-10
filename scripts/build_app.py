#!/usr/bin/env python3
"""Assemble app/ into the single self-contained docs/app/index.html.

Why a build step, and why a single file out:

* The dashboard must stay ONE self-contained file. It runs as a Claude artifact
  (which is a single document), it is opened straight off disk with no server,
  and it is published to GitHub Pages. Native ES modules would break the first
  two, because `file://` blocks module loading.
* But a 1400-line HTML file with CSS, two governance frameworks and all the
  rendering in one <script> is not maintainable, and the frameworks cannot be
  worked on separately.

So the source is split under app/ and concatenated here. The output is
generated: never edit docs/app/index.html by hand.

Run via: pixi run build-app
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_manifest import manifest_json
from check_i18n import Locale

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app"
OUT = ROOT / "docs" / "app" / "index.html"
# The proxy's Content-Security-Policy header, generated from the built page (#154).
CSP_OUT = ROOT / "proxy" / "csp.caddy"
# What the server needs from this build, beside the page (#168 PR C, D-76): each
# framework's definition hash and the decisions that end a project, which the migrate
# job loads into retirement_rule so disposal follows the same definition.
MANIFEST_OUT = OUT.parent / "manifest.json"

CSS_MARK = "/*@CSS@*/"
JS_MARK = "/*@JS@*/"
CSP_MARK = "<!--@CSP@-->"

BANNER = (
    "<!-- GENERATED FILE - do not edit.\n"
    "     Built from app/ by scripts/build_app.py (pixi run build-app).\n"
    "     Edit the sources under app/, then rebuild. -->\n"
)


def ordered(directory: Path, suffix: str) -> list[Path]:
    """Concatenation order, by numeric prefix at EVERY path segment.

    Sorting on the leaf name alone is wrong once sources are nested: both
    `00-core/00-util.js` and `10-frameworks/00-registry.js` start with `00`, and
    a leaf-only sort would interleave them by filename. The key below walks the
    whole relative path so directory order dominates, which is what decides the
    order declarations appear in the bundle.
    """

    def key(path: Path) -> tuple:
        parts = []
        for segment in path.relative_to(directory).parts:
            m = re.match(r"(\d+)", segment)
            parts.append((int(m.group(1)) if m else 9999, segment))
        return tuple(parts)

    return sorted((p for p in directory.rglob(f"*{suffix}")), key=key)


# The default build: what docs/app/index.html and proxy/csp.caddy are (#168). The
# committed app/frameworks.json must say exactly this; a build of other frameworks
# writes elsewhere (step 3), never over the published page.
class Role(StrEnum):
    """A framework definition's role (schema/framework.schema.json)."""

    PRIMARY = "primary"
    SUPPLEMENT = "supplement"


DEFAULT_FRAMEWORKS = {"primary": "chai", "frameworks": ["chai", "optica"]}
FRAMEWORKS_CONFIG = SRC / "frameworks.json"


def framework_defs(config: Path = FRAMEWORKS_CONFIG) -> dict:
    """The selected framework definitions, in the config's order, checked against
    the config: the primary is listed, and its definition says it is the primary."""
    cfg = json.loads(config.read_text(encoding="utf-8"))
    if cfg != DEFAULT_FRAMEWORKS:
        raise SystemExit(
            f"error: {config} must be "
            f"{json.dumps(DEFAULT_FRAMEWORKS)} for the published build; "
            "a build of other frameworks is not supported yet"
        )
    defs = {}
    for fid in cfg["frameworks"]:
        path = SRC / "frameworks" / fid / "framework.json"
        if not path.exists():
            raise SystemExit(f"error: {path} is missing")
        defs[fid] = json.loads(path.read_text(encoding="utf-8"))
    primary = defs.get(cfg["primary"])
    if (
        primary is None
        or Role(primary.get("role", Role.SUPPLEMENT)) is not Role.PRIMARY
    ):
        raise SystemExit(
            f"error: {cfg['primary']} is not a primary framework definition"
        )
    return defs


def frameworks_js() -> str:
    body = json.dumps(framework_defs(), ensure_ascii=False, separators=(",", ":"))
    return (
        "/* Generated from app/frameworks/<id>/framework.json"
        " by scripts/build_app.py. */\n"
        f"const FRAMEWORK_DEFS = Object.freeze({body});"
    )


def catalogs_js() -> str:
    """The message catalogs, app/i18n/<locale>.json, as one frozen object (#80).

    Embedded rather than fetched: the dashboard is one file that must work opened from
    disk (R-60), so nothing can be loaded at run time. English
    first, then the rest by name, so the output is stable.
    """
    files = sorted(
        (SRC / "i18n").glob("*.json"), key=lambda p: (p.stem != Locale.EN, p.stem)
    )
    catalogs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in files}
    if Locale.EN not in catalogs:
        raise SystemExit("error: app/i18n/en.json, the source catalog, is missing")
    body = json.dumps(catalogs, ensure_ascii=False, separators=(",", ":"))
    # Framework content translations (D-60). English is the definitions themselves,
    # so only the other languages are embedded.
    framework = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((SRC / "i18n" / "framework").glob("*.json"))
        if p.stem != Locale.EN
    }
    fw = json.dumps(framework, ensure_ascii=False, separators=(",", ":"))
    return (
        "/* Generated from app/i18n/*.json by scripts/build_app.py. */\n"
        f"const I18N_CATALOGS = Object.freeze({body});\n"
        f"const FRAMEWORK_I18N = Object.freeze({fw});"
    )


class _Scripts(HTMLParser):
    """Every <script> in a page: its attributes, and its text as the browser sees it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.found: list[tuple[list[tuple[str, str | None]], str]] = []
        self._open: list | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":  # enum-ok: an HTML tag name from html.parser
            self._open = [attrs, []]

    def handle_data(self, data):
        if self._open is not None:
            self._open[1].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._open is not None:  # enum-ok: an HTML tag name
            self.found.append((self._open[0], "".join(self._open[1])))
            self._open = None


def inline_script(html: str) -> str:
    """The text of the page's one inline script, exactly as the browser sees it.

    Read with an HTML parser, not a pattern: the policy's hash has to be of what the
    browser executes, and a pattern for a tag misses the spellings a parser does not."""
    parser = _Scripts()
    parser.feed(html)
    parser.close()
    inline = [text for attrs, text in parser.found if not attrs]
    if len(inline) != 1 or len(parser.found) != 1:
        raise SystemExit(
            "error: the page must have exactly one <script>, with no attributes; "
            f"found {len(parser.found)}"
        )
    return inline[0]


def script_hash(html: str) -> str:
    """The CSP source for that script: 'sha256-' and the base64 of its SHA-256."""
    digest = hashlib.sha256(inline_script(html).encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


# Directives a <meta> policy cannot carry; browsers ignore them there.
HEADER_ONLY = ("frame-ancestors",)


def csp_policy(html: str, *, header: bool) -> str:
    """The page policy. script-src names this page's script by hash, with no
    'unsafe-inline': a script, an event handler or a javascript: URL that arrives in
    the page by any other route is refused by the browser, whatever the page failed to
    escape. Style stays inline (the app styles itself), and nothing can reach another
    origin, which is what turns an injection into a blocked request, not a leak.

    The same policy is sent by the proxy as a header and carried by the page as a
    <meta> tag, so it also holds on the static example page and in a copy opened from
    disk, which cannot set headers. Only the header can say frame-ancestors."""
    directives = [
        "default-src 'none'",
        f"script-src {script_hash(html)}",
        "style-src 'unsafe-inline'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "font-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
    return "; ".join(d for d in directives if header or not d.startswith(HEADER_ONLY))


def csp_header(html: str) -> str:
    """The proxy's header, as the Caddy snippet proxy/Caddyfile imports."""
    return (
        "# GENERATED by scripts/build_app.py from docs/app/index.html. Do not edit.\n"
        "# script-src is the SHA-256 of the page's one inline script, so it changes\n"
        "# with every build. proxy/Caddyfile imports this file inside its `header`\n"
        "# block (#154).\n"
        f'Content-Security-Policy "{csp_policy(html, header=True)}"\n'
    )


def csp_meta(html: str) -> str:
    """The same policy as a tag, for the first child of the page's <head>."""
    policy = csp_policy(html, header=False)
    return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'


def main() -> int:
    shell = (SRC / "index.html").read_text(encoding="utf-8")
    for mark in (CSS_MARK, JS_MARK, CSP_MARK):
        if mark not in shell:
            print(f"error: {mark} missing from app/index.html", file=sys.stderr)
            return 1

    css_files = ordered(SRC / "css", ".css")
    js_files = ordered(SRC / "js", ".js")
    if not css_files or not js_files:
        print("error: no sources found under app/", file=sys.stderr)
        return 1

    # Blank line between modules, matching how the sections were separated when
    # this was one file. Keeps the generated output stable and readable.
    css = "\n\n".join(p.read_text(encoding="utf-8").strip("\n") for p in css_files)
    js = (
        "\n\n".join(
            [catalogs_js(), frameworks_js()]
            + [p.read_text(encoding="utf-8").strip("\n") for p in js_files]
        )
        + "\n"
    )

    html = shell.replace(CSS_MARK, css).replace(JS_MARK, js)
    # The policy names the script by hash, so it is filled in once the script is final.
    html = html.replace(CSP_MARK, csp_meta(html))
    if not html.startswith("<!--"):
        html = BANNER + html

    OUT.parent.mkdir(parents=True, exist_ok=True)
    previous = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    OUT.write_text(html, encoding="utf-8")

    CSP_OUT.write_text(csp_header(html), encoding="utf-8")
    defs = framework_defs()
    primary = json.loads(FRAMEWORKS_CONFIG.read_text(encoding="utf-8"))["primary"]
    MANIFEST_OUT.write_text(manifest_json(defs, primary), encoding="utf-8")

    changed = "unchanged" if previous == html else "updated"
    print(
        f"{changed}: {OUT.relative_to(ROOT)} "
        f"({len(html):,} bytes from {len(css_files)} css + {len(js_files)} js)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
