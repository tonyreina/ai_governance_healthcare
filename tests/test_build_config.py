#!/usr/bin/env python3
"""The build embeds exactly the configured framework definitions (#168).

app/frameworks.json names the frameworks the published build contains and which is
primary. scripts/build_app.py embeds those definitions as FRAMEWORK_DEFS, and until
a build of other frameworks has a place of its own to go (step 3: --out), it refuses
any config other than the default, so nothing can overwrite docs/app/index.html with
a different framework. This shows the embedding is exact and each refusal fires.

    pixi run test-build-config
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def refused(fn) -> str:
    try:
        fn()
    except SystemExit as e:
        return str(e.code)
    return ""


def manifest_checks(defs: dict) -> None:
    """docs/app/manifest.json: what the server loads its retirement rules from (D-76).
    It must be the build's definitions, exactly, and its pairs must be exactly the
    options whose class ends a project, so a change to either is noticed."""
    import copy
    import hashlib

    import build_manifest as bm

    print("The build manifest (docs/app/manifest.json)")
    path = ROOT / "docs" / "app" / "manifest.json"
    committed = path.read_text(encoding="utf-8")
    check(
        "the committed manifest is what the build writes",
        committed == bm.manifest_json(defs, "chai"),
        "run pixi run build-app",
    )
    check(
        "build_app writes it beside the page",
        path == build_app.MANIFEST_OUT,
        str(build_app.MANIFEST_OUT),
    )
    m = json.loads(committed)
    by_id = {f["id"]: f for f in m["frameworks"]}
    check("it lists the build's frameworks, in order", list(by_id) == list(defs))
    check(
        "each definition's hash is of its canonical JSON",
        all(
            by_id[fid]["sha256"] == hashlib.sha256(bm.canonical_json(d)).hexdigest()
            and by_id[fid]["version"] == d["version"]
            for fid, d in defs.items()
        ),
    )
    chai_pairs = {(p["gate"], p["decision"]) for p in by_id["chai"]["retire"]}
    check(
        "CHAI ends a project on exactly Stop at A, B, C and Retire at D",
        chai_pairs == {("A", "Stop"), ("B", "Stop"), ("C", "Stop"), ("D", "Retire")},
        str(chai_pairs),
    )
    check("OPTICA, a supplement, ends nothing", by_id["optica"]["retire"] == [])
    check(
        "the rule-set hash is the primary's",
        m["primary"] == "chai"
        and m["ruleSetHash"] == bm.rule_set_hash("chai", by_id["chai"]["retire"]),
    )

    print("What the manifest notices (mutations)")
    more = copy.deepcopy(defs)
    gate = next(g for g in more["chai"]["gates"] if g["id"] == "C")
    gate["options"].append({"value": "Withdraw", "class": "stop"})
    grown = bm.manifest(more, "chai")
    check(
        "a new stop option becomes a pair and a new rule-set hash",
        {"gate": "C", "decision": "Withdraw"} in grown["frameworks"][0]["retire"]
        and grown["ruleSetHash"] != m["ruleSetHash"],
    )
    weaker = copy.deepcopy(defs)
    retire = next(
        o
        for g in weaker["chai"]["gates"]
        for o in g["options"]
        if o["value"] == "Retire"
    )
    retire["class"] = "revise"
    check(
        "an option that stops ending a project leaves the pairs",
        {"gate": "D", "decision": "Retire"}
        not in bm.manifest(weaker, "chai")["frameworks"][0]["retire"],
    )
    reworded = copy.deepcopy(defs)
    reworded["chai"]["name"] = reworded["chai"]["name"] + " (edited)"
    other = bm.manifest(reworded, "chai")
    check(
        "any edit changes the definition hash; only an ending change the rule set",
        other["frameworks"][0]["sha256"] != by_id["chai"]["sha256"]
        and other["ruleSetHash"] == m["ruleSetHash"],
    )
    for g in weaker["chai"]["gates"]:
        for o in g["options"]:
            if o["class"] in ("stop", "retire"):
                o["class"] = "revise"
    check(
        "a primary that ends nothing gets no manifest",
        "no stop or retire" in refused(lambda: bm.manifest(weaker, "chai")),
    )
    typo = copy.deepcopy(defs)
    typo["chai"]["gates"][0]["options"][0]["class"] = "stopped"
    try:
        bm.manifest(typo, "chai")
        typo_refused = False
    except ValueError:
        typo_refused = True
    check("a class nobody defined is an error, not a non-ending option", typo_refused)


def main() -> int:
    print("The published build")
    defs = build_app.framework_defs()
    check("embeds the default frameworks, in order", list(defs) == ["chai", "optica"])
    html = (ROOT / "docs" / "app" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"const FRAMEWORK_DEFS = Object\.freeze\((\{.*?\})\);\n", html, re.S)
    embedded = json.loads(m.group(1)) if m else {}
    on_disk = {
        fid: json.loads(
            (ROOT / "app" / "frameworks" / fid / "framework.json").read_text(
                encoding="utf-8"
            )
        )
        for fid in ("chai", "optica")
    }
    check("the page holds exactly the definitions on disk", embedded == on_disk)

    print("What it refuses (mutations)")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "frameworks.json"
        cfg.write_text(json.dumps({"primary": "optica", "frameworks": ["optica"]}))
        why = refused(lambda: build_app.framework_defs(cfg))
        check("a config naming another primary", "must be" in why, why)
        cfg.write_text(json.dumps({"primary": "chai", "frameworks": ["chai"]}))
        why = refused(lambda: build_app.framework_defs(cfg))
        check("a config dropping a framework", "must be" in why, why)

        # The default config, but CHAI's definition says it is a supplement.
        src = Path(tmp) / "app"
        shutil.copytree(ROOT / "app" / "frameworks", src / "frameworks")
        path = src / "frameworks" / "chai" / "framework.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        d["role"] = "supplement"
        path.write_text(json.dumps(d), encoding="utf-8")
        (src / "frameworks.json").write_text(json.dumps(build_app.DEFAULT_FRAMEWORKS))
        saved = build_app.SRC
        build_app.SRC = src
        try:
            why = refused(lambda: build_app.framework_defs(src / "frameworks.json"))
        finally:
            build_app.SRC = saved
        check("a primary whose definition is a supplement", "not a primary" in why, why)

    manifest_checks(defs)

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("build config checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
