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

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_i18n import Locale

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app"
OUT = ROOT / "docs" / "app" / "index.html"
# The proxy's Content-Security-Policy header, generated from the built page (#154).
CSP_OUT = ROOT / "proxy" / "csp.caddy"

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


def framework_defs(
    config: Path = FRAMEWORKS_CONFIG,
    custom: bool = False,
    frameworks: Path | None = None,
) -> dict:
    """The selected framework definitions, in the config's order, checked against
    the config: the primary is listed, its definition says it is the primary, and it
    is the only one.

    The published build (custom=False) must be the default config; a build of other
    frameworks (custom=True, from --config) writes only to its own --out directory.
    `frameworks` is where the definitions are read from: app/frameworks/, unless a
    test builds a copy it has altered."""
    cfg = json.loads(config.read_text(encoding="utf-8"))
    if not custom and cfg != DEFAULT_FRAMEWORKS:
        raise SystemExit(
            f"error: {config} must be "
            f"{json.dumps(DEFAULT_FRAMEWORKS)} for the published build; "
            "build other frameworks with --config FILE --out DIR"
        )
    defs = {}
    for fid in cfg["frameworks"]:
        path = (frameworks or SRC / "frameworks") / fid / "framework.json"
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
    others = [
        f
        for f, d in defs.items()
        if f != cfg["primary"] and Role(d.get("role")) is Role.PRIMARY
    ]
    if others:
        raise SystemExit(f"error: a build has one primary; {others} are primaries too")
    return defs


def js_json(value: object) -> str:
    """JSON for the page's inline script. A definition or a catalog may hold any
    text, and a "</script>" (or "<!--") inside the script would end it and turn the
    rest into markup, so every "<" is written as its JSON escape. U+2028 and U+2029
    are escaped too: they end a line in older JavaScript but not in JSON."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def frameworks_js(defs: dict | None = None, published: bool = True) -> str:
    defs = framework_defs() if defs is None else defs
    body = js_json(defs)
    primary = next(f for f, d in defs.items() if Role(d["role"]) is Role.PRIMARY)
    build = js_json(
        {
            "primary": primary,
            "frameworks": list(defs),
            "published": published,
            # The framework of a record made before records were stamped.
            "legacy": DEFAULT_FRAMEWORKS["primary"],
        },
    )
    return (
        "/* Generated from app/frameworks/<id>/framework.json"
        " by scripts/build_app.py. */\n"
        f"const FRAMEWORK_DEFS = Object.freeze({body});\n"
        "/* Which build this is: the published one (CHAI and OPTICA), or one of\n"
        "   other frameworks built with --config (#168). */\n"
        f"const BUILD = Object.freeze({build});"
    )


# The engine and the project setup serve every framework; any other directory under
# app/js/10-frameworks/ is one framework's own code, named <nn>-<id>.
FRAMEWORK_CODE_DIR = "10-frameworks"
SHARED_CODE = frozenset({"engine", "project"})


def framework_code(path: Path, selected: set[str], src: Path = SRC) -> bool:
    """Whether a source file belongs in a build of `selected` frameworks."""
    parts = path.relative_to(src / "js").parts
    if len(parts) < 3 or parts[0] != FRAMEWORK_CODE_DIR:
        return True
    m = re.match(r"^\d+-(.+)$", parts[1])
    owner = m.group(1) if m else parts[1]
    return owner in SHARED_CODE or owner in selected


PROTECTED = ("docs", "proxy", "app")


def out_dir_problem(out: Path) -> str | None:
    """A build of other frameworks never writes the published page, the proxy's
    policy or the sources: refuse an --out under docs/, proxy/ or app/.

    Checked on the files it would write as well as the directory, each resolved,
    so a symbolic link cannot point a write into them; and by the file system's own
    identity of each existing ancestor, so a case-insensitive file system cannot
    reach them by another spelling."""
    targets = [out, out / "index.html", out / "csp.caddy"]
    for target in targets:
        resolved = target.resolve()
        for name in PROTECTED:
            tracked = ROOT / name
            if resolved == tracked or resolved.is_relative_to(tracked):
                return f"--out {out} writes under {name}/"
            for ancestor in [resolved, *resolved.parents]:
                same = ancestor.exists() and tracked.exists()
                if same and os.path.samefile(ancestor, tracked):
                    return f"--out {out} writes under {name}/"
    return None


def namespace_owners(src: Path = SRC) -> dict[str, str]:
    """Every catalog namespace a framework under app/frameworks/ owns, and its id."""
    owners = {}
    for path in sorted((src / "frameworks").glob("*/framework.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for ns in doc.get("namespaces", [doc["id"]]):
            owners[ns] = doc["id"]
    return owners


def catalogs_js(
    defs: dict | None = None, src: Path = SRC, frameworks: Path | None = None
) -> str:
    """The message catalogs, app/i18n/<locale>.json, as one frozen object (#80).

    Embedded rather than fetched: the dashboard is one file that must work opened from
    disk (R-60), so nothing can be loaded at run time. English first, then the rest by
    name, so the output is stable.

    Only the selected frameworks' text ships (#168): a key in a namespace another
    framework owns is left out, from the shell's catalogs and the framework ones. A
    developer's framework may bring its own translations, app/frameworks/<id>/i18n/
    <locale>.json; FRAMEWORK_LOCALES says which languages each framework has, so a
    screen can say when its words are shown in English (R-65).
    """
    defs = framework_defs() if defs is None else defs
    selected = {ns: fid for fid, d in defs.items() for ns in d.get("namespaces", [fid])}
    left_out = set(namespace_owners(src)) - set(selected)

    def keep(cat: dict) -> dict:
        return {k: v for k, v in cat.items() if k.split(".", 1)[0] not in left_out}

    files = sorted(
        (src / "i18n").glob("*.json"), key=lambda p: (p.stem != Locale.EN, p.stem)
    )
    catalogs = {p.stem: keep(json.loads(p.read_text(encoding="utf-8"))) for p in files}
    if Locale.EN not in catalogs:
        raise SystemExit("error: app/i18n/en.json, the source catalog, is missing")
    body = js_json(catalogs)
    # Framework content translations (D-60). English is the definitions themselves,
    # so only the other languages are embedded.
    framework = {
        p.stem: keep(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted((src / "i18n" / "framework").glob("*.json"))
        if p.stem != Locale.EN
    }
    for fid in defs:
        own = (frameworks or src / "frameworks") / fid / "i18n"
        for path in sorted(own.glob("*.json")):
            if path.stem == Locale.EN:
                continue
            entries = json.loads(path.read_text(encoding="utf-8"))
            have = framework.setdefault(path.stem, {})
            clash = sorted(set(entries) & set(have))
            if clash:
                raise SystemExit(
                    f"error: {path} repeats keys another catalog has: {clash[:3]}"
                )
            have.update(entries)
    locales = {
        fid: sorted(
            loc
            for loc, cat in framework.items()
            if any(selected.get(k.split(".", 1)[0]) == fid for k in cat)
        )
        for fid in defs
    }
    fw = js_json(framework)
    loc = js_json(locales)
    return (
        "/* Generated from app/i18n/*.json by scripts/build_app.py. */\n"
        f"const I18N_CATALOGS = Object.freeze({body});\n"
        f"const FRAMEWORK_I18N = Object.freeze({fw});\n"
        f"const FRAMEWORK_LOCALES = Object.freeze({loc});"
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


def main(argv: list[str] | None = None, frameworks: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the dashboard from app/.")
    parser.add_argument("--config", type=Path, help="a build of other frameworks")
    parser.add_argument("--out", type=Path, help="where it goes (with --config)")
    args = parser.parse_args(argv)
    custom = args.config is not None
    if custom != (args.out is not None):
        print("error: --config and --out go together", file=sys.stderr)
        return 2
    if custom:
        problem = out_dir_problem(args.out)
        if problem:
            print(f"error: {problem}, which the published build owns", file=sys.stderr)
            return 2
        defs = framework_defs(args.config.resolve(), custom=True, frameworks=frameworks)
        out, csp_out = args.out / "index.html", args.out / "csp.caddy"
    else:
        defs = framework_defs()
        out, csp_out = OUT, CSP_OUT

    shell = (SRC / "index.html").read_text(encoding="utf-8")
    for mark in (CSS_MARK, JS_MARK, CSP_MARK):
        if mark not in shell:
            print(f"error: {mark} missing from app/index.html", file=sys.stderr)
            return 1

    css_files = ordered(SRC / "css", ".css")
    js_files = [p for p in ordered(SRC / "js", ".js") if framework_code(p, set(defs))]
    if not css_files or not js_files:
        print("error: no sources found under app/", file=sys.stderr)
        return 1

    # Blank line between modules, matching how the sections were separated when
    # this was one file. Keeps the generated output stable and readable.
    css = "\n\n".join(p.read_text(encoding="utf-8").strip("\n") for p in css_files)
    js = (
        "\n\n".join(
            [
                catalogs_js(defs, frameworks=frameworks),
                frameworks_js(defs, published=not custom),
            ]
            + [p.read_text(encoding="utf-8").strip("\n") for p in js_files]
        )
        + "\n"
    )

    html = shell.replace(CSS_MARK, css).replace(JS_MARK, js)
    # The policy names the script by hash, so it is filled in once the script is final.
    html = html.replace(CSP_MARK, csp_meta(html))
    if not html.startswith("<!--"):
        html = BANNER + html

    out.parent.mkdir(parents=True, exist_ok=True)
    previous = out.read_text(encoding="utf-8") if out.exists() else None
    out.write_text(html, encoding="utf-8")

    csp_out.write_text(csp_header(html), encoding="utf-8")

    changed = "unchanged" if previous == html else "updated"
    shown = (
        out.resolve().relative_to(ROOT) if out.resolve().is_relative_to(ROOT) else out
    )
    print(
        f"{changed}: {shown} "
        f"({len(html):,} bytes from {len(css_files)} css + {len(js_files)} js)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
