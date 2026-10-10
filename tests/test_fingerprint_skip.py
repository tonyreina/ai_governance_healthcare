#!/usr/bin/env python3
"""One list of what the fingerprint leaves out, written in five places (#177).

The record fingerprint is computed by three programs: the dashboard
(`CANON_SKIP` in app/js/00-core/12-hash.js), the server's version history
(`_HASH_SKIP` in server/app/routes.py) and the reader's check
(`CANON_SKIP` in examples/load_export.py). Each leaves the same volatile fields
out. If one list gains or loses a field, the same record hashes to two values,
which reads as evidence of a change that never happened. Two more places say
which fields they are, to a person: the `of` sentence every JSON export carries
(`FINGERPRINT_OF`, app/js/20-app/50-exports.js), and docs/exports.md. And the
dashboard's comment gives each field its reason.

This reads all six from the files, without running any of them, and fails if
any differs from the dashboard's list. Then it breaks each one, adding a field
and removing one, and demands the check notice.

    pixi run test-fingerprint-skip
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HASH_JS = "app/js/00-core/12-hash.js"
ROUTES = "server/app/routes.py"
LOADER = "examples/load_export.py"
EXPORTS_JS = "app/js/20-app/50-exports.js"
DOCS = "docs/exports.md"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# --- one reader per place -------------------------------------------------------


def js_set(text: str) -> set[str] | None:
    """`const CANON_SKIP = new Set([ "a", "b", ... ]);`"""
    m = re.search(r"const CANON_SKIP = new Set\(\[(.*?)\]\);", text, re.S)
    if not m:
        return None
    body = re.sub(r"\s+", "", m.group(1)).rstrip(",")
    if not re.fullmatch(r'("[^"\\]*",)*"[^"\\]*"', body):
        return None  # anything but a list of plain string literals is not read
    return set(re.findall(r'"([^"\\]*)"', body))


def js_reasons(text: str) -> set[str] | None:
    """The comment above CANON_SKIP: one line per field (or `a/b`), then its reason."""
    m = re.search(
        r"/\* Excluded from the fingerprint[^\n]*\n(.*?)\n\s*The same list", text, re.S
    )
    if not m:
        return None
    names: set[str] = set()
    for line in m.group(1).splitlines():
        field = re.match(r"\s+([A-Za-z_][\w/]*)\s{2,}\S", line)
        if not field:
            return None
        names.update(field.group(1).split("/"))
    return names


def py_set(text: str, name: str) -> set[str] | None:
    """`NAME = {...}` or `NAME = frozenset({...})`, at module level."""
    for node in ast.parse(text).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "frozenset"
                and len(value.args) == 1
            ):
                value = value.args[0]
            try:
                found = ast.literal_eval(value)
            except ValueError:
                return None
            return set(found) if isinstance(found, set | frozenset) else None
    return None


def prose_fields(text: str) -> set[str] | None:
    """FINGERPRINT_OF: '... with a, b, c and d left out.'"""
    m = re.search(r'const FINGERPRINT_OF = "([^"]*)";', text)
    if not m:
        return None
    words = re.search(r"\bwith (.+?) left out\b", m.group(1))
    if not words:
        return None
    return set(re.split(r", | and |, and ", words.group(1)))


def docs_fields(text: str) -> set[str] | None:
    """docs/exports.md: '... with the volatile fields `a`, `b` ... left out.'"""
    flat = re.sub(r"\s+", " ", text)
    m = re.search(r"with the volatile fields (.+?) left out", flat)
    if not m:
        return None
    return set(re.findall(r"`([^`]+)`", m.group(1)))


READERS: dict[str, tuple[str, Callable[[str], set[str] | None]]] = {
    "the dashboard's CANON_SKIP": (HASH_JS, js_set),
    "the dashboard's reasons for each": (HASH_JS, js_reasons),
    "the server's _HASH_SKIP": (ROUTES, lambda t: py_set(t, "_HASH_SKIP")),
    "load_export.py's CANON_SKIP": (LOADER, lambda t: py_set(t, "CANON_SKIP")),
    "the export's FINGERPRINT_OF sentence": (EXPORTS_JS, prose_fields),
    "docs/exports.md": (DOCS, docs_fields),
}
REFERENCE = "the dashboard's CANON_SKIP"


def problems(texts: dict[str, str]) -> list[str]:
    """Every way the places disagree, given each file's text by path."""
    found = {where: read_(texts[path]) for where, (path, read_) in READERS.items()}
    out = [
        f"{where}: not found where expected" for where, v in found.items() if v is None
    ]
    ref = found[REFERENCE]
    if not ref:
        return [*out, "the dashboard's list is empty or missing"]
    for where, fields in found.items():
        if fields is None or where == REFERENCE:
            continue
        if fields != ref:
            missing, extra = sorted(ref - fields), sorted(fields - ref)
            out.append(f"{where} differs: missing {missing}, extra {extra}")
    return out


def real_texts() -> dict[str, str]:
    return {path: read(path) for path, _ in READERS.values()}


# --- mutations: each place, broken both ways ---------------------------------------

# (place, path, what is replaced, its replacement), each replacing exactly one
# occurrence. "add" puts in a field no other place has; "remove" takes one out.
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "dashboard list: add",
        HASH_JS,
        '"contentHash", "generated",',
        '"contentHash", "generated", "extraField",',
    ),
    ("dashboard list: remove", HASH_JS, '"cardUpdatedAt", "_state",', '"_state",'),
    (
        "dashboard reasons: add",
        HASH_JS,
        "     generated  ",
        "     extraField  a reason\n     generated  ",
    ),
    ("dashboard reasons: remove", HASH_JS, "     cardUpdatedAt        same\n", ""),
    (
        "server: add",
        ROUTES,
        '"contentHash", "generated"}',
        '"contentHash", "generated", "extraField"}',
    ),
    ("server: remove", ROUTES, '"cardUpdatedAt", "_state",', '"_state",'),
    (
        "load_export: add",
        LOADER,
        '    "generated",\n}',
        '    "generated",\n    "extraField",\n}',
    ),
    ("load_export: remove", LOADER, '    "cardUpdatedAt",\n', ""),
    (
        "export sentence: add",
        EXPORTS_JS,
        "contentHash and generated left out",
        "contentHash, extraField and generated left out",
    ),
    ("export sentence: remove", EXPORTS_JS, "cardUpdatedAt, _state", "_state"),
    (
        "docs: add",
        DOCS,
        "`contentHash` and\n`generated`",
        "`contentHash`, `extraField` and\n`generated`",
    ),
    ("docs: remove", DOCS, "`cardUpdatedAt`, `_state`", "`_state`"),
    (
        "dashboard list: a computed entry is not read as a list",
        HASH_JS,
        '"contentHash", "generated",',
        '"contentHash", ...EXTRA, "generated",',
    ),
]


def main() -> int:
    print("The real files")
    texts = real_texts()
    found = problems(texts)
    check("all six places name the same fields", not found, "; ".join(found))
    ref = js_set(texts[HASH_JS]) or set()
    check(
        "and they are the six #177 found (a list emptied everywhere would agree)",
        ref
        == {
            "updatedAt",
            "updatedBy",
            "cardUpdatedAt",
            "_state",
            "contentHash",
            "generated",
        },
        str(sorted(ref)),
    )

    print("Each place, broken (mutation)")
    for name, path, old, new in MUTATIONS:
        count = texts[path].count(old)
        if count != 1:
            check(
                f"{name}: the mutation applies",
                False,
                f"{old!r} occurs {count} times in {path}",
            )
            continue
        broken = dict(texts)
        broken[path] = texts[path].replace(old, new)
        caught = problems(broken)
        check(f"{name}: noticed", bool(caught), "the check passed a broken copy")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("fingerprint skip-list checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
