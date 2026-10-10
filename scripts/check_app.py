#!/usr/bin/env python3
"""Static checks on the built dashboard.

The dashboard is many modules under app/js concatenated, in filename order, into
one classic <script> (scripts/build_app.py). That invites failures that show
up in a browser only as a blank page, and since #168 a build of other frameworks
(--config) leaves framework directories out, so a reference into code that was not
built shows up the same way. This checks, for every page it is given:

1. Syntax. `node --check` on the script, when node is on PATH, and the parse
   below in any case. With no node, the check says it skipped `node --check`, and
   under REQUIRE_TESTS=1 (CI) that is a failure, because a skip exits 0 and reads
   as a pass (CLAUDE.md, "A skip is a failure").
2. Undefined names. Every identifier the script reads or writes is resolved
   through the scopes that enclose it. One that no scope declares and that is not
   an ECMAScript or browser global (GLOBALS below) is reported, unless it is
   asked about with `typeof`, the legitimate way to ask whether optional code was
   built: the operand of `typeof` itself (`typeof x`, `typeof (x)`), and a use
   inside the branch a typeof test of that same name guards, which is the
   consequent of an `if` or `?:`, or the right operand of `&&`, whose condition
   is (or has as an `&&` operand) `typeof x === "function"` or any other type,
   or `typeof x !== "undefined"`. Nothing wider: the else branch, code after
   `if (typeof x !== "function") return;`, and a `||` form are still reported.
   The resolution is exact, scope analysis on a real parse, not a pattern. What
   it cannot see: a name the app means to declare that is also a browser global
   (`open`, `close`, `print`, `origin`, `history`, `Image`, `Option`, ...) passes
   as that global if the declaration is missing, and a name a script adds at run
   time as a property of `window` is reported if read bare (and not checked if
   read as `window.x`).
3. Use before declaration. A `const`, `let` or `class` binding read before its
   declaration has run throws a ReferenceError (the temporal dead zone), and
   `typeof` does not protect it. Reported:
   * a read in the same execution context as the declaration (no function boundary
     between them, or only immediately run ones: an IIFE, a class static block, a
     static field) that comes earlier in the text, including the right-hand side
     of `for (const a of ...)`, which runs with `a` already in its dead zone.
     Exact: that code throws whenever it runs, which for top-level code is always,
     on load. One heuristic narrows it: code after the first `await` of an async
     function (an async IIFE, like the boot module's) runs after the script has
     finished loading, so a read there of a name declared outside that function
     is not reported. "First" is first in the text, so an `await` on a branch
     that is not taken, or in a loop that runs no times, hides a read that does
     run during load.
   * a read inside a function that top-level code calls, directly or through other
     functions, before the declaration. The call graph is followed only through
     calls of a plain name bound to a function (`f()`, `new K()`), and every path
     through a function is assumed to run, except what follows its first `await`
     (as above). So it misses a call made another way (a method call, a callback,
     an event handler) and could report a read on a branch that never runs during
     load. A read in a function body that is not called during load is,
     correctly, never reported: it runs after every module has loaded.
4. Duplicate top-level declarations: two modules defining one name, including a
   function declared in a top-level block (`{ function f(){} }`), which replaces
   a top-level function or var of that name when the block runs.

Parsing is tree-sitter's JavaScript grammar (tree-sitter and
tree-sitter-javascript, locked in pixi.lock), so it runs offline, without node,
and understands the syntax the app is written in. The scope analysis on top of it
is this file. What it does not model: `with` and direct `eval` (the app uses
neither, and check_injection forbids eval), and a `switch` that jumps past a
`let` in another case.

    pixi run check-app                  the published page, and a build of every
                                        app/frameworks/*/build.json into a temp dir
    python scripts/check_app.py PAGE..  just these built pages
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402

BUILT = ROOT / "docs" / "app" / "index.html"
JS_SRC = ROOT / "app" / "js"
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))
SKIPPED = "skipped:"

PARSER = Parser(Language(tree_sitter_javascript.language()))


class T(StrEnum):
    """The tree-sitter-javascript node types this analysis acts on (its grammar's
    names, so a protocol of tree-sitter's, kept as one closed set here)."""

    PROGRAM = "program"
    IDENTIFIER = "identifier"
    SHORTHAND_PROPERTY_IDENTIFIER = "shorthand_property_identifier"
    SHORTHAND_PROPERTY_IDENTIFIER_PATTERN = "shorthand_property_identifier_pattern"
    FUNCTION_DECLARATION = "function_declaration"
    GENERATOR_FUNCTION_DECLARATION = "generator_function_declaration"
    FUNCTION_EXPRESSION = "function_expression"
    GENERATOR_FUNCTION = "generator_function"
    ARROW_FUNCTION = "arrow_function"
    METHOD_DEFINITION = "method_definition"
    CLASS_DECLARATION = "class_declaration"
    CLASS = "class"
    CLASS_STATIC_BLOCK = "class_static_block"
    FIELD_DEFINITION = "field_definition"
    STATEMENT_BLOCK = "statement_block"
    FOR_STATEMENT = "for_statement"
    FOR_IN_STATEMENT = "for_in_statement"
    SWITCH_BODY = "switch_body"
    CATCH_CLAUSE = "catch_clause"
    VARIABLE_DECLARATION = "variable_declaration"
    LEXICAL_DECLARATION = "lexical_declaration"
    VARIABLE_DECLARATOR = "variable_declarator"
    FORMAL_PARAMETERS = "formal_parameters"
    OBJECT_PATTERN = "object_pattern"
    ARRAY_PATTERN = "array_pattern"
    ASSIGNMENT_PATTERN = "assignment_pattern"
    OBJECT_ASSIGNMENT_PATTERN = "object_assignment_pattern"
    REST_PATTERN = "rest_pattern"
    PAIR_PATTERN = "pair_pattern"
    UNARY_EXPRESSION = "unary_expression"
    CALL_EXPRESSION = "call_expression"
    NEW_EXPRESSION = "new_expression"
    PARENTHESIZED_EXPRESSION = "parenthesized_expression"
    IF_STATEMENT = "if_statement"
    TERNARY_EXPRESSION = "ternary_expression"
    BINARY_EXPRESSION = "binary_expression"
    STRING = "string"
    AWAIT_EXPRESSION = "await_expression"
    # Anonymous tokens: keywords that say which declaration or operator this is.
    TYPEOF = "typeof"
    CONST = "const"
    LET = "let"
    VAR = "var"
    STATIC = "static"
    ASYNC = "async"
    AWAIT = "await"
    AND = "&&"
    EQ = "=="
    STRICT_EQ = "==="
    NE = "!="
    STRICT_NE = "!=="


def kind(node: Node | None) -> T | None:
    """The node's type as a member, or None for a type this analysis ignores."""
    if node is None:
        return None
    return T._value2member_map_.get(node.type)


FUNCTIONS = frozenset(
    {
        T.FUNCTION_DECLARATION,
        T.GENERATOR_FUNCTION_DECLARATION,
        T.FUNCTION_EXPRESSION,
        T.GENERATOR_FUNCTION,
        T.ARROW_FUNCTION,
        T.METHOD_DEFINITION,
    }
)
FUNCTION_DECLARATIONS = frozenset(
    {T.FUNCTION_DECLARATION, T.GENERATOR_FUNCTION_DECLARATION}
)
FUNCTION_VALUES = frozenset(
    {T.FUNCTION_EXPRESSION, T.GENERATOR_FUNCTION, T.ARROW_FUNCTION}
)
CLASSES = frozenset({T.CLASS_DECLARATION, T.CLASS})
REFERENCES = frozenset(
    {
        T.IDENTIFIER,
        T.SHORTHAND_PROPERTY_IDENTIFIER,
        # In an assignment pattern, `({a} = o)`, this is a write to `a`.
        T.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN,
    }
)
BINDING_LEAVES = frozenset({T.IDENTIFIER, T.SHORTHAND_PROPERTY_IDENTIFIER_PATTERN})
EQUALS = frozenset({T.EQ, T.STRICT_EQ})
NOT_EQUALS = frozenset({T.NE, T.STRICT_NE})


class TypeofResult(StrEnum):
    """What `typeof` evaluates to, as far as a guard asks: is the name defined?"""

    UNDEFINED = "undefined"


class ScopeKind(StrEnum):
    PROGRAM = "program"
    FUNCTION = "function"
    BLOCK = "block"
    CLASS = "class"


class BindingKind(StrEnum):
    VAR = "var"
    LET = "let"
    CONST = "const"
    CLASS = "class"
    FUNCTION = "function"
    PARAM = "param"
    CATCH = "catch"
    IMPLICIT = "implicit"


# Bindings with a temporal dead zone: reading one before its declaration throws.
LEXICAL = frozenset({BindingKind.LET, BindingKind.CONST, BindingKind.CLASS})
DECLARATION_KIND = {T.CONST: BindingKind.CONST, T.LET: BindingKind.LET}


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# ECMAScript's own globals (ES2024), and the browser's that a page may use. A name
# here is never reported as undefined, so a name that is not really a global would
# hide a bug: tests/test_check_app.py asserts each exists in Chromium, Firefox, WebKit.
ES_GLOBALS = _words(
    """
    globalThis Infinity NaN undefined eval isFinite isNaN parseFloat parseInt
    decodeURI decodeURIComponent encodeURI encodeURIComponent escape unescape
    AggregateError Array ArrayBuffer Atomics BigInt BigInt64Array BigUint64Array
    Boolean DataView Date Error EvalError FinalizationRegistry Float32Array
    Float64Array Function Int8Array Int16Array Int32Array Intl JSON Map Math Number
    Object Promise Proxy RangeError ReferenceError Reflect RegExp Set
    String Symbol SyntaxError TypeError Uint8Array
    Uint8ClampedArray Uint16Array Uint32Array URIError WeakMap WeakRef WeakSet
    """
)
BROWSER_GLOBALS = _words(
    """
    window self document navigator location history screen console performance
    localStorage sessionStorage indexedDB crypto origin isSecureContext
    alert confirm prompt print open close focus blur postMessage queueMicrotask
    setTimeout clearTimeout setInterval clearInterval requestAnimationFrame
    cancelAnimationFrame structuredClone
    fetch atob btoa getComputedStyle matchMedia getSelection scrollTo scrollBy
    addEventListener removeEventListener dispatchEvent innerWidth innerHeight
    devicePixelRatio
    AbortController AbortSignal Blob BroadcastChannel CSS CompressionStream
    CustomEvent DOMException DOMParser DecompressionStream Document
    DocumentFragment Element Event EventSource EventTarget File FileList
    FileReader FormData Headers HTMLElement HTMLInputElement HTMLSelectElement
    HTMLTextAreaElement HTMLAnchorElement HTMLButtonElement HTMLDialogElement
    HTMLTemplateElement Image IntersectionObserver KeyboardEvent MessageChannel
    MouseEvent MutationObserver Node NodeFilter Option PointerEvent Range Request
    ResizeObserver Response Selection Storage StorageEvent Text
    TextDecoder TextEncoder TreeWalker URL URLSearchParams WebSocket Worker
    XMLHttpRequest XMLSerializer
    """
)
GLOBALS = ES_GLOBALS | BROWSER_GLOBALS


@dataclass(eq=False)
class Scope:
    kind: ScopeKind
    parent: Scope | None
    node: Node
    names: dict[str, Binding] = field(default_factory=dict)
    # Run as soon as it is defined (an IIFE, a static block or field): its code runs
    # in the execution context of whatever encloses it.
    immediate: bool = False

    @property
    def function(self) -> Scope:
        """The nearest function or program scope: where `var` goes."""
        s = self
        while s.kind not in (ScopeKind.FUNCTION, ScopeKind.PROGRAM):
            s = s.parent
        return s

    @property
    def context(self) -> Scope:
        """The execution context: the nearest function that is not run immediately."""
        s = self.function
        while s.immediate:
            s = s.parent.function
        return s


@dataclass(eq=False)
class Binding:
    name: str
    kind: BindingKind
    scope: Scope
    node: Node
    # The byte offset from which reading it is safe: the end of its declaration for
    # let, const and class; -1 (always) for the hoisted kinds.
    ready: int
    # The function it is bound to, when it is one: followed by the call graph.
    value: Node | None = None
    # A function declared in a block that Annex B also binds in the enclosing
    # function (or the program): `{ function f(){} }`.
    annex_b: bool = False


@dataclass(eq=False)
class Reference:
    node: Node
    scope: Scope
    binding: Binding | None
    in_typeof: bool

    @property
    def name(self) -> str:
        return self.node.text.decode("utf-8")


@dataclass(frozen=True)
class Problem:
    """What is wrong, and where: `offset` and each of `related` are byte offsets
    in the script, shown as module:line; the message names `related` as {0}, {1}."""

    message: str
    offset: int
    related: tuple[int, ...] = ()


class Analysis:
    """Scopes, bindings and references of one script."""

    def __init__(self, source: str):
        self.source = source.encode("utf-8")
        self.tree = PARSER.parse(self.source)
        self.root = self.tree.root_node
        self.program = Scope(ScopeKind.PROGRAM, None, self.root)
        self.scopes: dict[int, Scope] = {self.root.id: self.program}
        self.binding_nodes: set[int] = set()
        self.duplicates: list[tuple[Binding, Binding]] = []
        self.references: list[Reference] = []
        self._awaits: dict[int, int | None] = {}
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 20000))
        try:
            self._declare_children(self.root, self.program)
            self._resolve(self.root, self.program)
        finally:
            sys.setrecursionlimit(limit)

    # -- pass 1: scopes and declarations ---------------------------------------

    def _bind(
        self,
        name_node: Node,
        bkind: BindingKind,
        scope: Scope,
        ready: int = -1,
        value: Node | None = None,
        quiet: bool = False,
    ) -> None:
        self.binding_nodes.add(name_node.id)
        name = name_node.text.decode("utf-8")
        binding = Binding(name, bkind, scope, name_node, ready, value, annex_b=quiet)
        old = scope.names.get(name)
        if old is not None:
            # A block function at top level overwrites a top-level function or var
            # of the same name when its block runs (Annex B): a duplicate too. Two
            # block functions of one name are left alone (only one block may run).
            overrides = old.kind in (BindingKind.FUNCTION, BindingKind.VAR)
            if scope is self.program and (not quiet or (overrides and not old.annex_b)):
                self.duplicates.append((old, binding))
            if bkind is BindingKind.VAR or quiet:
                return  # `var x` again, or Annex B: the first binding stands
        scope.names[name] = binding

    def _bind_pattern(
        self, node: Node, bkind: BindingKind, scope: Scope, ready: int = -1
    ) -> None:
        """Bind every name a pattern declares. Default values are expressions,
        resolved in pass 2; keys of `{key: name}` are not bindings."""
        k = kind(node)
        if k in BINDING_LEAVES:
            self._bind(node, bkind, scope, ready)
        elif k in (T.ASSIGNMENT_PATTERN, T.OBJECT_ASSIGNMENT_PATTERN):
            self._bind_pattern(node.child_by_field_name("left"), bkind, scope, ready)
        elif k is T.PAIR_PATTERN:
            self._bind_pattern(node.child_by_field_name("value"), bkind, scope, ready)
        elif k in (
            T.OBJECT_PATTERN,
            T.ARRAY_PATTERN,
            T.REST_PATTERN,
            T.FORMAL_PARAMETERS,
        ):
            for child in node.named_children:
                self._bind_pattern(child, bkind, scope, ready)
        # Anything else in a pattern position (a member expression in a for-in
        # head that assigns) declares nothing.

    def _scope(self, node: Node, skind: ScopeKind, parent: Scope, **kw) -> Scope:
        scope = Scope(skind, parent, node, **kw)
        self.scopes[node.id] = scope
        return scope

    def _declare_children(self, node: Node, scope: Scope) -> None:
        for child in node.children:
            self._declare(child, scope)

    def _declare(self, node: Node, scope: Scope) -> None:
        k = kind(node)
        if k in FUNCTIONS:
            self._declare_function(node, scope, k)
        elif k in CLASSES:
            self._declare_class(node, scope, k)
        elif k is T.CLASS_STATIC_BLOCK:
            inner = self._scope(node, ScopeKind.FUNCTION, scope, immediate=True)
            body = node.child_by_field_name("body")
            self.scopes[body.id] = inner
            self._declare_children(body, inner)
        elif k is T.FIELD_DEFINITION:
            # A field's initializer runs like a method body: at construction, or,
            # for a static field, when the class is defined.
            static = any(kind(c) is T.STATIC for c in node.children)
            for child in node.children:
                if child == node.child_by_field_name("value"):
                    inner = self._scope(
                        child, ScopeKind.FUNCTION, scope, immediate=static
                    )
                    self._declare(child, inner)
                else:
                    self._declare(child, scope)
        elif k in (T.STATEMENT_BLOCK, T.FOR_STATEMENT, T.SWITCH_BODY):
            if node.id in self.scopes:  # a function's body: already its scope
                self._declare_children(node, self.scopes[node.id])
            else:
                self._declare_children(node, self._scope(node, ScopeKind.BLOCK, scope))
        elif k is T.FOR_IN_STATEMENT:
            inner = self._scope(node, ScopeKind.BLOCK, scope)
            decl = kind(node.child_by_field_name("kind"))
            left = node.child_by_field_name("left")
            if decl is T.VAR:
                self._bind_pattern(left, BindingKind.VAR, scope.function)
            elif decl in DECLARATION_KIND:
                # The right-hand side is evaluated with these bindings already in
                # scope and not yet initialized: `for (const a of a)` throws.
                right = node.child_by_field_name("right")
                self._bind_pattern(left, DECLARATION_KIND[decl], inner, right.end_byte)
            self._declare_children(node, inner)
        elif k is T.CATCH_CLAUSE:
            inner = self._scope(node, ScopeKind.BLOCK, scope)
            param = node.child_by_field_name("parameter")
            if param is not None:
                self._bind_pattern(param, BindingKind.CATCH, inner)
            body = node.child_by_field_name("body")
            self.scopes[body.id] = inner
            self._declare_children(node, inner)
        elif k is T.VARIABLE_DECLARATION:
            for decl in node.named_children:
                if kind(decl) is T.VARIABLE_DECLARATOR:
                    self._declare_declarator(decl, BindingKind.VAR, scope.function)
            self._declare_children(node, scope)
        elif k is T.LEXICAL_DECLARATION:
            bkind = DECLARATION_KIND[kind(node.child_by_field_name("kind"))]
            for decl in node.named_children:
                if kind(decl) is T.VARIABLE_DECLARATOR:
                    self._declare_declarator(decl, bkind, scope)
            self._declare_children(node, scope)
        else:
            self._declare_children(node, scope)

    def _declare_declarator(self, decl: Node, bkind: BindingKind, scope: Scope) -> None:
        name = decl.child_by_field_name("name")
        value = decl.child_by_field_name("value")
        ready = decl.end_byte if bkind in LEXICAL else -1
        if kind(name) is T.IDENTIFIER:
            fn = value if kind(value) in FUNCTION_VALUES | CLASSES else None
            self._bind(name, bkind, scope, ready, fn)
        else:
            self._bind_pattern(name, bkind, scope, ready)

    def _declare_function(self, node: Node, scope: Scope, k: T) -> None:
        name = node.child_by_field_name("name")
        inner = self._scope(node, ScopeKind.FUNCTION, scope, immediate=_iife(node))
        if k in FUNCTION_DECLARATIONS:
            self._bind(name, BindingKind.FUNCTION, scope, value=node)
            if scope.kind is not ScopeKind.PROGRAM and scope is not scope.function:
                # Annex B: in a script, a function declared in a block is also a
                # var of the enclosing function.
                self._bind(
                    name, BindingKind.FUNCTION, scope.function, value=node, quiet=True
                )
        elif name is not None and k is not T.METHOD_DEFINITION:
            self._bind(name, BindingKind.FUNCTION, inner, value=node)
        if k is not T.ARROW_FUNCTION:
            inner.names["arguments"] = Binding(
                "arguments", BindingKind.IMPLICIT, inner, node, -1
            )
        params = node.child_by_field_name("parameters") or node.child_by_field_name(
            "parameter"
        )
        if params is not None:
            self._bind_pattern(params, BindingKind.PARAM, inner)
        body = node.child_by_field_name("body")
        if body is not None and kind(body) is T.STATEMENT_BLOCK:
            self.scopes[body.id] = inner
        for child in node.children:
            if child != name or k is T.METHOD_DEFINITION:
                self._declare(child, inner)

    def _declare_class(self, node: Node, scope: Scope, k: T) -> None:
        name = node.child_by_field_name("name")
        if k is T.CLASS_DECLARATION:
            self._bind(name, BindingKind.CLASS, scope, node.end_byte, node)
        inner = self._scope(node, ScopeKind.CLASS, scope)
        if name is not None:
            # The name inside the class body is its own binding, ready once defined.
            # It is initialized before the static fields and blocks run, so
            # it is ready from the start of the body.
            text = name.text.decode("utf-8")
            body = node.child_by_field_name("body")
            inner.names[text] = Binding(
                text, BindingKind.CLASS, inner, name, body.start_byte, node
            )
            self.binding_nodes.add(name.id)
        for child in node.children:
            if child != name:
                self._declare(child, inner)

    # -- pass 2: references --------------------------------------------------

    def _resolve(self, node: Node, scope: Scope) -> None:
        scope = self.scopes.get(node.id, scope)
        if kind(node) in REFERENCES and node.id not in self.binding_nodes:
            self.references.append(
                Reference(
                    node,
                    scope,
                    lookup(scope, node.text.decode("utf-8")),
                    _in_typeof(node),
                )
            )
        for child in node.children:
            self._resolve(child, scope)

    # -- the checks -----------------------------------------------------------

    def syntax_errors(self) -> list[Problem]:
        found = []

        def walk(n: Node) -> None:
            if n.is_error or n.is_missing:
                what = "missing " + n.type if n.is_missing else "unexpected text"
                found.append(Problem(f"syntax error: {what}", n.start_byte))
                return
            if n.has_error:
                for c in n.children:
                    walk(c)

        walk(self.root)
        return found

    def undefined_names(self) -> list[Problem]:
        seen: dict[str, list[Reference]] = {}
        for ref in self.references:
            if (
                ref.binding is None
                and not ref.in_typeof
                and ref.name not in GLOBALS
                and not _guarded(ref.node, ref.name)
            ):
                seen.setdefault(ref.name, []).append(ref)
        return [
            Problem(
                f"undefined name {name!r}: no module declares it, and it is not a "
                f"JavaScript or browser global ({len(refs)} use"
                f"{'' if len(refs) == 1 else 's'})",
                refs[0].node.start_byte,
            )
            for name, refs in seen.items()
        ]

    def used_before_declaration(self) -> list[Problem]:
        problems = []
        reported: set[tuple[int, int]] = set()

        def report(ref: Reference, how: str, related: tuple[int, ...] = ()) -> None:
            key = (ref.node.id, ref.binding.node.id)
            if key in reported:
                return
            reported.add(key)
            problems.append(
                Problem(
                    f"{ref.name!r} is used before its declaration runs ({how}); "
                    "it is declared at {0}",
                    ref.node.start_byte,
                    (ref.binding.node.start_byte, *related),
                )
            )

        # Exact: a read earlier in the same execution context.
        for ref in self.references:
            b = ref.binding
            if (
                b is not None
                and b.kind in LEXICAL
                and ref.node.start_byte < b.ready
                and ref.scope.context is b.scope.context
                and not self._after_await(ref, b.scope.function)
            ):
                report(ref, "read directly")

        # Through the call graph: what top-level code calls before a declaration.
        by_context: dict[int, list[Reference]] = {}
        for ref in self.references:
            by_context.setdefault(ref.scope.context.node.id, []).append(ref)
        for ref in by_context.get(self.root.id, []):
            target = _called(ref)
            if target is None or self._after_await(ref):
                continue
            at = ref.node.start_byte
            chain = [ref.name]
            for fn, path in self._reachable(target, by_context, chain):
                for inner in by_context.get(fn.id, []):
                    b = inner.binding
                    if (
                        b is not None
                        and b.scope is self.program
                        and b.kind in LEXICAL
                        and at < b.ready
                        and not self._after_await(inner)
                    ):
                        report(
                            inner,
                            "called during load at {1} via "
                            + " -> ".join(f"{p}()" for p in path),
                            (at,),
                        )
        return problems

    def _reachable(
        self, start: Binding, by_context: dict[int, list[Reference]], chain: list[str]
    ) -> Iterator[tuple[Node, list[str]]]:
        """Every function body run by calling `start`, with the call chain to it."""
        seen: set[int] = set()
        todo = [(start, chain)]
        while todo:
            binding, path = todo.pop()
            for body in _bodies(binding):
                if body.id in seen:
                    continue
                seen.add(body.id)
                yield body, path
                for ref in by_context.get(body.id, []):
                    nxt = _called(ref)
                    if nxt is not None and not self._after_await(ref):
                        todo.append((nxt, [*path, ref.name]))

    def _await_end(self, fn: Node) -> int | None:
        """Where an async function's code first suspends: the end of its first
        `await` (its operand is evaluated before it suspends), or None."""
        if fn.id not in self._awaits:
            async_ = kind(fn) in FUNCTIONS and any(
                kind(c) is T.ASYNC for c in fn.children
            )
            body = fn.child_by_field_name("body") if async_ else None
            self._awaits[fn.id] = None if body is None else _first_await(body)
        return self._awaits[fn.id]

    def _after_await(self, ref: Reference, outer: Scope | None = None) -> bool:
        """Whether a reference runs only after an async function it is in has
        suspended, so after the rest of the script has loaded. Walks out from
        the reference through functions run immediately, to its execution
        context, stopping at `outer` (the function whose own code declares the
        name, where suspending does not help: its declaration has not run)."""
        at = ref.node.start_byte
        s = ref.scope.function
        while s is not outer:
            end = self._await_end(s.node)
            if end is not None and at >= end:
                return True
            if not s.immediate:
                return False
            s = s.parent.function
        return False

    def duplicate_declarations(self) -> list[Problem]:
        return [
            Problem(
                f"duplicate top-level declaration {new.name!r} (first at {{0}}) "
                "- two modules define it",
                new.node.start_byte,
                (old.node.start_byte,),
            )
            for old, new in self.duplicates
        ]


def lookup(scope: Scope | None, name: str) -> Binding | None:
    while scope is not None:
        if name in scope.names:
            return scope.names[name]
        scope = scope.parent
    return None


def _in_typeof(node: Node) -> bool:
    """The operand of `typeof`, `typeof x` or `typeof (x)`."""
    parent = _unparen(node).parent
    return (
        kind(parent) is T.UNARY_EXPRESSION
        and kind(parent.child_by_field_name("operator")) is T.TYPEOF
    )


def _unparen(node: Node) -> Node:
    """Out through enclosing parentheses: `x` in `((x))` to the outermost."""
    while kind(node.parent) is T.PARENTHESIZED_EXPRESSION:
        node = node.parent
    return node


def _inner(node: Node | None) -> Node | None:
    """In through parentheses: `((x))` to `x`."""
    while kind(node) is T.PARENTHESIZED_EXPRESSION and node.named_child_count == 1:
        node = node.named_children[0]
    return node


def _typeof_of(node: Node | None) -> str | None:
    """The name `typeof name` asks about, or None if this is not one."""
    node = _inner(node)
    if not (
        kind(node) is T.UNARY_EXPRESSION
        and kind(node.child_by_field_name("operator")) is T.TYPEOF
    ):
        return None
    arg = _inner(node.child_by_field_name("argument"))
    return arg.text.decode("utf-8") if kind(arg) is T.IDENTIFIER else None


def _says_defined(cond: Node | None, name: str) -> bool:
    """Whether `cond` being true means `name` is defined: it is, or has as an
    `&&` operand, `typeof name === "<anything but undefined>"` or
    `typeof name !== "undefined"` (either way round, `==` and `!=` too)."""
    cond = _inner(cond)
    if kind(cond) is not T.BINARY_EXPRESSION:
        return False
    op = kind(cond.child_by_field_name("operator"))
    left, right = cond.child_by_field_name("left"), cond.child_by_field_name("right")
    if op is T.AND:
        return _says_defined(left, name) or _says_defined(right, name)
    if op not in EQUALS | NOT_EQUALS:
        return False
    for asked, other in ((left, right), (right, left)):
        other = _inner(other)
        if _typeof_of(asked) == name and kind(other) is T.STRING:
            undefined = other.text[1:-1].decode("utf-8") == TypeofResult.UNDEFINED
            return (op in EQUALS) is not undefined
    return False


def _guarded(node: Node, name: str) -> bool:
    """Whether `node` sits in the branch a typeof test of `name` guards: the
    consequent of an `if` or `?:` whose condition says it is defined, or the
    right operand of an `&&` whose left does. Not the else branch, and not code
    after an early return: that is all."""
    child, parent = node, node.parent
    while parent is not None:
        k = kind(parent)
        if k in (T.IF_STATEMENT, T.TERNARY_EXPRESSION):
            if parent.child_by_field_name("consequence") == child and _says_defined(
                parent.child_by_field_name("condition"), name
            ):
                return True
        elif (
            k is T.BINARY_EXPRESSION
            and kind(parent.child_by_field_name("operator")) is T.AND
            and parent.child_by_field_name("right") == child
            and _says_defined(parent.child_by_field_name("left"), name)
        ):
            return True
        child, parent = parent, parent.parent
    return False


def _first_await(node: Node) -> int | None:
    """The end of the first `await` in this code, not counting nested functions
    (they suspend themselves, not this one). `for await` suspends once its
    right-hand side is evaluated."""
    todo = [node]
    while todo:
        n = todo.pop()
        k = kind(n)
        if k is T.AWAIT_EXPRESSION:
            return n.end_byte
        if k in FUNCTIONS:
            continue
        if k is T.FOR_IN_STATEMENT and any(kind(c) is T.AWAIT for c in n.children):
            right = n.child_by_field_name("right")
            inner = _first_await(right)
            return right.end_byte if inner is None else inner
        todo.extend(reversed(n.children))
    return None


def _iife(fn: Node) -> bool:
    """A function expression called where it is written: `(() => ...)()`."""
    outer = _unparen(fn)
    parent = outer.parent
    return (
        kind(fn) in FUNCTION_VALUES
        and kind(parent) is T.CALL_EXPRESSION
        and parent.child_by_field_name("function") == outer
    )


def _called(ref: Reference) -> Binding | None:
    """The binding a reference calls, `f()` or `new F()`, when it is a function."""
    node = _unparen(ref.node)
    parent = node.parent
    k = kind(parent)
    callee = (
        parent.child_by_field_name("function")
        if k is T.CALL_EXPRESSION
        else parent.child_by_field_name("constructor")
        if k is T.NEW_EXPRESSION
        else None
    )
    if callee != node or ref.binding is None or ref.binding.value is None:
        return None
    return ref.binding


def _bodies(binding: Binding) -> Iterator[Node]:
    """The function nodes that run when a binding is called: the function itself,
    or for a class its constructor and instance field initializers."""
    value = binding.value
    if kind(value) in FUNCTIONS:
        yield value
        return
    if kind(value) in CLASSES:
        body = value.child_by_field_name("body")
        for member in body.named_children:
            mk = kind(member)
            if mk is T.METHOD_DEFINITION:
                name = member.child_by_field_name("name")
                if name is not None and name.text == b"constructor":
                    yield member
            elif mk is T.FIELD_DEFINITION:
                v = member.child_by_field_name("value")
                if v is not None and not any(
                    kind(c) is T.STATIC for c in member.children
                ):
                    yield v


# -- a built page ---------------------------------------------------------------


class Modules:
    """Which module of app/js a byte of the bundle came from, for messages that
    name a file and line rather than a line of a 5,000-line script."""

    def __init__(self, source: bytes, js_src: Path = JS_SRC):
        self.source = source
        self.spans: list[tuple[int, int, str]] = []
        root = js_src.parent.parent
        for path in build_app.ordered(js_src, ".js"):
            text = path.read_text(encoding="utf-8").strip("\n").encode("utf-8")
            at = source.find(text)
            if text and at >= 0:
                rel = path.relative_to(root) if path.is_relative_to(root) else path
                self.spans.append((at, at + len(text), str(rel)))

    def where(self, offset: int) -> str:
        for start, end, rel in self.spans:
            if start <= offset < end:
                return f"{rel}:{self.source.count(NL, start, offset) + 1}"
        # The build's own generated part (catalogs, definitions), or a test's script.
        return f"script line {self.source.count(NL, 0, offset) + 1}"


NL = b"\n"


def node_check(js: str) -> list[str]:
    """`node --check`: the engine's own parser, including its early errors."""
    node = shutil.which("node")
    if not node:
        if REQUIRE_TESTS:
            return [
                "node is not available, so `node --check` could not run "
                "(REQUIRE_TESTS=1 makes that a failure)"
            ]
        return [f"{SKIPPED} node not available, `node --check` not run"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "app.js"
        path.write_text(js, encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(path)], capture_output=True, text=True
        )
    return [result.stderr.strip()] if result.returncode != 0 else []


def check_script(js: str, js_src: Path = JS_SRC) -> list[str]:
    """Every problem in one bundle's script, each naming its module and line."""
    analysis = Analysis(js)
    modules = Modules(analysis.source, js_src)
    problems = (
        analysis.syntax_errors()
        + analysis.undefined_names()
        + analysis.used_before_declaration()
        + analysis.duplicate_declarations()
    )
    return [
        f"{modules.where(p.offset)}: "
        + p.message.format(*(modules.where(r) for r in p.related))
        for p in sorted(problems, key=lambda p: p.offset)
    ]


def check_page(page: Path, js_src: Path = JS_SRC) -> list[str]:
    html = page.read_text(encoding="utf-8")
    js = build_app.inline_script(html)
    return node_check(js) + check_script(js, js_src)


def custom_builds() -> list[Path]:
    return sorted((ROOT / "app" / "frameworks").glob("*/build.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("pages", nargs="*", type=Path, help="built pages to check")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        pages = list(args.pages)
        if not pages:
            if not BUILT.exists():
                print(
                    f"error: {BUILT} missing - run `pixi run build-app`",
                    file=sys.stderr,
                )
                return 1
            pages.append(BUILT)
            # A build of other frameworks leaves framework code out (#168): check
            # that what is left still defines everything it uses.
            for config in custom_builds():
                out = Path(tmp) / config.parent.name
                with open(os.devnull, "w") as quiet:
                    old, sys.stdout = sys.stdout, quiet
                    try:
                        code = build_app.main(
                            ["--config", str(config), "--out", str(out)]
                        )
                    finally:
                        sys.stdout = old
                if code != 0:
                    print(f"error: the build of {config} failed", file=sys.stderr)
                    return 1
                pages.append(out / "index.html")

        failed = False
        for page in pages:
            shown = (
                page.relative_to(ROOT) if page.resolve().is_relative_to(ROOT) else page
            )
            if not page.exists():
                print(f"error: {shown} does not exist", file=sys.stderr)
                failed = True
                continue
            problems = check_page(page)
            hard = [p for p in problems if not p.startswith(SKIPPED)]
            for p in problems:
                print(f"{shown}: {p}", file=sys.stderr)
            failed = failed or bool(hard)
            if not hard:
                label = "the build of " + page.parent.name if page != BUILT else shown
                print(f"app checks passed: {label}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
