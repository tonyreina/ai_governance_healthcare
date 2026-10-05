#!/usr/bin/env python3
"""Fail if a file contains a non-Latin character that looks like an ASCII letter.

Why this exists: a link shared with this project spelled "who-highlights" with
U+043E CYRILLIC SMALL LETTER O in place of the ASCII "o". The two are visually
identical in almost every font. In a URL that is a phishing signature; in source
or docs it silently breaks search, anchors and copy-paste, and it is invisible in
review.

Legitimate typography (em dashes, curly quotes, accented Latin, emoji) is left
alone. This only flags characters from scripts whose letters are confusable with
ASCII Latin ones.

Run via: pixi run check-homographs   (also wired into prek)
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

# Scripts containing glyphs that render like ASCII Latin letters or digits.
CONFUSABLE_RANGES: list[tuple[int, int, str]] = [
    (0x0370, 0x03FF, "Greek"),
    (0x0400, 0x04FF, "Cyrillic"),
    (0x0500, 0x052F, "Cyrillic Supplement"),
    (0x0530, 0x058F, "Armenian"),
    (0x2160, 0x217F, "Roman numeral forms"),
    (0xFF00, 0xFFEF, "Fullwidth forms"),
    (0x1D400, 0x1D7FF, "Mathematical alphanumerics"),
]


def confusable_script(code: int) -> str | None:
    for low, high, name in CONFUSABLE_RANGES:
        if low <= code <= high:
            return name
    return None


def check(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # binary or unreadable: not our business

    problems = []
    for index, char in enumerate(text):
        script = confusable_script(ord(char))
        if script is None:
            continue
        line = text.count("\n", 0, index) + 1
        col = index - (text.rfind("\n", 0, index) + 1) + 1
        name = unicodedata.name(char, "unnamed")
        context = text[max(0, index - 40) : index + 40].replace("\n", " ")
        problems.append(
            f"{path}:{line}:{col}: U+{ord(char):04X} {name} ({script})\n"
            f"    ...{context}...\n"
            f"    Replace with the ASCII equivalent."
        )
    return problems


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(
        p
        for p in Path(".").rglob("*")
        if p.is_file()
        and not any(part in {".git", ".pixi", "site", ".cache"} for part in p.parts)
    )

    problems = [msg for path in paths if path.is_file() for msg in check(path)]
    for msg in problems:
        print(msg, file=sys.stderr)

    if problems:
        print(f"\n{len(problems)} confusable character(s) found.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
