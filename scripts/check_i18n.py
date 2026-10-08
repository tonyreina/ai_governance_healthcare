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

ROOT = Path(__file__).resolve().parent.parent
CATALOGS = ROOT / "app" / "i18n"
SOURCES = [ROOT / "app" / "index.html", *sorted((ROOT / "app" / "js").rglob("*.js"))]
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
        asked |= set(T_CALL.findall(text)) | attrs
        named |= set(KEY_LITERAL.findall(text)) | attrs
    keys = {k for k in source if k != META}
    return [
        f"the app asks for {k!r}, which en.json lacks" for k in sorted(asked - keys)
    ] + [f"app/i18n/en.json: {k!r} is never used" for k in sorted(keys - named)]


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
    texts = {str(p): p.read_text(encoding="utf-8") for p in SOURCES}
    problems += usage_problems(source, texts)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if problems:
        print(f"check-i18n: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"check-i18n: ok ({len(catalogs)} catalogs, {len(source) - 1} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
