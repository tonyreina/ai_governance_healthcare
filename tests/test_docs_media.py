#!/usr/bin/env python3
"""The showcase video on the docs site: present, bounded, first-party, honest.

A broken video on the front page of the project is silent. The strict docs build
checks Markdown links, not the `src` of a `<video>`, so a renamed file or a
dropped asset would publish a page with a dead player and nothing would fail.

What is asserted, and why:

* every media file the page and README reference exists, so the player is not dead;
* each file is under the cap and the pre-commit guard enforces the SAME cap, so the
  exception to the repo-wide 512 KB limit cannot drift wider than the page assumes;
* the video is an MP4 with its index at the front, so it starts playing before it
  has finished downloading (a bad re-encode loses this without any visible error);
* the page is first-party: no iframe, no third-party media URL (R-05);
* the player has controls and a poster and does not autoplay: a 90-second video
  that starts talking on page load is an accessibility failure, not a feature;
* the page says the video shows the Docker stack, not the browser-only demonstration
  copy (R-04), because a viewer will otherwise assume the demo behaves like it.

Each rule has a mutation test: break a copy of the real page and demand it notice.

    pixi run test-docs-media
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS_PAGE = ROOT / "docs" / "index.md"
README = ROOT / "README.md"
ASSETS = ROOT / "docs" / "assets"
PRECOMMIT = ROOT / ".pre-commit-config.yaml"

MAX_MEDIA_KB = 10240
MEDIA_SUFFIXES = (".mp4", ".webm", ".jpg", ".jpeg", ".png")
LOCAL_MEDIA = re.compile(r"""(?:src|poster|href)="((?!https?:|#)[^"]*assets/[^"]+)""")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# --- the rules: plain data in, a list of problems out -----------------------


def missing_media(page: str, base: Path) -> list[str]:
    return [
        f"{ref} is referenced but does not exist"
        for ref in LOCAL_MEDIA.findall(page)
        if not (base / ref).exists()
    ]


def oversized(directory: Path, cap_kb: int) -> list[str]:
    return [
        f"{p.name} is {p.stat().st_size // 1024} KB, over the {cap_kb} KB cap"
        for p in sorted(directory.glob("*"))
        if p.suffix in MEDIA_SUFFIXES and p.stat().st_size > cap_kb * 1024
    ]


def cap_the_guard_enforces(config: dict) -> int | None:
    """The --maxkb of the pre-commit hook that covers docs/assets media."""
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") != "check-added-large-files":
                continue
            if "docs/assets" not in str(hook.get("files", "")):
                continue
            for arg in hook.get("args", []):
                found = re.fullmatch(r"--maxkb=(\d+)", arg)
                if found:
                    return int(found.group(1))
    return None


def repo_wide_guard_excludes_media(config: dict) -> bool:
    """The general 512 KB hook must not also fire on the media it exempts."""
    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            if hook.get("id") == "check-added-large-files" and "files" not in hook:
                return "docs/assets" in str(hook.get("exclude", ""))
    return False


def not_streamable(path: Path) -> list[str]:
    head = path.read_bytes()[:400_000]
    problems = []
    if head[4:8] != b"ftyp":
        problems.append(f"{path.name} is not an MP4 (no ftyp box)")
    moov, mdat = head.find(b"moov"), head.find(b"mdat")
    if moov == -1 or (mdat != -1 and mdat < moov):
        problems.append(
            f"{path.name} has its index after the data, so it cannot start playing "
            "until fully downloaded (re-encode with -movflags +faststart)"
        )
    return problems


def third_party(page: str) -> list[str]:
    problems = []
    if re.search(r"<iframe", page, re.I):
        problems.append("the page embeds an iframe (a third party), against R-05")
    for url in re.findall(
        r"""<(?:video|source)[^>]*\b(?:src|poster)="(https?://[^"]+)""", page
    ):
        problems.append(f"the player loads {url} from another origin")
    return problems


def player_problems(page: str) -> list[str]:
    video = re.search(r"<video\b[^>]*>", page, re.S)
    if not video:
        return ["there is no <video> element"]
    tag = video.group(0)
    problems = []
    if "controls" not in tag:
        problems.append("the player has no controls")
    if "poster=" not in tag:
        problems.append("the player has no poster, so it is a black box until clicked")
    if re.search(r"\bautoplay\b", tag):
        problems.append("the video autoplays; a narrated video must wait to be played")
    if "aria-label" not in tag:
        problems.append("the player has no accessible name")
    return problems


def mode_honesty_problems(page: str) -> list[str]:
    section = page[page.find("See it in action") :][:2500]
    ok = "Docker stack" in section and "browser-only" in section
    return (
        []
        if ok
        else [
            "the section does not say the video shows the Docker stack and that the "
            "demonstration copy is browser-only (R-04)"
        ]
    )


def every_rule() -> list[str]:
    page = DOCS_PAGE.read_text(encoding="utf-8")
    config = yaml.safe_load(PRECOMMIT.read_text(encoding="utf-8"))
    videos = sorted(ASSETS.glob("*.mp4"))
    problems = [
        *missing_media(page, DOCS_PAGE.parent),
        *missing_media(README.read_text(encoding="utf-8"), README.parent),
        *oversized(ASSETS, MAX_MEDIA_KB),
        *third_party(page),
        *player_problems(page),
        *mode_honesty_problems(page),
    ]
    for video in videos:
        problems += not_streamable(video)
    if cap_the_guard_enforces(config) != MAX_MEDIA_KB:
        problems.append(
            f"no pre-commit hook caps docs/assets media at {MAX_MEDIA_KB} KB "
            f"(found {cap_the_guard_enforces(config)})"
        )
    if not repo_wide_guard_excludes_media(config):
        problems.append("the repo-wide 512 KB guard does not exclude docs/assets media")
    if not videos:
        problems.append("there is no video in docs/assets")
    return problems


# --- tests ------------------------------------------------------------------


def main() -> int:
    print("The real page, assets and guard")
    problems = every_rule()
    check("every rule passes", not problems, "; ".join(problems))

    page = DOCS_PAGE.read_text(encoding="utf-8")
    good = re.search(r"<video\b.*?</video>", page, re.S).group(0)

    print("Mutation tests: each rule must notice when it is broken")
    check(
        "a renamed or missing asset is noticed",
        bool(missing_media(page.replace("-demo.mp4", "-gone.mp4"), DOCS_PAGE.parent)),
    )
    check(
        "a missing poster file is noticed",
        bool(missing_media(page.replace("-demo.jpg", "-gone.jpg"), DOCS_PAGE.parent)),
    )
    check(
        "an iframe embed is noticed",
        bool(third_party(page + '<iframe src="https://youtu.be/x"></iframe>')),
    )
    check(
        "a player loading from another origin is noticed",
        bool(
            third_party(
                good.replace('src="assets/', 'src="https://cdn.example.org/assets/')
            )
        ),
    )
    check(
        "autoplay is noticed",
        bool(player_problems(good.replace("controls", "controls autoplay"))),
    )
    check(
        "missing controls are noticed",
        bool(player_problems(good.replace("controls ", ""))),
    )
    check(
        "a missing poster attribute is noticed",
        bool(player_problems(re.sub(r'poster="[^"]+"', "", good))),
    )
    check(
        "a missing accessible name is noticed",
        bool(player_problems(re.sub(r'aria-label="[^"]+"', "", good))),
    )
    check("no video element at all is noticed", bool(player_problems("no video here")))
    check(
        "dropping the mode caveat is noticed",
        bool(mode_honesty_problems(page.replace("browser-only", "local"))),
    )
    check(
        "a stricter cap in the page than in the guard is noticed",
        cap_the_guard_enforces(
            {
                "repos": [
                    {
                        "hooks": [
                            {
                                "id": "check-added-large-files",
                                "files": "docs/assets",
                                "args": ["--maxkb=999999"],
                            }
                        ]
                    }
                ]
            }
        )
        != MAX_MEDIA_KB,
    )
    check(
        "no media guard at all is noticed",
        cap_the_guard_enforces({"repos": []}) is None,
    )
    check(
        "a guard that does not exempt media is noticed",
        not repo_wide_guard_excludes_media(
            {
                "repos": [
                    {
                        "hooks": [
                            {"id": "check-added-large-files", "args": ["--maxkb=512"]}
                        ]
                    }
                ]
            }
        ),
    )

    tmp = ROOT / ".pixi" / "docs-media-test"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        index_last = tmp / "late.mp4"
        index_last.write_bytes(
            b"\x00\x00\x00\x18ftypmp42"
            + b"\x00" * 16
            + b"mdat"
            + b"\x00" * 64
            + b"moov"
        )
        check(
            "an MP4 whose index is at the end is noticed",
            bool(not_streamable(index_last)),
        )
        not_mp4 = tmp / "x.mp4"
        not_mp4.write_bytes(b"RIFF....AVI ")
        check("a file that is not an MP4 is noticed", bool(not_streamable(not_mp4)))
        big = tmp / "big.mp4"
        big.write_bytes(b"\x00" * (11 * 1024 * 1024))
        check("a file over the cap is noticed", bool(oversized(tmp, MAX_MEDIA_KB)))
    finally:
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("docs media checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
