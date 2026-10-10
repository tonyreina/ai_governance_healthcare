#!/usr/bin/env python3
"""What the default build shows and exports, pinned (#168).

The frameworks-as-data port rewrites how every screen and export is produced. It
must not change what a person sees or what a file says, except where a change says
so. This renders, in a real browser with the clock and randomness frozen:

  * the portfolio, in English, the pseudo-locale and Hebrew (right to left);
  * every view of every sample project, with OPTICA off and then on, in English;
  * one project's views in the pseudo-locale and Hebrew, and read-only;
  * the side panel, and every export of every project: Markdown, the HTML report,
    the JSON (its volatile `generated` stamp removed) and the portfolio CSV;

and compares a SHA-256 of each piece with tests/fixtures/snapshot_default.json.
A difference lists the pieces that changed. When a change is intended, regenerate
with --update and say why in the change; `tests/snapshot_app.py` dumps the full
markup of two builds to diff by hand.

    pixi run test-snapshot             compare
    pixi run test-snapshot --update    rewrite the fixture (an intended change)
    pixi run test-snapshot --dump F    also write every piece's text to F
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
FIXTURE = ROOT / "tests" / "fixtures" / "snapshot_default.json"

FREEZE = """
(() => {
  const T = 1767225600000;                     // 2026-01-01T00:00:00Z
  const RealDate = Date;
  globalThis.Date = class extends RealDate {
    constructor(...a) { if (a.length) super(...a); else super(T); }
    static now() { return T; }
  };
  let seed = 42;
  Math.random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
})()
"""

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def wait_until(page, expr: str, timeout: float = 15.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate(f"() => !!({expr})"):
            return
        page.wait_for_timeout(50)
    raise TimeoutError(expr)


def settle(page) -> None:
    """Wait until the open project's history has stopped arriving: it loads, and
    a log write lands, asynchronously."""
    # Quiet means no save pending or in flight and the history unchanged for
    # 0.6 s: a slow runner lands a log write well after the change that caused it.
    last, same = None, 0
    while same < 15:
        now = page.evaluate(
            "JSON.stringify([Object.keys(pending).length,"
            " Object.values(flushing).some(Boolean), LOG.length, LOG.map(e => e.text)])"
        )
        same = same + 1 if now == last else 0
        last = now
        page.wait_for_timeout(40)


def views_of(page, pid: str, prefix: str, out: dict) -> None:
    page.evaluate(f"openProject({json.dumps(pid)}, 'setup')")
    settle(page)
    out[f"{prefix}/rail"] = page.inner_html("#rail")
    for vid in page.evaluate("activeViews().map(v => v.id)"):
        page.evaluate(f"go({json.dumps(vid)})")
        page.wait_for_timeout(15)
        out[f"{prefix}/view/{vid}"] = page.inner_html("#main")


def capture() -> tuple[dict[str, str], list[str]]:
    out: dict[str, str] = {}
    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # The clock is frozen to an instant; the zone and locale it is shown in are
        # pinned too, or a date renders differently on a machine in another zone.
        page = browser.new_page(
            viewport={"width": 1400, "height": 1000},
            timezone_id="America/New_York",
            locale="en-US",
        )
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on(
            "console",
            lambda m: (
                errors.append(f"console.error: {m.text}") if m.type == "error" else None
            ),
        )
        page.add_init_script(FREEZE)
        page.goto(APP.as_uri())
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED")
        page.evaluate("loadSamples()")
        wait_until(page, "PROJECTS && PROJECTS.size >= 10")
        page.wait_for_timeout(300)
        pids = page.evaluate(
            "[...PROJECTS.values()].map(p => [p.meta.solution, p.id]).sort()"
        )

        for loc in ("en", "en-XA", "he"):
            page.evaluate(f"setLocale({json.dumps(loc)}); relocalize(); goHome()")
            page.wait_for_timeout(80)
            out[f"{loc}/dashboard"] = page.inner_html("#main")
        page.evaluate("setLocale('en'); relocalize()")

        for name, pid in pids:
            key = f"en/{name}"
            views_of(page, pid, f"{key}/optica-off", out)
            out[f"{key}/panel"] = page.inner_html("#labelHost")
            out[f"{key}/export.md"] = page.evaluate("exportMD()")
            out[f"{key}/export.html"] = page.evaluate("exportHTML()")
            data = page.evaluate("projectJSON(S)")
            data.pop("generated", None)
            out[f"{key}/export.json"] = json.dumps(
                data, sort_keys=True, ensure_ascii=False
            )
            # Switching OPTICA writes a log entry, asynchronously; wait for it so
            # the report and history views are captured after it, every time.
            n = page.evaluate("LOG.length")
            page.evaluate("setFrameworkEnabled('optica', true)")
            wait_until(page, f"LOG.length > {n}")
            settle(page)
            views_of(page, pid, f"{key}/optica-on", out)
            n = page.evaluate("LOG.length")
            page.evaluate("setFrameworkEnabled('optica', false)")
            wait_until(page, f"LOG.length > {n}")
            settle(page)

        page.evaluate("goHome()")
        out["en/export.csv"] = page.evaluate("exportCSV()")

        name, pid = pids[0]
        for loc in ("en-XA", "he"):
            page.evaluate(f"setLocale({json.dumps(loc)}); relocalize()")
            views_of(page, pid, f"{loc}/{name}", out)
        page.evaluate("setLocale('en'); relocalize()")
        page.evaluate(f"openProject({json.dumps(pid)}, 'setup'); setReadOnly(true)")
        page.wait_for_timeout(60)
        views_of(page, pid, f"en/{name}/read-only", out)
        browser.close()
    return out, errors


def digest(pieces: dict[str, str]) -> dict[str, str]:
    return {
        k: hashlib.sha256(v.encode("utf-8")).hexdigest()
        for k, v in sorted(pieces.items())
    }


def main(argv: list[str]) -> int:
    update = "--update" in argv
    pieces, errors = capture()
    if "--dump" in argv:
        # Every piece's full text, to compare two builds by hand when the hashes
        # differ (an intended change must be shown to be what it says).
        out = Path(argv[argv.index("--dump") + 1])
        out.write_text(json.dumps(pieces, indent=1, sort_keys=True), encoding="utf-8")
        print(f"dumped {len(pieces)} pieces to {out}")
    print("The default build renders without errors")
    check("no page or console errors", not errors, "; ".join(errors[:3]))
    check(
        "it captured every sample, both OPTICA states, three languages",
        len(pieces) > 300,
        str(len(pieces)),
    )
    # Opening a project reloads it from the store, so capturing before a save lands
    # once recorded "OPTICA on" with no OPTICA views at all.
    check(
        "the OPTICA-on pass shows OPTICA's chapters",
        sum(bool(re.search(r"/optica-on/view/o\d+$", k)) for k in pieces) == 10 * 13,
        str(sum(bool(re.search(r"/optica-on/view/o\d+$", k)) for k in pieces)),
    )
    now = digest(pieces)
    if update:
        again = digest(capture()[0])
        check(
            "two captures agree (the snapshot is deterministic)",
            again == now,
            str([k for k in now if now[k] != again.get(k)][:5]),
        )
        if not failures:
            FIXTURE.write_text(
                json.dumps(now, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(f"wrote {FIXTURE.relative_to(ROOT)} ({len(now)} pieces)")
        return 1 if failures else 0

    print("It matches the pinned snapshot")
    was = json.loads(FIXTURE.read_text(encoding="utf-8")) if FIXTURE.exists() else {}
    changed = sorted(k for k in now if k in was and now[k] != was[k])
    added = sorted(set(now) - set(was))
    removed = sorted(set(was) - set(now))
    check("nothing changed", not changed, f"{len(changed)}: {changed[:12]}")
    check("nothing added", not added, f"{len(added)}: {added[:12]}")
    check("nothing removed", not removed, f"{len(removed)}: {removed[:12]}")
    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print(f"snapshot checks passed ({len(now)} pieces)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
