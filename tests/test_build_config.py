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
        for p in (ROOT / "docs" / "app" / "index.html", ROOT / "proxy" / "csp.caddy")
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

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("build config checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
