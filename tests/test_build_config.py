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
import os
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

    print("A build of other frameworks goes where --out says, and nowhere else")
    example = ROOT / "app" / "frameworks" / "example" / "build.json"
    published = {
        p: p.read_bytes()
        for p in (
            ROOT / "docs" / "app" / "index.html",
            ROOT / "proxy" / "csp.caddy",
            ROOT / "docs" / "app" / "manifest.json",
        )
    }
    check(
        "--config without --out is refused",
        build_app.main(["--config", str(example)]) == 2,
    )
    check(
        "--out without --config is refused",
        build_app.main(["--out", "somewhere"]) == 2,
    )
    codes = {
        tracked: build_app.main(
            ["--config", str(example), "--out", str(ROOT / tracked)]
        )
        for tracked in ("docs", "docs/app", "proxy", "app")
    }
    # A directory elsewhere whose index.html is a link to the published page.
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
        (Path(tmp) / "index.html").symlink_to(ROOT / "docs" / "app" / "index.html")
        codes["a link to the published page"] = build_app.main(
            ["--config", str(example), "--out", tmp]
        )
    # And one whose manifest.json is a link to the published manifest.
    with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
        (Path(tmp) / "manifest.json").symlink_to(
            ROOT / "docs" / "app" / "manifest.json"
        )
        codes["a link to the published manifest"] = build_app.main(
            ["--config", str(example), "--out", tmp]
        )
    check(
        "an --out into docs/, proxy/ or app/ is refused",
        all(code == 2 for code in codes.values()),
        str(codes),
    )
    # Inside the repository (build/ is ignored): the crash was there.
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
        cwd = Path.cwd()
        os.chdir(tmp)
        try:
            # A relative --out crashed after writing the page (shown its path
            # relative to the repository, which a relative path is not).
            code = build_app.main(["--config", str(example), "--out", "out"])
        except ValueError as e:
            code = f"ValueError: {e}"
        finally:
            os.chdir(cwd)
        check("a relative --out builds", code == 0, str(code))
        page = Path(tmp) / "out" / "index.html"
        check(
            "the page and its proxy policy are written there",
            page.exists() and (Path(tmp) / "out" / "csp.caddy").exists(),
        )
        html = page.read_text(encoding="utf-8") if page.exists() else ""
        check("it is the example's build", '"primary":"example"' in html)
        # The server retires by the manifest beside the page it serves (D-76), so a
        # custom build's manifest is its own, in --out, never the published one.
        import build_manifest as bm

        written = Path(tmp) / "out" / "manifest.json"
        example_defs = build_app.framework_defs(example, custom=True)
        check(
            "its manifest is written there too, for the example's primary",
            written.exists()
            and written.read_text(encoding="utf-8")
            == bm.manifest_json(example_defs, "example"),
        )
        shown = json.loads(written.read_text("utf-8")) if written.exists() else {}
        check(
            "the manifest names the example as primary",
            shown.get("primary") == "example",
            str(shown.get("primary")),
        )

        # A config whose primary is not listed first: the manifest's primary, and
        # the rule set the server retires by, are still the primary's, never the
        # first framework's.
        later = Path(tmp) / "later.json"
        later.write_text(
            json.dumps({"primary": "example", "frameworks": ["optica", "example"]})
        )
        code = build_app.main(["--config", str(later), "--out", str(Path(tmp) / "l")])
        check("a config listing its primary second builds", code == 0, str(code))
        out = Path(tmp) / "l" / "manifest.json"
        got = json.loads(out.read_text("utf-8")) if out.exists() else {}
        later_defs = build_app.framework_defs(later, custom=True)
        example_pairs = {
            (g["id"], o["value"])
            for g in later_defs["example"]["gates"]
            for o in g["options"]
            if o["class"] in ("stop", "retire")
        }
        check(
            "its manifest names that primary, and hashes that primary's rules",
            [f["id"] for f in got.get("frameworks", [])] == ["optica", "example"]
            and got.get("primary") == "example"
            and got.get("ruleSetHash")
            == bm.rule_set_hash(
                "example",
                [{"gate": g, "decision": d} for g, d in sorted(example_pairs)],
            )
            and bool(example_pairs),
            str({k: got.get(k) for k in ("primary", "ruleSetHash")}),
        )
        # Mutation: taking the first framework listed as the primary would write
        # another manifest (here none: OPTICA ends nothing, so the build would fail),
        # which the check above tells apart.
        try:
            first = bm.manifest_json(later_defs, next(iter(later_defs)))
        except SystemExit:
            first = None
        check(
            "mutation: the first-listed framework's manifest is not this one",
            out.exists() and first != out.read_text("utf-8"),
        )
    check(
        "the published page and policy are untouched",
        all(p.read_bytes() == b for p, b in published.items()),
    )

    print("Only the selected frameworks' text ships, with their languages")

    def parsed(js: str, name: str) -> dict:
        m = re.search(rf"const {name} = Object\.freeze\((\{{.*?\}})\);", js, re.S)
        return json.loads(m.group(1)) if m else {}

    js = build_app.catalogs_js()
    locales = parsed(js, "FRAMEWORK_LOCALES")
    seven = ["de", "es", "fr", "he", "hi", "ru", "zh-Hans"]
    check(
        "the default build: CHAI and OPTICA in all seven other languages",
        locales == {"chai": seven, "optica": seven},
        str(locales),
    )
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "app"
        shutil.copytree(ROOT / "app" / "i18n", src / "i18n")
        shutil.copytree(ROOT / "app" / "frameworks", src / "frameworks")
        zz = json.loads((src / "frameworks/chai/framework.json").read_text("utf-8"))
        zz.update(id="zz", namespaces=["zz"])
        (src / "frameworks/zz/i18n").mkdir(parents=True)
        (src / "frameworks/zz/framework.json").write_text(json.dumps(zz))
        (src / "frameworks/zz/i18n/de.json").write_text(
            json.dumps({"zz.item.s1-1": "Bedarf"})
        )
        js = build_app.catalogs_js({"zz": zz}, src=src)
        shell = parsed(js, "I18N_CATALOGS")["en"]
        content = parsed(js, "FRAMEWORK_I18N")
        foreign = sorted(
            k for k in shell if k.split(".")[0] in ("chai", "te", "optica")
        )
        check(
            "a custom build's catalogs carry no CHAI or OPTICA keys",
            not foreign,
            str(foreign[:4]),
        )
        check(
            "and no CHAI or OPTICA content in any language",
            not [k for cat in content.values() for k in cat if not k.startswith("zz.")],
        )
        check(
            "its own translation ships",
            content.get("de", {}).get("zz.item.s1-1") == "Bedarf",
        )
        check(
            "and its languages are recorded",
            parsed(js, "FRAMEWORK_LOCALES") == {"zz": ["de"]},
            str(parsed(js, "FRAMEWORK_LOCALES")),
        )
        # A key CHAI's own translations already hold, in a build with both.
        (src / "frameworks/zz/i18n/de.json").write_text(
            json.dumps({"chai.item.s1-1": "x"})
        )
        chai = json.loads((src / "frameworks/chai/framework.json").read_text("utf-8"))
        why = refused(lambda: build_app.catalogs_js({"chai": chai, "zz": zz}, src=src))
        check(
            "a translation file repeating another framework's key is refused",
            "repeats" in why,
            why,
        )

    manifest_checks(defs)

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("build config checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
