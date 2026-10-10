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

    print()
    if failures:
        print(f"{len(failures)} failure(s): {failures}")
        return 1
    print("build config checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
