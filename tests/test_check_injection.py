#!/usr/bin/env python3
"""scripts/check_injection.py notices what it says it notices.

A check that has never been seen to fail is a claim, not a control. Each rule is shown
failing on a planted example, and passing on the safe form next to it, and the real tree
is checked against its baseline.

    pixi run test-check-injection
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "check_injection", ROOT / "scripts" / "check_injection.py"
)
ci = importlib.util.module_from_spec(spec)
sys.modules["check_injection"] = ci
spec.loader.exec_module(ci)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def hard(js: str) -> list[str]:
    return ci.scan("x.js", js)[0]


def counts(js: str) -> dict:
    return dict(ci.scan("x.js", js)[1])


def main() -> int:
    print("Constructs that are never allowed")
    for label, js in [
        ("eval()", "const x = eval(s);"),
        ("new Function()", "const f = new Function('a', s);"),
        ("document.write()", "document.write(s);"),
        ("insertAdjacentHTML()", "el.insertAdjacentHTML('beforeend', s);"),
        ("an outerHTML assignment", "el.outerHTML = s;"),
        ("a srcdoc assignment", "frame.srcdoc = s;"),
        ("a javascript: URL", "const u = 'javascript:alert(1)';"),
        ("a string passed to a timer", "setTimeout('run()', 10);"),
        ("a handler written into markup", 'return `<b onclick="go()">x</b>`;'),
    ]:
        check(f"{label} is noticed", bool(hard(js)), js)
    check(
        "a handler assigned in code is not a handler written into markup",
        not hard("btn.onclick = () => go();"),
    )
    check(
        "a function passed to a timer is fine", not hard("setTimeout(() => go(), 10);")
    )
    check(
        "a comment that talks about eval() is not code",
        not hard("// never call eval(s)\n/* new Function() */ const x = 1;"),
    )
    check(
        "a block comment over several lines is not code",
        not hard("/*\n  eval(s) and document.write(s)\n*/\nconst x = 1;"),
    )
    check(
        "https:// inside a string does not start a comment that hides code",
        bool(hard("const u = 'https://x'; eval(s);")),
    )
    check(
        "xss-ok with a reason excuses one",
        not hard("frame.srcdoc = s;  // xss-ok: sandboxed without allow-scripts"),
    )
    check(
        "xss-ok with no reason excuses nothing",
        bool(hard("frame.srcdoc = s;  // xss-ok:")),
    )

    print("A URL made of interpolated text")
    check(
        "href with a value is noticed",
        bool(hard('return `<a href="${u}">x</a>`;')),
    )
    check(
        "src and action too",
        bool(hard('`<img src="${u}">`')) and bool(hard('`<form action="${u}">`')),
    )
    check(
        "a data- attribute whose name ends in 'action' is not a URL",
        not hard('`<button data-hold-action="${esc(a)}">`'),
    )
    check(
        "url-ok with a reason excuses one",
        not hard('`<a href="${esc(u)}">`  // url-ok: our own constant'),
    )
    check(
        "url-ok with no reason does not",
        bool(hard('`<a href="${esc(u)}">`  // url-ok:')),
    )

    print("The shape of the bug the payload test found")
    check(
        "a stored value interpolated into a class attribute is counted",
        counts('`<span class="tag ${st||"none"}">`') == {"attribute": 1},
    )
    check(
        "the same value through esc(), bdi(), t(), tHtml() or tf() is not",
        not counts(
            '`<i class="${esc(a)}" title="${t(k)}" alt="${tf(k, d)}" id="${bdi(x)}">`'
        ),
    )
    check(
        "a value in element text is not an attribute",
        not counts("`<b>${x}</b>`"),
    )
    check(
        "an assignment to innerHTML is counted",
        counts("host.innerHTML = s;") == {"innerHTML": 1},
    )
    check(
        "a comparison with innerHTML is not",
        not counts("if (el.innerHTML === s) go();"),
    )
    check(
        "xss-ok with a reason takes one out of the count",
        not counts('`<i class="${v}">`  // xss-ok: v is a status key from code'),
    )

    print("The baseline ratchet")
    growth, stale = ci.ratchet({"a.js": {"attribute": 3}}, {"a.js": {"attribute": 2}})
    check("a new one fails", bool(growth) and not stale)
    growth, stale = ci.ratchet({"a.js": {"attribute": 1}}, {"a.js": {"attribute": 2}})
    check("a fixed one makes the baseline stale", bool(stale) and not growth)
    growth, stale = ci.ratchet({"a.js": {"attribute": 2}}, {"a.js": {"attribute": 2}})
    check("an equal count passes", not growth and not stale)
    growth, _ = ci.ratchet({"new.js": {"innerHTML": 1}}, {})
    check("a new file is not exempt", bool(growth))

    print("The real tree")
    problems, found = ci.scan_tree(ci.JS)
    baseline = json.loads(ci.BASELINE.read_text())
    growth, stale = ci.ratchet(found, baseline)
    check("has no forbidden construct", not problems, "; ".join(problems[:3]))
    check("is within its baseline", not growth, "; ".join(growth[:3]))
    check("and the baseline is not stale", not stale, "; ".join(stale[:3]))
    check("and the check passes as the hook runs it", ci.main([]) == 0)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("check-injection tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
