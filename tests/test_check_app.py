#!/usr/bin/env python3
"""scripts/check_app.py notices what it says it notices (#176).

Its docstring once claimed it caught a declaration used before the module that
defines it, and a name no module defines, while the code checked only syntax and
duplicates. Since #168 a build of other frameworks leaves framework code out, so a
dangling reference would show only as a blank page. A check that has never been
seen to fail is a claim, not a control, so each rule is shown failing here:

* unit: synthetic scripts with an undefined name, a read in the temporal dead
  zone (directly, in an IIFE, in a for-of head, before an `await`, and through
  functions called during load), a duplicate, and the legitimate shapes next to
  them (a function body that runs later, code after an `await`, `typeof` of an
  optional name and the branch it guards, browser globals, shadowing,
  patterns), which must pass;
* integration: the published page and a build of the example framework pass;
  the browser globals the check accepts all exist in a real browser engine;
* mutation: a copy of app/ with a definition deleted, with the boot module sorted
  first, and with shared code reading a CHAI-only name, each rebuilt for real by a
  copy of scripts/build_app.py, must fail check-app naming the problem (module
  and line); the same CHAI-only call behind a typeof guard must pass.

Under REQUIRE_TESTS=1 (CI), a part that cannot run (no node, no browser) fails.

    pixi run test-check-app
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import check_app  # noqa: E402

REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))
CHECK = ROOT / "scripts" / "check_app.py"
EXAMPLE_CONFIG = Path("app") / "frameworks" / "example" / "build.json"

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def cannot_run(name: str, why: str) -> None:
    """A part with nothing to run it: a failure in CI, a visible skip elsewhere."""
    if REQUIRE_TESTS:
        check(name, False, f"{why} (REQUIRE_TESTS=1)")
    else:
        print(f"  SKIP  {name}  <- {why}")


def error_text(message: str) -> str:
    """An error's whole message on one line. Playwright's launch error is a
    header (`BrowserType.launch: `) with the reason on the lines below it, in a
    box drawn with these characters, so its first line alone says nothing."""
    parts = [line.strip().strip(BOX).strip() for line in message.splitlines()]
    return " ".join(p for p in parts if p) or "(the error had no message)"


BOX = "\u2554\u2557\u255a\u255d\u2550\u2551"


def problems(js: str) -> list[str]:
    return check_app.check_script(js)


def flags(js: str, *needles: str) -> bool:
    found = problems(js)
    return bool(found) and all(any(n in p for p in found) for n in needles)


def unit() -> None:
    print("Undefined names")
    check(
        "a name no module declares is reported, by name",
        flags("function f(){ return helpr(1); }", "undefined name 'helpr'"),
        problems("function f(){ return helpr(1); }"),
    )
    check(
        "a misspelled browser global is reported",
        flags("documnet.title;", "undefined name 'documnet'"),
    )
    check(
        "an undeclared name assigned to is reported (it would be an implicit global)",
        flags("function f(){ total = 1; }", "undefined name 'total'"),
    )
    check(
        "an undeclared name in a destructuring assignment is reported",
        flags("const o = {}; ({ a } = o);", "undefined name 'a'"),
    )
    check(
        "a name declared only inside another function is not visible here",
        flags("function f(){ const x = 1; } function g(){ return x; }", "'x'"),
    )
    check(
        "a top-level `arguments` (outside any function) is reported",
        flags("const f = () => arguments;", "undefined name 'arguments'"),
    )
    print("typeof guards: a name only some builds have")
    guarded = """
        function card(){
          if (typeof chaiCardMarkdown === "function") return chaiCardMarkdown(1);
          return "";
        }
        const STORE = null;
        if (STORE && typeof plugA === "function") { plugA(); }
        const r = typeof plugB === "function" ? plugB() : null;
        typeof plugC === "function" && plugC.go && plugC();
        if (typeof plugD !== "undefined") plugD.go();
    """
    check(
        "a name used only inside a branch guarded by its own typeof passes",
        problems(guarded) == [],
        problems(guarded),
    )
    parens = """
        const t = typeof (plugE);
        if (typeof (plugF) === "function") (plugF)();
    """
    check(
        "typeof with its operand in parentheses is a typeof too",
        problems(parens) == [],
        problems(parens),
    )
    check(
        "the same name called outside the guarded branch is still reported",
        flags(
            "function card(){\n"
            '  if (typeof chaiCardMarkdown === "function") chaiCardMarkdown(1);\n'
            "  return chaiCardMarkdown(2);\n"
            "}",
            "undefined name 'chaiCardMarkdown'",
            "(1 use)",
        ),
        problems(
            'if (typeof chaiCardMarkdown === "function") chaiCardMarkdown(1);\n'
            "chaiCardMarkdown(2);"
        ),
    )
    check(
        "a typeof guard of another name does not cover this one",
        flags('if (typeof other === "function") plug();', "undefined name 'plug'"),
    )
    check(
        "the else branch of a typeof guard is not covered",
        flags('typeof plug === "function" ? 0 : plug();', "undefined name 'plug'"),
    )
    check(
        '`typeof x === "undefined"` does not cover what follows it',
        flags('typeof plug === "undefined" && plug();', "undefined name 'plug'"),
    )
    check(
        "nothing wider: code after an early return, and a `||` form, are reported",
        flags(
            'function f(){ if (typeof plug !== "function") return; plug(); }\n'
            'function g(){ return typeof cb !== "function" || cb(); }',
            "undefined name 'plug'",
            "undefined name 'cb'",
        ),
    )
    check(
        "a typeof guard does not excuse a read in the temporal dead zone",
        flags(
            'if (typeof later === "number") later;\nconst later = 1;',
            "'later' is used before",
        ),
    )

    ok = """
        const f0 = 1, { a, b: [c, ...d], e = f0 } = window.cfg;
        function g(p, { q, r = p }, [s] = [], ...rest){
          return [p, q, r, s, rest, arguments];
        }
        const h = x => x + a + c + d + e;
        for (const [k, v] of Object.entries({})) { k; v; }
        for (var i = 0; i < 2; i++) {}
        i;
        try { g(1, {}); } catch (err) { console.log(err); }
        class K extends EventTarget {
          static n = 1; #p = 2; m(){ return K.n + this.#p; }
        }
        const E = class Inner { m(){ return Inner; } };
        if (h) { function annexB(){} }
        annexB();
        outer: for (;;) { break outer; }
        const has = typeof chaiOnly === "function";
        document.title = JSON.stringify(Math.max(1, Number("2")));
        setTimeout(() => fetch(new URL(location.href)), 0);
    """
    check(
        "declarations of every shape, typeof of an optional name, and globals pass",
        problems(ok) == [],
        problems(ok),
    )

    print("Use before declaration (the temporal dead zone)")
    check(
        "a top-level read of a const declared later is reported",
        flags("const a = later + 1;\nconst later = 2;", "'later' is used before"),
        problems("const a = later + 1;\nconst later = 2;"),
    )
    check(
        "a top-level `new` of a class declared later is reported",
        flags("const s = new Store();\nclass Store {}", "'Store' is used before"),
    )
    check(
        "a class extending one declared later is reported",
        flags("class A extends B {}\nclass B {}", "'B' is used before"),
    )
    check(
        "a read in an IIFE before the declaration is reported",
        flags("(() => later)();\nconst later = 1;", "'later' is used before"),
    )
    check(
        "a read in a static block runs when the class is defined: reported",
        flags("class A { static { later; } }\nlet later = 1;", "'later'"),
    )
    check(
        "a function called during load that reads a later const is reported",
        flags(
            "function boot(){ return render(); }\n"
            "function render(){ return CONFIG.x; }\n"
            "boot();\n"
            "const CONFIG = { x: 1 };",
            "'CONFIG' is used before",
            "via boot() -> render()",
        ),
    )
    check(
        "a constructor called during load that reads a later const is reported",
        flags("class A { x = LIMIT; }\nnew A();\nconst LIMIT = 1;", "'LIMIT'"),
    )
    check(
        "a read in a block before a let in that block is reported",
        flags("function f(){ { x; let x = 1; } }", "'x' is used before"),
    )
    check(
        "a default value reading a later name of the same declaration is reported",
        flags("const { e = f0 } = {}, f0 = 1;", "'f0' is used before"),
    )
    check(
        "a const read in its own initializer is reported",
        flags("const n = n + 1;", "'n' is used before"),
    )
    check(
        "a for-of reading its own binding on the right-hand side is reported",
        flags("const o = {};\nfor (const a of a) {}", "'a' is used before"),
        problems("const o = {};\nfor (const a of a) {}"),
    )
    check(
        "a for-in reading its own binding on the right-hand side is reported",
        flags("for (let k in k) {}", "'k' is used before"),
    )
    print("Async code: what runs after the first await runs after load")
    check(
        "a read after the first await of an async IIFE passes",
        problems("(async () => { await null; x; })();\nconst x = 1;") == [],
        problems("(async () => { await null; x; })();\nconst x = 1;"),
    )
    check(
        "a read before the first await of an async IIFE is reported",
        flags(
            "(async () => { x; await null; })();\nconst x = 1;", "'x' is used before"
        ),
    )
    check(
        "the operand of the first await is read before it suspends: reported",
        flags(
            "(async () => { await fetch(x); })();\nconst x = 1;", "'x' is used before"
        ),
    )
    check(
        "a read after the first await, of a let declared later in that same async "
        "function, is still reported",
        flags("(async () => { await null; y; let y = 1; })();", "'y' is used before"),
    )
    check(
        "an await in a nested function does not suspend the IIFE around it",
        flags(
            "(async () => { const g = async () => { await null; }; x; })();\n"
            "const x = 1;",
            "'x' is used before",
        ),
    )
    check(
        "an async function called during load: a read after its first await passes",
        problems(
            "async function boot(){ await null; return C + render(); }\n"
            "function render(){ return C; }\n"
            "boot();\n"
            "const C = 1;"
        )
        == [],
        problems(
            "async function boot(){ await null; return C + render(); }\n"
            "function render(){ return C; }\n"
            "boot();\n"
            "const C = 1;"
        ),
    )
    check(
        "an async function called during load: a read before its first await is "
        "reported",
        flags(
            "async function boot(){ render(); await null; }\n"
            "function render(){ return C; }\n"
            "boot();\n"
            "const C = 1;",
            "'C' is used before",
            "via boot() -> render()",
        ),
    )
    legit = """
        function render(){ return CONFIG.x + later(); }
        const handler = () => CONFIG.x;
        class View { draw(){ return CONFIG.x; } static make(){ return new View(); } }
        document.addEventListener("click", () => render());
        const CONFIG = { x: 1 };
        const later = () => 2;
        render();
        const v = new View();
    """
    check(
        "a function body that reads a later const, called only after it, passes",
        problems(legit) == [],
        problems(legit),
    )
    check(
        "a var read before its assignment is not a TDZ error (it is hoisted)",
        problems("x;\nvar x = 1;") == [],
    )
    check(
        "a function declaration called before it appears is hoisted, and passes",
        problems("f();\nfunction f(){ return 1; }") == [],
    )
    check(
        "a const declared before a function that is then called passes",
        problems("const C = 1;\nfunction f(){ return C; }\nf();") == [],
    )
    check(
        "a static field that names its own class passes (it is initialized first)",
        problems("class K { static a = 1; static b = K.a; }") == [],
    )

    print("Duplicates and syntax")
    check(
        "a name two modules declare at top level is reported",
        flags(
            "const esc = 1;\n\nfunction esc(){}",
            "duplicate top-level declaration 'esc'",
        ),
    )
    check(
        "a block function that overrides a top-level function is reported",
        flags(
            "function f(){}\n{ function f(){} }", "duplicate top-level declaration 'f'"
        ),
        problems("function f(){}\n{ function f(){} }"),
    )
    check(
        "the same name declared in two functions is not a duplicate",
        problems("function a(){ const x = 1; } function b(){ const x = 2; }") == [],
    )
    check("a syntax error is reported", flags("const a = ;", "syntax error"))

    print("A part that cannot run says why")
    launch = (
        "BrowserType.launch: \n"
        "Executable doesn't exist at /ms-playwright/chromium-1/chrome\n"
        "\u2554" + "\u2550" * 20 + "\u2557\n"
        "\u2551 Please run: playwright install \u2551\n"
        "\u255a" + "\u2550" * 20 + "\u255d\n"
    )
    shown = error_text(launch)
    check(
        "a Playwright launch error is reported with its reason, not just its header",
        "Executable doesn't exist at /ms-playwright" in shown
        and "playwright install" in shown
        and "\n" not in shown,
        shown,
    )

    print("node --check honors REQUIRE_TESTS")
    which, require = check_app.shutil.which, check_app.REQUIRE_TESTS
    try:
        check_app.shutil.which = lambda _name: None
        check_app.REQUIRE_TESTS = False
        local = check_app.node_check("const a = 1;")
        check_app.REQUIRE_TESTS = True
        ci = check_app.node_check("const a = 1;")
    finally:
        check_app.shutil.which, check_app.REQUIRE_TESTS = which, require
    check(
        "without node, the skip is said, and is not a failure outside CI",
        len(local) == 1 and local[0].startswith(check_app.SKIPPED),
        local,
    )
    check(
        "without node, under REQUIRE_TESTS=1, it is a failure",
        len(ci) == 1 and not ci[0].startswith(check_app.SKIPPED),
        ci,
    )
    if shutil.which("node"):
        early = check_app.node_check("let a = 1;\nlet a = 2;")
        check("node --check reports an early error", bool(early), early)
    else:
        cannot_run("node --check reports an early error", "node is not on PATH")


def integration() -> None:
    print("The real builds")
    out = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, cwd=ROOT
    )
    check(
        "check-app passes on the published page and the example build",
        out.returncode == 0
        and "docs/app/index.html" in out.stdout
        and "the build of example" in out.stdout,
        out.stdout + out.stderr,
    )
    if not shutil.which("node"):
        cannot_run("node --check ran on the real page", "node is not on PATH")

    print("Every global the check accepts exists in a real browser")
    try:
        from browser_engine import launch
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:
        cannot_run("the accepted globals exist in a browser", str(exc))
        return
    try:
        with sync_playwright() as pw:
            browser = launch(pw)
            page = browser.new_page()
            missing = page.evaluate(
                "names => names.filter(n => !(n in globalThis))",
                sorted(check_app.GLOBALS),
            )
            browser.close()
    except Error as exc:
        cannot_run("the accepted globals exist in a browser", error_text(str(exc)))
        return
    check(
        f"all {len(check_app.GLOBALS)} accepted globals exist in this engine",
        missing == [],
        missing,
    )


def copy_tree(tmp: Path) -> Path:
    """A copy of what a build reads (app/, scripts/), so the copy's build_app.py
    builds the copy's sources: its ROOT is where it is."""
    root = tmp / "repo"
    shutil.copytree(ROOT / "app", root / "app")
    (root / "proxy").mkdir()
    shutil.copytree(
        ROOT / "scripts", root / "scripts", ignore=shutil.ignore_patterns("__pycache__")
    )
    return root


def build_and_check(root: Path) -> dict[str, subprocess.CompletedProcess]:
    """Build the copy (the published config and the example), and check each."""
    results = {}
    builds = {
        "published": ([], root / "docs" / "app" / "index.html"),
        "example": (
            ["--config", str(root / EXAMPLE_CONFIG), "--out", str(root / "out")],
            root / "out" / "index.html",
        ),
    }
    for name, (args, page) in builds.items():
        built = subprocess.run(
            [sys.executable, str(root / "scripts" / "build_app.py"), *args],
            capture_output=True,
            text=True,
        )
        if built.returncode != 0:
            results[name] = built
            continue
        # The copy's own check, whose app/js is the copy's: a message then names
        # the module as the copy has it (a renamed file under its new name).
        results[name] = subprocess.run(
            [sys.executable, str(root / "scripts" / "check_app.py"), str(page)],
            capture_output=True,
            text=True,
        )
    return results


def mutation() -> None:
    print("Mutations of a copy of app/, rebuilt for real")
    with tempfile.TemporaryDirectory() as tmp:
        root = copy_tree(Path(tmp))
        util = root / "app" / "js" / "00-core" / "00-util.js"
        text = util.read_text(encoding="utf-8")
        line = re.search(r"^const bdi = .*\n", text, re.M)
        check("the definition to delete exists", line is not None)
        util.write_text(text.replace(line.group(0), ""), encoding="utf-8")
        for name, res in build_and_check(root).items():
            check(
                f"a deleted definition fails check-app, naming it ({name} build)",
                res.returncode == 1 and "undefined name 'bdi'" in res.stderr,
                res.stdout + res.stderr,
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = copy_tree(Path(tmp))
        js = root / "app" / "js"
        boot = js / "00-core" / "00-aa-boot.js"
        (js / "20-app" / "80-boot.js").rename(boot)
        # The first read that throws: the boot module's top-level use of
        # HeaderControl, which 02-i18n.js declares, now sorted after it.
        lines = boot.read_text(encoding="utf-8").splitlines()
        at = next(i for i, x in enumerate(lines, 1) if "HeaderControl." in x)
        expected = (
            f"app/js/00-core/00-aa-boot.js:{at}: 'HeaderControl' is used before its "
            "declaration runs (read directly); it is declared at "
            "app/js/00-core/02-i18n.js:"
        )
        for name, res in build_and_check(root).items():
            check(
                f"the boot module sorted first fails check-app ({name} build)",
                res.returncode == 1 and "is used before its declaration" in res.stderr,
                res.stdout + res.stderr,
            )
            check(
                f"... and names the module and line of the offending read ({name} "
                "build)",
                expected in res.stderr,
                f"wanted {expected!r} in: {res.stderr[:600]}",
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = copy_tree(Path(tmp))
        shell = root / "app" / "js" / "20-app" / "10-shell.js"
        shell.write_text(
            shell.read_text(encoding="utf-8") + "\nfunction cardExtras(){\n"
            '  if (typeof chaiCardMarkdown === "function")\n'
            "    return chaiCardMarkdown({});\n"
            '  return "";\n}\n',
            encoding="utf-8",
        )
        for name, res in build_and_check(root).items():
            check(
                f"shared code calling CHAI's code behind a typeof guard passes ({name} "
                "build)",
                res.returncode == 0,
                res.stdout + res.stderr,
            )

    with tempfile.TemporaryDirectory() as tmp:
        root = copy_tree(Path(tmp))
        chai = root / "app" / "js" / "10-frameworks" / "10-chai"
        names = re.findall(
            r"^function (\w+)",
            "\n".join(
                p.read_text(encoding="utf-8") for p in sorted(chai.rglob("*.js"))
            ),
            re.M,
        )
        check("there is a CHAI-only function to reach for", bool(names))
        shell = root / "app" / "js" / "20-app" / "10-shell.js"
        shell.write_text(
            shell.read_text(encoding="utf-8")
            + f"\nfunction reachIntoChai(){{ return {names[0]}(); }}\n",
            encoding="utf-8",
        )
        results = build_and_check(root)
        check(
            "shared code calling CHAI's code still passes in the build that has it",
            results["published"].returncode == 0,
            results["published"].stdout + results["published"].stderr,
        )
        check(
            "... and fails the example build, which leaves CHAI out, naming it",
            results["example"].returncode == 1
            and f"undefined name '{names[0]}'" in results["example"].stderr,
            results["example"].stdout + results["example"].stderr,
        )


def main() -> int:
    unit()
    integration()
    mutation()
    if failures:
        print(f"\n{len(failures)} failed: {failures}")
        return 1
    print("\nall check-app tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
