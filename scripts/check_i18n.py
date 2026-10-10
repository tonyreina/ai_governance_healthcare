#!/usr/bin/env python3
"""Keep the dashboard's message catalogs complete and honest (#80).

app/i18n/en.json is the source. Every other catalog must:

* have exactly its keys: a missing key would show English in the middle of another
  language, and an extra one is a translation of nothing;
* keep every {placeholder}, so a name or a count is never dropped or invented;
* give every plural category the language needs (Intl.PluralRules names them; the
  browser test checks this table against the real thing);
* hold no markup: t() returns text, and the caller escapes it;
* record a reviewer only for a safety-bearing key (en.json "@meta".safety), because a
  reviewer is what lets a translated warning show at all (D-59).

And every key in en.json must be used by the app, and every key the app names must
exist, so the catalog cannot rot into a list of strings nobody shows.

    pixi run check-i18n
"""

from __future__ import annotations

import json
import re
import sys
from enum import StrEnum
from pathlib import Path

# check_framework holds the key rule the build and the engine share.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_framework as ck

ROOT = Path(__file__).resolve().parent.parent
CATALOGS = ROOT / "app" / "i18n"
SOURCES = [ROOT / "app" / "index.html", *sorted((ROOT / "app" / "js").rglob("*.js"))]
# Framework definitions name shell catalog keys for their statuses and phases (#168).
DEFINITIONS = sorted((ROOT / "app" / "frameworks").glob("*/framework.json"))
DEFINITION_MSG = re.compile(r'"msg"\s*:\s*"([^"]+)"')
META = "@meta"


class Locale(StrEnum):
    """The dashboard's languages: Locale in app/js/00-core/02-i18n.js, and the catalog
    file names. tests/test_i18n.py checks the two lists agree."""

    EN = "en"
    ES = "es"
    FR = "fr"
    DE = "de"
    HI = "hi"
    RU = "ru"
    ZH_HANS = "zh-Hans"
    HE = "he"


# CLDR plural categories each supported language uses for cardinal numbers.
# tests/test_i18n.py checks this against Intl.PluralRules in a real browser.
PLURALS: dict[Locale, frozenset[str]] = {
    Locale.EN: frozenset({"one", "other"}),
    Locale.ES: frozenset({"one", "many", "other"}),
    Locale.FR: frozenset({"one", "many", "other"}),
    Locale.DE: frozenset({"one", "other"}),
    Locale.HI: frozenset({"one", "other"}),
    Locale.RU: frozenset({"one", "few", "many", "other"}),
    Locale.ZH_HANS: frozenset({"other"}),
    Locale.HE: frozenset({"one", "two", "other"}),
}

PLACEHOLDER = re.compile(r"\{(\w+)\}")
KEY_LITERAL = re.compile(r"""["'`]([a-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)+)["'`]""")


def placeholders(value: object) -> set[str]:
    if isinstance(value, dict):
        return (
            set().union(*(placeholders(v) for v in value.values())) if value else set()
        )
    return set(PLACEHOLDER.findall(value)) if isinstance(value, str) else set()


def strings(value: object) -> list[str]:
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)]
    return [value] if isinstance(value, str) else []


def catalog_problems(
    locale: str, catalog: dict, source: dict, safety: set[str]
) -> list[str]:
    """What is wrong with one translated catalog, compared with the source."""
    where = f"app/i18n/{locale}.json"
    problems = []
    meta = catalog.get(META)
    if not isinstance(meta, dict):
        return [f"{where}: no {META} block"]
    if meta.get("locale") != locale:
        problems.append(
            f"{where}: {META}.locale is {meta.get('locale')!r}, not {locale!r}"
        )
    if not meta.get("name"):
        problems.append(f"{where}: {META}.name (the language's own name) is missing")
    if locale not in PLURALS:
        problems.append(
            f"{where}: {locale!r} has no plural rules in check_i18n.PLURALS"
        )
    reviewers = meta.get("reviewers", {})
    if not isinstance(reviewers, dict):
        problems.append(f"{where}: {META}.reviewers must be an object")
        reviewers = {}
    for key, who in reviewers.items():
        if key not in safety:
            problems.append(
                f"{where}: reviewer recorded for {key!r}, which is not safety-bearing"
            )
        elif not isinstance(who, str) or not who.strip():
            problems.append(f"{where}: reviewer for {key!r} is empty")

    keys = {k for k in catalog if k != META}
    expected = {k for k in source if k != META}
    problems += [f"{where}: missing {k!r}" for k in sorted(expected - keys)]
    problems += [f"{where}: {k!r} is not in en.json" for k in sorted(keys - expected)]
    for key in sorted(keys & expected):
        value, original = catalog[key], source[key]
        if placeholders(value) != placeholders(original):
            problems.append(
                f"{where}: {key!r} has placeholders {sorted(placeholders(value))}, "
                f"en.json has {sorted(placeholders(original))}"
            )
        if isinstance(original, dict):
            if not isinstance(value, dict):
                problems.append(f"{where}: {key!r} is a plural in en.json and not here")
            else:
                lacking = PLURALS.get(locale, frozenset()) - set(value)
                if lacking:
                    problems.append(
                        f"{where}: {key!r} lacks plural forms {sorted(lacking)}"
                    )
        if any("<" in s for s in strings(value)):
            problems.append(f"{where}: {key!r} holds markup; the caller builds markup")
    return problems


def source_problems(source: dict) -> list[str]:
    problems = []
    meta = source.get(META) or {}
    safety = set(meta.get("safety") or [])
    problems += [
        f"app/i18n/en.json: safety key {k!r} does not exist"
        for k in sorted(safety - set(source))
    ]
    for key, value in source.items():
        if key == META:
            continue
        if isinstance(value, dict) and "other" not in value:
            problems.append(f"app/i18n/en.json: plural {key!r} has no 'other' form")
        if any("<" in s for s in strings(value)):
            problems.append(f"app/i18n/en.json: {key!r} holds markup")
    return problems


T_CALL = re.compile(r"""\b(?:t|tEn|tHtml)\(\s*["'`]([^"'`$]+)["'`]""")


def usage_problems(source: dict, texts: dict[str, str]) -> list[str]:
    """Keys the app asks for that do not exist, and keys nothing names.

    A key is "asked for" when it is a literal argument of t(), tEn() or tHtml(), or a
    data-i18n attribute. It is "named" when it appears as a string literal anywhere
    in the app, which also counts a key kept in a table such as SEARCH_HINT.
    """
    asked: set[str] = set()
    named: set[str] = set()
    for text in texts.values():
        attrs = set(re.findall(r'data-i18n(?:-\w+)?="([^"]+)"', text))
        msgs = set(DEFINITION_MSG.findall(text))
        asked |= set(T_CALL.findall(text)) | attrs | msgs
        named |= set(KEY_LITERAL.findall(text)) | attrs | msgs
    keys = {k for k in source if k != META}
    return [
        f"the app asks for {k!r}, which en.json lacks" for k in sorted(asked - keys)
    ] + [f"app/i18n/en.json: {k!r} is never used" for k in sorted(keys - named)]


# Text the app puts on screen at run time, after a click or a save. The pseudo-locale
# ratchet in tests/test_i18n.py only sees what a screen shows when it opens, so these
# would slip past it: a toast, a label swapped by a handler, a tooltip set by code.
RUNTIME_LITERAL = re.compile(
    r"""\b(?:toast|fatalError|setMode)\(\s*["'`][A-Za-z]"""
    r"""|\.(?:textContent|innerText|title|placeholder)\s*=[^;]*?["'`][A-Za-z][a-z]+\s"""
    r"""|setAttribute\(\s*["'](?:title|aria-label|placeholder|alt)["']\s*,\s*["'`][A-Za-z]"""
)
RUNTIME_OK = "i18n-ok:"


def runtime_literal_problems(texts: dict[str, str]) -> list[str]:
    """English handed straight to the screen by code, instead of through t().

    `i18n-ok: <reason>` on the line excuses one that is not language (a symbol, a
    product name); the reason is mandatory.
    """
    problems = []
    for name, text in texts.items():
        if not name.endswith(".js"):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            ok = line.split(RUNTIME_OK, 1)
            if len(ok) == 2 and ok[1].strip():
                continue
            if RUNTIME_LITERAL.search(line):
                where = (
                    Path(name).relative_to(ROOT) if Path(name).is_absolute() else name
                )
                problems.append(f"{where}:{n}: English set on screen without t()")
    return problems


# Left and right that should follow the reading direction (Hebrew is right to left).
# The logical forms (margin-inline-start, text-align:start, inset-inline-start, the
# border-start-end-radius family) mirror on their own; these do not.
_LENGTH = r"-?[\d.]+[a-z%]*"
PHYSICAL_DIRECTION = re.compile(
    r"(?:margin|padding|border)-(?:left|right)\b"
    r"|text-align:\s*(?:left|right)\b"
    r"|float:\s*(?:left|right)\b"
    r"|(?<![\w-])(?:left|right)\s*:"
    r"|border-(?:top|bottom)-(?:left|right)-radius"
    r"|box-shadow:\s*inset\s+(?!0[\s;])" + _LENGTH
)
_VALUE = rf"(?:{_LENGTH}|auto)"
# margin/padding: top right bottom left. Mirrors only if right equals left.
SPACING_4 = re.compile(
    rf"(?<![\w-])(?:margin|padding)\s*:\s*{_VALUE}\s+({_VALUE})\s+{_VALUE}\s+({_VALUE})"
)
# border-radius: top-left top-right bottom-right bottom-left. Mirrors only if each
# pair across the vertical axis matches.
RADIUS_4 = re.compile(
    rf"(?<![\w-])border-radius\s*:\s*({_VALUE})\s+({_VALUE})\s+({_VALUE})\s+({_VALUE})"
)
INLINE_STYLE = re.compile(r'style="([^"]*)"|cssText\s*=\s*"([^"]*)"')
RTL_OK = "rtl-ok:"
DIRECTION_SOURCES = [ROOT / "app" / "css" / "app.css"]


def uneven(line: str) -> bool:
    return any(m.group(1) != m.group(2) for m in SPACING_4.finditer(line)) or any(
        m.group(1) != m.group(2) or m.group(3) != m.group(4)
        for m in RADIUS_4.finditer(line)
    )


def physical_direction_problems(texts: dict[str, str]) -> list[str]:
    """Layout tied to left or right, in the stylesheet or a script's inline style.

    `rtl-ok: <reason>` on the line excuses one that is symmetric or off screen
    (`left:50%` with a centering transform); the reason is mandatory.
    """
    problems = []
    for name, text in texts.items():
        for n, line in enumerate(text.splitlines(), 1):
            ok = line.split(RTL_OK, 1)
            if len(ok) == 2 and ok[1].strip(" */").strip():
                continue
            if name.endswith(".js"):
                line = " ".join(a or b for a, b in INLINE_STYLE.findall(line))
            if PHYSICAL_DIRECTION.search(line) or uneven(line):
                where = (
                    Path(name).relative_to(ROOT) if Path(name).is_absolute() else name
                )
                problems.append(f"{where}:{n}: left/right will not mirror in Hebrew")
    return problems


def framework_problems(source: dict, catalogs: dict[str, dict]) -> list[str]:
    """The framework content (D-60): app/i18n/framework/en.json is the English the
    definitions hold (tests/test_framework_i18n.py keeps it so), and every other
    language translates exactly those keys, as plain text."""
    problems = []
    for locale in Locale:
        if locale is Locale.EN:
            continue
        where = f"app/i18n/framework/{locale}.json"
        catalog = catalogs.get(str(locale))
        if catalog is None:
            problems.append(f"{where} is missing")
            continue
        problems += [
            f"{where}: missing {k!r}" for k in sorted(set(source) - set(catalog))
        ]
        problems += [
            f"{where}: {k!r} is not in framework/en.json"
            for k in sorted(set(catalog) - set(source))
        ]
        for key, value in catalog.items():
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{where}: {key!r} is empty")
            elif "<" in value:
                problems.append(f"{where}: {key!r} holds markup")
    return problems


def _where(path: Path) -> str:
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def custom_framework_problems(frameworks: Path, shared_source: dict) -> list[str]:
    """A developer's framework (#168, R-65): English is its definition, so it has no
    en file; any other language it brings, app/frameworks/<id>/i18n/<locale>.json,
    holds exactly the keys the definition implies, as plain text, or the check names
    what is missing. A framework whose text lives in app/i18n/framework (CHAI,
    OPTICA) keeps it there, in every language."""
    problems = []
    shared = {k.split(".", 1)[0] for k in shared_source}
    for path in sorted(frameworks.glob("*/framework.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        fid = doc["id"]
        folder = path.parent / "i18n"
        files = sorted(folder.glob("*.json")) if folder.is_dir() else []
        if set(doc.get("namespaces", [fid])) & shared:
            problems += [
                f"{_where(p)}: {fid}'s text lives in app/i18n/framework/" for p in files
            ]
            continue
        want = ck.framework_strings(doc)
        for p in files:
            where = _where(p)
            if p.stem not in {str(loc) for loc in Locale} or p.stem == Locale.EN:
                problems.append(
                    f"{where}: not a translation (English is the definition itself)"
                    if p.stem == Locale.EN
                    else f"{where}: {p.stem!r} is not a language this app offers"
                )
                continue
            catalog = json.loads(p.read_text(encoding="utf-8"))
            missing = sorted(set(want) - set(catalog))
            if missing:
                problems.append(
                    f"{where}: a supplied language must be complete; missing "
                    f"{len(missing)}: {', '.join(missing[:6])}"
                )
            problems += [
                f"{where}: {k!r} is not text {fid}'s definition has"
                for k in sorted(set(catalog) - set(want))
            ]
            for key, value in catalog.items():
                if not isinstance(value, str) or not value.strip():
                    problems.append(f"{where}: {key!r} is empty")
                elif "<" in value:
                    problems.append(f"{where}: {key!r} holds markup")
    return problems


def main() -> int:
    files = sorted(CATALOGS.glob("*.json"))
    catalogs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in files}
    source = catalogs.get(Locale.EN)
    if source is None:
        print("check-i18n: app/i18n/en.json is missing", file=sys.stderr)
        return 1
    safety = set((source.get(META) or {}).get("safety") or [])
    problems = source_problems(source)
    for locale, catalog in catalogs.items():
        if locale != Locale.EN:
            problems += catalog_problems(locale, catalog, source, safety)
    fw_dir = CATALOGS / "framework"
    fw = {
        p.stem: json.loads(p.read_text(encoding="utf-8")) for p in fw_dir.glob("*.json")
    }
    if Locale.EN in fw:
        problems += framework_problems(fw[Locale.EN], fw)
        problems += custom_framework_problems(
            ROOT / "app" / "frameworks", fw[Locale.EN]
        )
    else:
        problems.append("app/i18n/framework/en.json is missing")
    texts = {str(p): p.read_text(encoding="utf-8") for p in SOURCES}
    definitions = {str(p): p.read_text(encoding="utf-8") for p in DEFINITIONS}
    problems += usage_problems(source, {**texts, **definitions})
    problems += runtime_literal_problems(texts)
    problems += physical_direction_problems(
        {
            **{str(p): p.read_text(encoding="utf-8") for p in DIRECTION_SOURCES},
            **{k: v for k, v in texts.items() if k.endswith(".js")},
        }
    )
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if problems:
        print(f"check-i18n: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"check-i18n: ok ({len(catalogs)} catalogs, {len(source) - 1} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
