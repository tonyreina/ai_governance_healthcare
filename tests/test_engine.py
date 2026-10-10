#!/usr/bin/env python3
"""The framework engine's rules, on definitions CHAI and OPTICA never exercise (#168).

The snapshot (test-snapshot) shows CHAI and OPTICA behave exactly as before on the
engine. This shows the engine's own semantics on small stand-in definitions, in the
real page: the review clock's fallback, a plain checklist with no lifecycle, how each
status class scores, that a value the definition does not know counts as nothing,
and that flags keep the definition's order with red first.

    pixi run test-engine
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

APP = Path(__file__).resolve().parent.parent / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# Two sections, two gates (G1 after a, R the recurring review after b), phases with
# roles, a declined status, and a plug-in flag between two engine rules.
DEF = """{
  schemaVersion: 1, id: "zz", name: "ZZ", role: "primary",
  statuses: [{value: "y", class: "done"}, {value: "h", class: "partial"},
             {value: "n", class: "open"}, {value: "d", class: "declined"},
             {value: "x", class: "excluded"}],
  categories: [{id: "K", name: "Keep"}],
  sections: [{id: "a", n: 1, title: "A", items: [
                {id: "a1", category: "K", text: "one"},
                {id: "a2", category: "K", text: "two"}]},
             {id: "b", n: 2, title: "B", items: [
                {id: "b1", category: "K", text: "three"}]}],
  gates: [{id: "G1", after: "a", title: "Gate one", options: [
             {value: "Go", class: "go"}, {value: "Halt", class: "stop"}]},
          {id: "R", after: "b", title: "Review", options: [
             {value: "Keep going", class: "go"}, {value: "Rework", class: "revise"},
             {value: "End", class: "retire"}]}],
  phases: [{key: "start", label: "Start", role: "planning", section: "a"},
           {key: "live", label: "Live", role: "live", reachedBy: "G1", section: "b"}],
  review: {gate: "R", anchors: ["R", "G1"], monthsByRiskTier: {High: 6},
           defaultMonths: 12, dueSoonDays: 30},
  flags: [{rule: "pastDue"}, {plugin: "zz.test"}, {rule: "openWhenLive"},
          {rule: "review", gate: "G1"}, {rule: "reviseAtReview", gate: "R"}],
}"""

PLAIN = """{
  schemaVersion: 1, id: "pl", name: "Plain", role: "primary",
  statuses: [{value: "y", class: "done"}, {value: "n", class: "open"}],
  sections: [{id: "only", n: 1, title: "Only", items: [{id: "i1", text: "one"}]}],
  flags: [{rule: "pastDue"}],
}"""


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(APP.as_uri())
        end = time.time() + 15
        while time.time() < end and not page.evaluate(
            "() => typeof LOADED !== 'undefined' && LOADED"
        ):
            page.wait_for_timeout(100)
        page.evaluate(
            f"""() => {{
              window.ZZ = engineFramework({DEF});
              window.PL = engineFramework({PLAIN});
              registerPlugin("zz.test", {{flags: ctx => ctx.live
                ? [{{sev: Severity.AMBER, text: "plugin flag", msg: ["x", {{}}]}}]
                : []}});
              window.proj = (gates, items, extra) => Object.assign({{
                meta: {{reviewCadence: "", riskTier: ""}}, gates: gates || {{}},
                items: items || {{}}, updatedAt: null}}, extra || {{}});
            }}"""
        )

        print("Scores, by status class")
        sc = page.evaluate(
            "ZZ.score(ZZ.items,"
            " {a1: {status: 'y'}, a2: {status: 'h'}, b1: {status: 'd'}})"
        )
        check(
            "done 1, partial half; declined answered but out of the denominator",
            sc
            == {"pct": 75, "answered": 3, "total": 3, "applicable": 2, "declined": 1},
            str(sc),
        )
        sc = page.evaluate(
            "ZZ.score(ZZ.items, {a1: {status: 'x'}, a2: {status: 'zzz'}, b1: {}})"
        )
        check(
            "excluded leaves the denominator; an unknown status counts as no credit",
            sc["applicable"] == 2 and sc["pct"] == 0 and sc["answered"] == 2,
            str(sc),
        )

        print("Phase, by decision class")
        ph = page.evaluate("ZZ.phase(proj())")
        check("no decision: the first phase", ph["key"] == "start", str(ph))
        ph = page.evaluate("ZZ.phase(proj({G1: {decision: 'Go'}}))")
        check(
            "an advancing decision reaches its phase, with its section's number",
            ph["key"] == "live" and ph["stage"] == 2,
            str(ph),
        )
        ph = page.evaluate("ZZ.phase(proj({G1: {decision: 'Approve'}}))")
        check(
            "a value the definition does not know advances nothing",
            ph["key"] == "start",
        )
        ph = page.evaluate("ZZ.phase(proj({G1: {decision: 'Halt'}}))")
        check("a stop-class decision: Stopped", ph["label"] == "Stopped", str(ph))
        ph = page.evaluate(
            "ZZ.phase(proj({G1: {decision: 'Go'}, R: {decision: 'End'}}))"
        )
        check("a retire-class decision: Retired", ph["label"] == "Retired", str(ph))

        print("The review clock")
        nr = page.evaluate(
            "ZZ.nextReview(proj({G1: {decision: 'Go', date: '2026-01-10'},"
            " R: {decision: 'Keep going', date: ''}}))"
        )
        check(
            "a review decided without a date falls back to the next anchor",
            nr == "2027-01-10",
            str(nr),
        )
        nr = page.evaluate(
            "ZZ.nextReview(proj({G1: {decision: 'Go', date: '2026-01-10'},"
            " R: {decision: 'Keep going', date: '2026-03-01'}}, {}, "
            "{meta: {reviewCadence: '', riskTier: 'High'}}))"
        )
        check(
            "a dated review starts the clock, at the risk tier's cadence",
            nr == "2026-09-01",
            str(nr),
        )
        nr = page.evaluate("ZZ.nextReview(proj({G1: {decision: 'Halt'}}))")
        check("no review while not live", nr is None, str(nr))

        print("Flags: the definition's order, red first")
        fl = page.evaluate(
            "ZZ.flags(proj({G1: {decision: 'Go', date: ''}, R: {decision: 'Rework'}},"
            " {a1: {status: 'n'}}))"
        )
        texts = [f["text"] for f in fl]
        check(
            "the plug-in flag sits where the definition put it, after red sorts first",
            texts
            == [
                "Live with 1 criterion not met",
                "Live with no deployment date recorded at Gate one",
                "plugin flag",
                "Last review asked for retraining or revision",
            ],
            str(texts),
        )

        print("CHAI, every decision: retired exactly on a stop or retire option")
        # The server's retention SQL holds the same set (server/tests/test_retention.py
        # reads it from the definition); this is the dashboard's side, on the engine.
        rows = page.evaluate(
            """() => CHAI_DEF.gates.flatMap(g => g.options.map(o => {
                 const ph = ENGINES.chai.phase({gates: {[g.id]: {decision: o.value}},
                                                items: {}, meta: {}});
                 return [g.id, o.value, o.class, ph.key];
               }))"""
        )
        wrong = [r for r in rows if (r[3] == "retired") != (r[2] in ("stop", "retire"))]
        check(
            f"all {len(rows)} of CHAI's gate options",
            len(rows) == 16 and not wrong,
            str(wrong or len(rows)),
        )
        ending = sorted((r[0], r[1]) for r in rows if r[3] == "retired")
        check(
            "and the ending ones are the four the server retires",
            ending == [("A", "Stop"), ("B", "Stop"), ("C", "Stop"), ("D", "Retire")],
            str(ending),
        )

        print("A plain checklist with no lifecycle")
        ph = page.evaluate("PL.phase(proj())")
        check("has no phase, and does not throw", ph["key"] == "", str(ph))
        check("has no review", page.evaluate("PL.nextReview(proj())") is None)
        st = page.evaluate("PL.status(proj())")
        check("is on track with nothing overdue", st["key"] == "green", str(st))

        check("no page errors", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("engine checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
