#!/usr/bin/env python3
"""Keep the dashboard's ways of turning text into markup few, and reviewed.

The dashboard is one file whose page policy has to allow inline script (R-01), so the
only thing standing between a colleague's typed text and script running in the CMIO's
session is that every value is escaped on the way into markup. tests/test_injection.py
proves that today, by poisoning every field and rendering every screen. This is the
tripwire for tomorrow's code, before a test has to find it.

What it refuses, in app/js (the built file is generated from it):

    always          eval(), new Function(), document.write(), insertAdjacentHTML(),
                    an outerHTML assignment, a `srcdoc` assignment, a javascript: URL,
                    a string passed to setTimeout/setInterval, an on*="..." handler
                    written into markup
    a URL           href=, src=, action= and the like with an interpolated value,
                    unless the line says `url-ok: <why>` (a link built from a person's
                    text goes through safeUrl(), which only lets http and https pass)
    a ratchet       an interpolated value inside a quoted attribute that is not wrapped
                    in esc(), bdi(), t(), tHtml() or tf(); and an assignment to
                    innerHTML. Both are counted per file in
                    scripts/injection_baseline.json, and a new one fails. The
                    existing ones were each read and come from code (ids, indexes,
                    booleans, constants), not from a person.

`xss-ok: <reason>` on the line excuses one, and the reason is mandatory. The attribute
rule is the shape of the bug the payload test found: `class="tag ${status}"`, where a
stored status became the attribute.

What it cannot see, by design: a value escaped for the wrong context (esc() is right
for text and quoted attributes, wrong inside a URL or CSS), a value that reaches an
innerHTML through a variable built elsewhere, and any file that is not under app/js.
The payload test covers those by behavior.

    python scripts/check_injection.py                     check
    python scripts/check_injection.py --update-baseline   ratchet down only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "js"
BASELINE = Path(__file__).resolve().parent / "injection_baseline.json"

# Generated from CHAI's published content; data, not code.
DATA_FILES = {"05-te-metrics.js"}

OK_MARK = re.compile(r"(?:xss-ok|url-ok):\s*\S")
URL_MARK = re.compile(r"url-ok:\s*\S")

FORBIDDEN = {
    "eval()": re.compile(r"\beval\s*\("),
    "new Function()": re.compile(r"\bnew\s+Function\b"),
    "document.write()": re.compile(r"\bdocument\s*\.\s*write(?:ln)?\s*\("),
    "insertAdjacentHTML()": re.compile(r"\binsertAdjacentHTML\b"),
    "an outerHTML assignment": re.compile(r"\.outerHTML\s*[+]?="),
    "a srcdoc assignment": re.compile(r"\.srcdoc\s*[+]?=(?!=)"),
    "a javascript: URL": re.compile(r"javascript:", re.I),
    "a string passed to a timer": re.compile(r"\bset(?:Timeout|Interval)\(\s*[\"'`]"),
    "an on*= handler written into markup": re.compile(
        r"\bon[a-z]{3,}\s*=\s*[\"']", re.I
    ),
}

URL_ATTR = re.compile(
    r"(?<![\w-])(?:href|src|action|formaction|poster|data|xlink:href|ping)\s*=\s*[\"'][^\"']*\$\{"
)
ATTR_START = re.compile(r"[\w:-]+=([\"'])")
ESCAPED = re.compile(r"^\s*(?:esc|bdi|t|tHtml|tf|safeUrl)\(")
INNER_HTML = re.compile(r"\.innerHTML\s*[+]?=(?!=)")


def code_only(source: str) -> list[tuple[str, str]]:
    """(code, comment) per line, with comments removed so a sentence about eval()
    does not count. A `//` inside a string such as https:// is not a comment: it must
    follow whitespace or start the line."""
    out = []
    in_block = False
    for line in source.split("\n"):
        code, comment = line, ""
        if in_block:
            end = line.find("*/")
            if end < 0:
                out.append(("", line))
                continue
            comment, code, in_block = line[: end + 2], line[end + 2 :], False
        while True:
            start = code.find("/*")
            if start < 0:
                break
            end = code.find("*/", start + 2)
            if end < 0:
                comment += code[start:]
                code, in_block = code[:start], True
                break
            comment += code[start : end + 2]
            code = code[:start] + code[end + 2 :]
        m = re.search(r"(?:^|\s)//(.*)$", code)
        if m:
            comment += m.group(0)
            code = code[: m.start()]
        out.append((code, comment))
    return out


def attribute_interpolations(code: str) -> list[str]:
    """The expression of every `${...}` inside a quoted attribute value. Quotes inside
    an interpolation (`class="tag ${st||"none"}"`) belong to the expression, so the
    value ends at the first quote outside any `${...}`."""
    found: list[str] = []
    for start in ATTR_START.finditer(code):
        quote, i = start.group(1), start.end()
        while i < len(code) and code[i] != quote:
            if code.startswith("${", i):
                depth, j = 1, i + 2
                while j < len(code) and depth:
                    depth += {"{": 1, "}": -1}.get(code[j], 0)
                    j += 1
                found.append(code[i + 2 : j - 1])
                i = j
            else:
                i += 1
    return found


def scan(path: str, source: str) -> tuple[list[str], Counter]:
    """Hard problems (always failures), and this file's ratchet counts."""
    problems: list[str] = []
    counts: Counter = Counter()
    for n, (code, comment) in enumerate(code_only(source), 1):
        excused = bool(OK_MARK.search(comment))
        for what, pattern in FORBIDDEN.items():
            if pattern.search(code) and not excused:
                problems.append(f"{path}:{n}: {what}")
        if URL_ATTR.search(code) and not URL_MARK.search(comment):
            problems.append(
                f"{path}:{n}: a URL attribute with an interpolated value; "
                "build it with safeUrl(), or say `url-ok: <why>`"
            )
        if excused:
            continue
        if INNER_HTML.search(code):
            counts["innerHTML"] += 1
        for expr in attribute_interpolations(code):
            if not ESCAPED.match(expr):
                counts["attribute"] += 1
    return problems, counts


def scan_tree(root: Path) -> tuple[list[str], dict[str, dict[str, int]]]:
    problems: list[str] = []
    counts: dict[str, dict[str, int]] = {}
    for path in sorted(root.rglob("*.js")):
        if path.name in DATA_FILES:
            continue
        rel = path.relative_to(ROOT).as_posix()
        found, c = scan(rel, path.read_text(encoding="utf-8"))
        problems += found
        if c:
            counts[rel] = dict(c)
    return problems, counts


def ratchet(
    counts: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]
) -> tuple[list[str], list[str]]:
    """(growth, stale): what grew past the baseline, and what shrank below it."""
    growth, stale = [], []
    for rel in sorted(set(counts) | set(baseline)):
        for kind in sorted(set(counts.get(rel, {})) | set(baseline.get(rel, {}))):
            now, was = (
                counts.get(rel, {}).get(kind, 0),
                baseline.get(rel, {}).get(kind, 0),
            )
            if now > was:
                growth.append(f"{rel}: {kind} {was} -> {now}")
            elif now < was:
                stale.append(f"{rel}: {kind} {was} -> {now}")
    return growth, stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--allow-growth", action="store_true")
    args = parser.parse_args(argv)

    problems, counts = scan_tree(JS)
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    growth, stale = ratchet(counts, baseline)

    if args.update_baseline:
        if growth and not args.allow_growth:
            print("refusing to grow the baseline:\n  " + "\n  ".join(growth))
            return 1
        BASELINE.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
        total = sum(sum(c.values()) for c in counts.values())
        print(f"baseline written: {total} reviewed use(s)")
        return 0

    out: list[str] = list(problems)
    out += [
        f"{g} (a new, unreviewed one: escape it, or `xss-ok: <why>`)" for g in growth
    ]
    out += [
        f"{s} (fixed: ratchet the baseline down with --update-baseline)" for s in stale
    ]
    for line in out:
        print(f"  {line}", file=sys.stderr)
    if out:
        print(f"check-injection: {len(out)} problem(s)", file=sys.stderr)
        return 1
    total = sum(sum(c.values()) for c in counts.values())
    print(f"check-injection: ok ({total} baselined, each read and from code)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
