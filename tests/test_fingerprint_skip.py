#!/usr/bin/env python3
"""One list of what the fingerprint leaves out, written in six places (#177).

The record fingerprint is computed by three programs: the dashboard
(`CANON_SKIP` in app/js/00-core/12-hash.js), the server's version history
(`_HASH_SKIP` in server/app/routes.py) and the reader's check
(`CANON_SKIP` in examples/load_export.py). Each leaves the same volatile fields
out. If one list gains or loses a field, the same record hashes to two values,
which reads as evidence of a change that never happened. Two more places say
which fields they are, to a person: the `of` sentence every JSON export carries
(`FINGERPRINT_OF`, app/js/20-app/50-exports.js), and docs/exports.md. And the
dashboard's comment gives each field its reason. Three lists, two sentences and a
comment: six places.

This reads all six from the files, without running any of them, and fails if
any differs from the dashboard's list. A list is read where it is written, so it
must be the list the program uses: each program may only test membership in it
(`.has(key)` in JavaScript, `in` in Python), anywhere in the program, and any
other use (`.add`, `.delete`, a second assignment, `|=`, an alias, another module
setting it) fails, because a later change would make the program's list differ
from the one read here.

The two sentences must also state the rest of the rule a reader needs to
recompute a fingerprint: the record as stored, keys sorted by UTF-16 code unit
(not by code point), and a lone surrogate written as its \\u escape.

Then it breaks each place, adding a field, removing one, changing a list after it
is written and dropping a part of the rule, and demands the check notice.

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
# Every file of the dashboard (concatenated into one page, so any of them could
# change CANON_SKIP) and every module of the server.
JS_FILES = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "app" / "js").rglob("*.js"))
SERVER_FILES = sorted(
    str(p.relative_to(ROOT)) for p in (ROOT / "server" / "app").glob("*.py")
)

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


# --- the list a program uses is the one written ----------------------------------


def strip_js_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    return re.sub(r"(?m)(^|[^:\\])//[^\n]*", r"\1", code)


def js_uses(texts: dict[str, str]) -> list[str]:
    """CANON_SKIP is declared once, a Set of literals, and only ever asked .has()."""
    out, declared = [], 0
    for path in JS_FILES:
        code = strip_js_comments(texts[path])
        for m in re.finditer(r"\bCANON_SKIP\b", code):
            before, after = code[max(0, m.start() - 6) : m.start()], code[m.end() :]
            if before == "const " and re.match(r"\s*=\s*new Set\(\[", after):
                declared += 1
            elif not re.match(r"\s*\.\s*has\s*\(", after):
                line = code.count("\n", 0, m.start()) + 1
                out.append(f"{path}:{line}: CANON_SKIP is used other than by .has()")
    if declared != 1:
        out.append(f"CANON_SKIP is declared {declared} times in app/js, not once")
    return out


def py_uses(text: str, name: str, path: str) -> list[str]:
    """`name` is bound once, at module level, and only ever the right side of `in`."""
    tree = ast.parse(text)
    allowed: set[int] = set()
    binds = 0
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            allowed.add(id(node.targets[0]))
            binds += 1
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for op, right in zip(node.ops, node.comparators, strict=True):
                if isinstance(op, ast.In | ast.NotIn) and isinstance(right, ast.Name):
                    allowed.add(id(right))
    out = []
    for node in ast.walk(tree):
        where = f"{path}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Name) and node.id == name and id(node) not in allowed:
            out.append(f"{where}: {name} is used other than by `in`")
        elif isinstance(node, ast.Attribute) and node.attr == name:
            out.append(f"{where}: {name} is reached as an attribute")
        elif isinstance(node, ast.Global | ast.Nonlocal) and name in node.names:
            out.append(f"{where}: {name} is declared global")
        elif isinstance(node, ast.arg) and node.arg == name:
            out.append(f"{where}: {name} is a parameter")
        elif isinstance(node, ast.alias) and name in (node.name, node.asname):
            out.append(f"{where}: {name} is imported")
        elif (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            out.append(f"{where}: {name} is redefined")
    if binds != 1:
        out.append(
            f"{path}: {name} is assigned {binds} times at module level, not once"
        )
    return out


def used_as_written(texts: dict[str, str]) -> list[str]:
    out = js_uses(texts)
    out += py_uses(texts[ROUTES], "_HASH_SKIP", ROUTES)
    out += py_uses(texts[LOADER], "CANON_SKIP", LOADER)
    for path in SERVER_FILES:
        if path != ROUTES and re.search(r"\b_HASH_SKIP\b", texts[path]):
            out.append(f"{path}: _HASH_SKIP is used outside {ROUTES}")
    return out


# --- the rest of the rule, in the two sentences ------------------------------------

# Each sentence must say these, in these words: what is hashed, the order of the
# keys, and how a lone surrogate is written.
RULE = {
    "the record as stored": r"\bas stored\b",
    "keys sorted by UTF-16 code unit": (
        r"\bsorted at every level,? by UTF-16 code unit\b"
    ),
    # The sentence in the JavaScript source escapes its backslash.
    "a lone surrogate written as its \\u escape": (
        r"\blone surrogate\b[^.]*?\\{1,2}u`? escape"
    ),
}


def prose(path: str, text: str) -> str:
    if path == EXPORTS_JS:
        m = re.search(r'const FINGERPRINT_OF = "([^"]*)";', text)
        return m.group(1) if m else ""
    return re.sub(r"\s+", " ", text)


def rule_stated(texts: dict[str, str]) -> list[str]:
    out = []
    for where, path in (
        ("the export's FINGERPRINT_OF", EXPORTS_JS),
        ("docs/exports.md", DOCS),
    ):
        said = prose(path, texts[path])
        for part, pattern in RULE.items():
            if not re.search(pattern, said, re.S):
                out.append(f"{where} does not state {part}")
    return out


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
    return out + used_as_written(texts) + rule_stated(texts)


def real_texts() -> dict[str, str]:
    paths = {path for path, _ in READERS.values()} | set(JS_FILES) | set(SERVER_FILES)
    return {path: read(path) for path in paths}


# --- mutations: each place, broken both ways ---------------------------------------

# (place, path, what is replaced, its replacement), each replacing exactly one
# occurrence; None appends the replacement to the file. "add" puts in a field no
# other place has; "remove" takes one out.
MUTATIONS: list[tuple[str, str, str | None, str]] = [
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
    # A list changed after it is written: the program's list is not the one read.
    (
        "dashboard list: added to, in another file",
        "app/js/00-core/45-changelog.js",
        "if (CANON_SKIP.has(key)) continue;",
        'if (CANON_SKIP.has(key)) continue; CANON_SKIP.add("extraField");',
    ),
    (
        "dashboard list: deleted from, after it is written",
        HASH_JS,
        "function canonicalJSON(doc) {",
        'CANON_SKIP.delete("generated");\nfunction canonicalJSON(doc) {',
    ),
    (
        "dashboard list: an alias that could change it",
        "app/js/20-app/80-boot.js",
        None,
        "\nconst SKIP_TOO = CANON_SKIP;\n",
    ),
    (
        "server: assigned again",
        ROUTES,
        "def _canonical(value: Any, _depth: int = 0) -> Any:",
        '_HASH_SKIP = _HASH_SKIP | {"extraField"}\n\n\n'
        "def _canonical(value: Any, _depth: int = 0) -> Any:",
    ),
    (
        "server: set from another module",
        "server/app/main.py",
        None,
        "\nroutes._HASH_SKIP = frozenset()\n",
    ),
    (
        "load_export: added to, after it is written",
        LOADER,
        "def _canonical(value):",
        'CANON_SKIP.add("extraField")\n\n\ndef _canonical(value):',
    ),
    (
        "load_export: discarded from, inside a function",
        LOADER,
        '    data = json.loads(Path(path).read_text(encoding="utf-8"))',
        '    CANON_SKIP.discard("generated")\n'
        '    data = json.loads(Path(path).read_text(encoding="utf-8"))',
    ),
    ("load_export: |=", LOADER, None, '\nCANON_SKIP |= {"extraField"}\n'),
    # The rest of the rule, dropped from each sentence.
    (
        "export sentence: no ordering rule",
        EXPORTS_JS,
        "sorted at every level by UTF-16 code unit",
        "sorted at every level",
    ),
    (
        "export sentence: ordering by code point",
        EXPORTS_JS,
        "by UTF-16 code unit",
        "by code point",
    ),
    (
        "export sentence: no lone surrogate rule",
        EXPORTS_JS,
        " (a lone surrogate as its lowercase \\\\u escape)",
        "",
    ),
    (
        "export sentence: not the stored record",
        EXPORTS_JS,
        "project record as stored",
        "project record",
    ),
    (
        "docs: no ordering rule",
        DOCS,
        "keys sorted at every level,\nby UTF-16 code unit as JavaScript sorts them",
        "keys sorted at every level,\nas JavaScript sorts them",
    ),
    (
        "docs: no lone surrogate rule",
        DOCS,
        "is written as its lowercase `\\u` escape",
        "is written as itself",
    ),
    ("docs: not the stored record", DOCS, "The record is the one as stored.", ""),
]


def main() -> int:
    print("The real files")
    texts = real_texts()
    found = problems(texts)
    check(
        "all six places name the same fields, each list is the one its program uses,"
        " and both sentences state the whole rule",
        not found,
        "; ".join(found),
    )
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
        count = 1 if old is None else texts[path].count(old)
        if count != 1:
            check(
                f"{name}: the mutation applies",
                False,
                f"{old!r} occurs {count} times in {path}",
            )
            continue
        broken = dict(texts)
        broken[path] = (
            texts[path] + new if old is None else texts[path].replace(old, new)
        )
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
