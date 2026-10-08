#!/usr/bin/env python3
"""scripts/preflight.py: the gate behind `make up`, tested by trying to get past it.

The README promises that `make up` "refuses to start on unsafe settings", and
preflight is the only thing keeping that sentence true. It guards three things
compose cannot express (compose can say "must be set", never "and not THAT value"):

* the database password: present, not a published placeholder, not trivial;
* the identity sources: a Caddy placeholder or empty, never a literal, because a
  literal stamps every visitor as one person;
* the bind: not published to the network while the stack speaks plain HTTP.

It decides from `.env` ALONE, so the way to get it wrong is to read `.env`
differently from the way compose does, and both of those mistakes fail open:

    SITE_ADDRESS=            compose: the default, plain http://:80.   Preflight
                             used to read "" as "not plain HTTP" and wave through
                             a bind to the whole network.
    POSTGRES_PASSWORD=abc # a long note about this
                             compose: "abc".  Preflight counted the note and
                             passed a three-character password.

So these tests pin preflight to compose's own rules: an empty value means the
default, an unquoted ` #` starts a comment, a quoted value keeps its `#`, and the
`export` prefix is accepted.

    pixi run test-preflight
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "preflight", ROOT / "scripts" / "preflight.py"
)
pf = importlib.util.module_from_spec(spec)
sys.modules["preflight"] = pf
spec.loader.exec_module(pf)

GOOD_PASSWORD = "a-Perfectly/Fine+Password=0123456789"
PLACEHOLDER_IDENTITY = "{http.request.header.X-Forwarded-Email}"
SAFE = {"POSTGRES_PASSWORD": GOOD_PASSWORD, "IDENTITY_ID_SOURCE": PLACEHOLDER_IDENTITY}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def problems(**overrides: str) -> list[str]:
    return pf.check({**SAFE, **overrides})


def mentions(found: list[str], text: str) -> bool:
    return any(text in p for p in found)


def parse(text: str) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / ".env"
        path.write_text(text, encoding="utf-8")
        return pf.read_env(path)


def run_main(env_text: str | None, **environ: str) -> tuple[int, str]:
    """Run main() in a throwaway directory, as `make preflight` does."""
    cwd, saved = os.getcwd(), dict(os.environ)
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            if env_text is not None:
                Path(".env").write_text(env_text, encoding="utf-8")
            os.environ.pop("FORCE", None)
            os.environ.update(environ)
            with contextlib.redirect_stdout(out):
                code = pf.main()
        finally:
            os.chdir(cwd)
            os.environ.clear()
            os.environ.update(saved)
    return code, out.getvalue()


def main() -> int:
    print("A complete, safe configuration passes")
    check("a strong password and a placeholder identity", problems() == [])
    check(
        "a password with every awkward character is fine (R-25)",
        problems(POSTGRES_PASSWORD="pw/with+slash=and:colon@#?%&[]x") == [],
    )

    print("The database password")
    check(
        "an empty password is refused",
        mentions(problems(POSTGRES_PASSWORD=""), "POSTGRES_PASSWORD is empty"),
    )
    check(
        "and the message says how to make one",
        mentions(problems(POSTGRES_PASSWORD=""), "openssl rand"),
    )
    for placeholder in (
        "replace-me-before-first-run",
        "replace-me",
        "changeme",
        "password",
        "postgres",
        "chai",
        "dev-only-not-a-secret",
    ):
        check(
            f"the placeholder {placeholder!r} is refused",
            mentions(problems(POSTGRES_PASSWORD=placeholder), "placeholder"),
        )
    check(
        "a placeholder is matched without regard to case",
        mentions(problems(POSTGRES_PASSWORD="ChangeMe"), "placeholder"),
    )
    check(
        "REPLACE-ME in capitals is refused",
        mentions(
            problems(POSTGRES_PASSWORD="REPLACE-ME-BEFORE-FIRST-RUN"), "placeholder"
        ),
    )
    check(
        "15 characters is refused",
        mentions(problems(POSTGRES_PASSWORD="x" * 15), "15 characters"),
    )
    check("16 characters is accepted", problems(POSTGRES_PASSWORD="x" * 16) == [])
    short = "Sh0rt-Secret"
    check(
        "a short password's value is never echoed",
        not any(short in p for p in problems(POSTGRES_PASSWORD=short)),
    )
    check(
        "a managed instance has no password to check",
        problems(
            POSTGRES_PASSWORD="",
            DATABASE_URL="postgresql://chai@/chai?host=/cloudsql/p:r:i",
        )
        == [],
    )

    print("The identity sources")
    for name in ("IDENTITY_ID_SOURCE", "IDENTITY_EMAIL_SOURCE"):
        check(
            f"a literal {name} is refused",
            mentions(problems(**{name: "dev@localhost"}), "is a literal"),
        )
        check(
            f"a Caddy placeholder in {name} is accepted",
            problems(**{name: PLACEHOLDER_IDENTITY}) == [],
        )
        check(
            f"an empty {name} is accepted, so the proxy 401s every request",
            problems(**{name: ""}) == [],
        )
    check(
        "the message points at make dev for local use",
        mentions(problems(IDENTITY_ID_SOURCE="dev@localhost"), "make dev"),
    )
    check(
        "a literal display name is not an identity and is not refused",
        problems(IDENTITY_NAME_SOURCE="Dev User") == [],
    )
    check(
        "both literals are reported separately",
        len(
            [
                p
                for p in problems(IDENTITY_ID_SOURCE="a@b", IDENTITY_EMAIL_SOURCE="a@b")
                if "literal" in p
            ]
        )
        == 2,
    )

    print("The bind: plain HTTP is not published to the network")
    for host in ("127.0.0.1", "::1", "localhost"):
        check(
            f"loopback {host} is fine over plain HTTP",
            problems(HTTP_BIND=host, SITE_ADDRESS="http://:80") == [],
        )
    check(
        "0.0.0.0 over plain HTTP is refused",
        mentions(
            problems(HTTP_BIND="0.0.0.0", SITE_ADDRESS="http://:80"), "plain HTTP"
        ),
    )
    check(
        "a LAN address over plain HTTP is refused",
        mentions(
            problems(HTTP_BIND="192.168.1.10", SITE_ADDRESS="http://:80"), "plain HTTP"
        ),
    )
    check(
        "http://host over plain HTTP is refused",
        mentions(
            problems(HTTP_BIND="0.0.0.0", SITE_ADDRESS="http://gov.example.org"),
            "plain HTTP",
        ),
    )
    check(
        "a hostname makes Caddy provision TLS, so 0.0.0.0 is fine",
        problems(HTTP_BIND="0.0.0.0", SITE_ADDRESS="governance.example.org") == [],
    )
    check(
        "https:// is TLS too",
        problems(HTTP_BIND="0.0.0.0", SITE_ADDRESS="https://governance.example.org")
        == [],
    )
    check(
        "the message names the way out",
        mentions(problems(HTTP_BIND="0.0.0.0", SITE_ADDRESS="http://:80"), "FORCE=1"),
    )

    print("Empty means the default, exactly as compose reads it")
    check("HTTP_BIND unset is loopback", problems() == [])
    check("HTTP_BIND= (blank) is loopback, not a refusal", problems(HTTP_BIND="") == [])
    check(
        "SITE_ADDRESS= (blank) is plain HTTP, so 0.0.0.0 is REFUSED",
        mentions(problems(HTTP_BIND="0.0.0.0", SITE_ADDRESS=""), "plain HTTP"),
    )
    check(
        "SITE_ADDRESS unset is plain HTTP, so 0.0.0.0 is REFUSED",
        mentions(problems(HTTP_BIND="0.0.0.0"), "plain HTTP"),
    )

    print("Its defaults are the ones compose.yaml uses")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    bind = re.search(r"\$\{HTTP_BIND:-([^}]+)\}", compose)
    site = re.search(r"\$\{SITE_ADDRESS:-([^}]+)\}", compose)
    check(
        "the HTTP_BIND default matches",
        bool(bind) and bind.group(1) == getattr(pf, "DEFAULT_BIND", None),
        "pf.DEFAULT_BIND is not defined",
    )
    check(
        "the SITE_ADDRESS default matches",
        bool(site) and site.group(1) == getattr(pf, "DEFAULT_SITE", None),
        "pf.DEFAULT_SITE is not defined",
    )

    print("Reading .env the way compose does")
    check("an equals sign in a value is kept", parse("A=b=c").get("A") == "b=c")
    check("double quotes are removed", parse('A="two words"').get("A") == "two words")
    check("single quotes are removed", parse("A='two words'").get("A") == "two words")
    check(
        "blank lines and comment lines are ignored",
        parse("\n# A=1\n\nB=2\n") == {"B": "2"},
    )
    check(
        "spaces around the key and value are trimmed",
        parse("  A = b  ").get("A") == "b",
    )
    check("an empty value is an empty string", parse("A=").get("A") == "")
    check(
        "a missing file is an empty configuration",
        pf.read_env(Path("/nonexistent/.env")) == {},
    )
    check(
        "an unquoted ' #' starts a comment", parse("A=val # a note").get("A") == "val"
    )
    check(
        "a '#' with no space before it is part of the value",
        parse("A=pass#word").get("A") == "pass#word",
    )
    check(
        "a '#' inside quotes is kept", parse('A="pass #word"').get("A") == "pass #word"
    )
    check(
        "a comment after a closing quote is dropped",
        parse('A="val" # note').get("A") == "val",
    )
    check("a tab before '#' starts a comment", parse("A=val\t# note").get("A") == "val")
    check("the export prefix is accepted", parse("export A=1").get("A") == "1")

    print("A comment cannot make a weak value look strong")
    weak = parse(
        "POSTGRES_PASSWORD=abc # this long note must not count toward the length"
    )
    check(
        "the password is just what compose would use",
        weak.get("POSTGRES_PASSWORD") == "abc",
    )
    check(
        "so a weak one with a long note is still refused",
        mentions(pf.check({**SAFE, **weak}), "3 characters"),
    )
    check(
        "a comment after a bind is not part of it",
        problems(**parse("HTTP_BIND=127.0.0.1 # loopback only")) == [],
    )
    check(
        "an exported password is still checked",
        mentions(
            pf.check({**SAFE, **parse("export POSTGRES_PASSWORD=short")}),
            "5 characters",
        ),
    )

    print("main(): what the operator actually sees")
    code, out = run_main("POSTGRES_PASSWORD=\nIDENTITY_ID_SOURCE=\n")
    check("an unsafe .env exits 1", code == 1, str(code))
    check("and says how many problems and where", "problem(s) in .env" in out)
    check("and offers the override", "make up FORCE=1" in out)
    code, out = run_main(
        f"POSTGRES_PASSWORD={GOOD_PASSWORD}\nIDENTITY_ID_SOURCE={PLACEHOLDER_IDENTITY}\n"
    )
    check("a safe .env exits 0", code == 0, str(code))
    check("and says ok", "preflight: ok" in out)
    code, out = run_main("POSTGRES_PASSWORD=\n", FORCE="1")
    check("FORCE=1 skips the check and exits 0", code == 0, str(code))
    check(
        "and says it skipped, not that it passed", "skipped" in out and "ok" not in out
    )
    code, _ = run_main(None)
    check("no .env at all is refused, not waved through", code == 1, str(code))

    print("The first-run path the README documents")
    shipped = pf.read_env(ROOT / ".env.example")
    check(
        "the shipped template is refused until a password is set",
        mentions(pf.check(shipped), "POSTGRES_PASSWORD is empty"),
    )
    done = {
        **shipped,
        "POSTGRES_PASSWORD": "pwYZ1MXvvrx+eItO/Zq=0123456789abcdef",
        "IDENTITY_ID_SOURCE": PLACEHOLDER_IDENTITY,
    }
    check(
        "the shipped template plus a base64 password and an identity passes",
        pf.check(done) == [],
        str(pf.check(done)),
    )

    print("Google IAP needs its prefix stripped, or access lists never match (#35)")
    goog = "{http.request.header.X-Goog-Authenticated-User-Id}"
    goog_mail = "{http.request.header.X-Goog-Authenticated-User-Email}"
    check(
        "a Google identity source with no strip prefix is refused",
        mentions(problems(IDENTITY_ID_SOURCE=goog), "IDENTITY_STRIP_PREFIX"),
    )
    check(
        "the email source alone is enough to trigger it",
        mentions(problems(IDENTITY_EMAIL_SOURCE=goog_mail), "IDENTITY_STRIP_PREFIX"),
    )
    check(
        "an explicitly empty prefix is the same as unset",
        mentions(
            problems(IDENTITY_ID_SOURCE=goog, IDENTITY_STRIP_PREFIX=""),
            "IDENTITY_STRIP_PREFIX",
        ),
    )
    check(
        "the right prefix passes",
        not mentions(
            problems(
                IDENTITY_ID_SOURCE=goog, IDENTITY_STRIP_PREFIX="accounts.google.com:"
            ),
            "IDENTITY_STRIP_PREFIX",
        ),
    )
    check(
        "a header match is not case sensitive, as HTTP header names are not",
        mentions(
            problems(
                IDENTITY_ID_SOURCE="{http.request.header.x-goog-authenticated-user-id}"
            ),
            "IDENTITY_STRIP_PREFIX",
        ),
    )
    check(
        "other front doors need no prefix",
        not mentions(
            problems(
                IDENTITY_ID_SOURCE="{http.request.header.X-Forwarded-User}",
            ),
            "IDENTITY_STRIP_PREFIX",
        ),
    )
    check(
        "a prefix that is not Google's is refused for a Google source",
        mentions(
            problems(IDENTITY_ID_SOURCE=goog, IDENTITY_STRIP_PREFIX="oops:"),
            "IDENTITY_STRIP_PREFIX",
        ),
    )

    # The template's own Google block, uncommented as its comment says to, must
    # work. It did not: a later `IDENTITY_STRIP_PREFIX=` at the bottom of the file
    # re-emptied what the block had set, and compose takes the last value.
    template = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(template) if "Google Cloud: Identity" in ln)
    block = []
    for ln in template[start + 1 :]:
        if ln.startswith("# ---"):
            break
        if re.match(r"# IDENTITY_\w+=", ln):
            block.append(ln[2:])
    spliced = "\n".join(
        ln
        for ln in template
        if not ln.startswith(
            ("IDENTITY_ID_SOURCE=", "IDENTITY_NAME_SOURCE=", "IDENTITY_EMAIL_SOURCE=")
        )
    )
    in_place = pf.check(
        parse(
            spliced.replace(
                "# IDENTITY_ID_SOURCE={http.request.header.X-Goog",
                "IDENTITY_ID_SOURCE={http.request.header.X-Goog",
            ).replace(
                "# IDENTITY_STRIP_PREFIX=accounts.google.com:",
                "IDENTITY_STRIP_PREFIX=accounts.google.com:",
            )
            + "\nPOSTGRES_PASSWORD="
            + GOOD_PASSWORD
        )
    )
    check(
        "uncommenting the template's Google block, in place, passes preflight",
        not mentions(in_place, "IDENTITY_STRIP_PREFIX"),
        str(in_place),
    )
    check("the block names the prefix", any("accounts.google.com:" in b for b in block))
    check(
        "nothing later in the file re-empties the prefix it sets",
        parse(
            "\n".join(
                [
                    "IDENTITY_STRIP_PREFIX=accounts.google.com:",
                    *[ln for ln in template if ln.startswith("IDENTITY_STRIP_PREFIX=")],
                ]
            )
        ).get("IDENTITY_STRIP_PREFIX")
        == "accounts.google.com:",
        "an active `IDENTITY_STRIP_PREFIX=` line after the Google block wins over it",
    )

    print("Every identity example the docs show passes the gate (#62)")
    # The self-hosting guide's first example was IDENTITY_ID_SOURCE=dev@localhost,
    # the exact literal preflight refuses to start on, and it was the uncommented
    # line. An operator who copied it was stopped by the gate, and one who forced
    # past it made every visitor the same person. Run every uncommented
    # IDENTITY_*_SOURCE assignment in the docs through the real check.
    assign = re.compile(r"^\s*(?:export\s+)?(IDENTITY_\w+?)=(\S*)\s*(?:#.*)?$")
    shown = 0
    for doc in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        # A document's examples are one configuration: evaluate them TOGETHER, so
        # a source that needs a companion setting (the Google prefix) is held to it.
        found_here: dict[str, str] = {}
        for line in doc.read_text().splitlines():
            found = assign.match(line)
            if found:
                shown += 1
                found_here[found.group(1)] = found.group(2).strip()
        if not found_here:
            continue
        refused = [p for p in pf.check({**SAFE, **found_here}) if "IDENTITY" in p]
        check(
            f"{doc.relative_to(ROOT)}: its identity examples pass preflight together",
            not refused,
            str(refused),
        )
    check("the scan found the examples it is meant to check", shown > 0, str(shown))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("preflight checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
