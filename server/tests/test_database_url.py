"""A database password may contain any character.

`make dev` crashed on startup with

    ValueError: invalid literal for int() with base 10: 'pwYZ1MXvvrx+eItO'

because compose built the connection URL by pasting `${POSTGRES_PASSWORD}` into it.
A `/` in the password ends the URL's authority section, so the first chunk of the
password was read as a port number. The password came from `openssl rand -base64
32`, the generator `preflight.py` and `.env.example` tell people to use, and base64
produces a `/` often enough that about half of all passwords break the stack.

The fix is that nothing builds a URL by string interpolation. Compose passes the
pieces; the API assembles the URL and percent-encodes the password. These tests
hold it there:

* the pieces become a URL that any parser round-trips, for passwords chosen to
  break one and for a few thousand the documented generator actually produces;
* a role with a hostile password can really connect to a real PostgreSQL, and a
  wrong password really cannot (so the check is not passing because auth is off);
* a hand-written DATABASE_URL that is broken fails at startup with a message that
  says what is wrong and does NOT echo the password it was given;
* compose never again interpolates the password into a URL.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import asyncpg
import pytest
from app.config import Settings, build_database_url
from app.db import Database

from .conftest import DB_URL, requires_db

REPO = Path(__file__).resolve().parents[2]

# Characters that end or confuse a URL's authority, plus the shape that bit us.
AWKWARD = [
    "pwYZ1MXvvrx+eItO/Zq=",  # the shape of the password that crashed `make dev`
    "pw/with/slashes",
    "p@ss:word",
    "q?x#y%z",
    "a+b=c==",
    "has space",
    "ünïcödé-密码",
    "[brackets]{braces}",
    "quote'and\"double",
    "pw&amp;=%2F%40",  # already looks percent-encoded; must not be double-decoded
    "\\back\\slash\\",
    "all/\\+=@:?#%&[]{}!$'\" end",
]


def env(**overrides: str) -> dict[str, str]:
    base = {
        "POSTGRES_USER": "chai",
        "POSTGRES_HOST": "db",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "chai",
    }
    base.update(overrides)
    return base


def build(**overrides: str) -> str:
    return build_database_url(env(**overrides))


class TestThePiecesBecomeAUrlThatSurvivesAnyPassword:
    @pytest.mark.parametrize("password", AWKWARD)
    def test_every_awkward_password_round_trips(self, password: str):
        parts = urlsplit(build(POSTGRES_PASSWORD=password))
        assert parts.hostname == "db"
        assert parts.port == 5432, "the password must not leak into the port"
        assert parts.username == "chai"
        assert unquote(parts.password or "") == password
        assert parts.path == "/chai"

    def test_the_failure_this_replaces_is_real(self):
        """Pasting the password in raw is exactly what crashed. Keep that visible."""
        raw = "postgresql://chai:pwYZ1MXvvrx+eItO/Zq=@db:5432/chai"
        with pytest.raises(ValueError):
            urlsplit(raw).port  # noqa: B018  (the access is the test)
        assert urlsplit(build(POSTGRES_PASSWORD="pwYZ1MXvvrx+eItO/Zq=")).port == 5432

    def test_what_the_documented_generator_produces_always_works(self):
        """`openssl rand -base64 32`: about half of these used to break the URL."""
        for _ in range(3000):
            password = base64.b64encode(os.urandom(32)).decode()
            parts = urlsplit(build(POSTGRES_PASSWORD=password))
            assert parts.port == 5432
            assert unquote(parts.password or "") == password

    def test_user_and_database_names_are_encoded_too(self):
        parts = urlsplit(
            build(POSTGRES_PASSWORD="x", POSTGRES_USER="a/b", POSTGRES_DB="d@b")
        )
        assert parts.port == 5432
        assert unquote(parts.username or "") == "a/b"
        assert unquote(parts.path.lstrip("/")) == "d@b"

    def test_an_ipv6_host_is_bracketed(self):
        parts = urlsplit(build(POSTGRES_PASSWORD="x", POSTGRES_HOST="::1"))
        assert parts.hostname == "::1" and parts.port == 5432

    def test_defaults_are_the_compose_defaults(self):
        url = build_database_url({"POSTGRES_PASSWORD": "pw"})
        parts = urlsplit(url)
        assert (parts.username, parts.hostname, parts.port, parts.path) == (
            "chai",
            "localhost",
            5432,
            "/chai",
        )

    def test_no_password_means_no_url_not_a_guess(self):
        assert build_database_url({}) == ""
        assert build_database_url({"POSTGRES_PASSWORD": ""}) == ""


class TestAnExplicitDatabaseUrl:
    def test_it_wins_over_the_pieces(self):
        explicit = "postgresql://u:p@example.org:5432/x?sslmode=verify-full"
        out = build_database_url(
            {"DATABASE_URL": explicit, "POSTGRES_PASSWORD": "ignored"}
        )
        assert out == explicit

    def test_a_good_one_is_used_as_written(self):
        sock = "postgresql://chai@/chai?host=/cloudsql/proj:region:inst"
        assert build_database_url({"DATABASE_URL": sock}) == sock

    def test_a_broken_one_fails_at_startup_and_says_why(self):
        broken = "postgresql://chai:SuperSecret/Pw+9=@db:5432/chai"
        with pytest.raises(RuntimeError) as caught:
            build_database_url({"DATABASE_URL": broken})
        message = str(caught.value)
        assert "percent-encoded" in message, "tell the operator what to do"
        assert "POSTGRES_PASSWORD" in message, "and the easier way out"

    def test_the_message_never_contains_the_password(self):
        """An error that echoes a credential ends up in a log aggregator."""
        broken = "postgresql://chai:SuperSecret/Pw+9=@db:5432/chai"
        with pytest.raises(RuntimeError) as caught:
            build_database_url({"DATABASE_URL": broken})
        assert "SuperSecret" not in str(caught.value)
        assert "Pw+9" not in str(caught.value)


class TestSettingsFromTheEnvironment:
    def test_the_pieces_reach_the_settings(self, monkeypatch: pytest.MonkeyPatch):
        for k in ("DATABASE_URL", "POSTGRES_PASSWORD", "POSTGRES_HOST"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("POSTGRES_PASSWORD", "pw/with+slash=")
        monkeypatch.setenv("POSTGRES_HOST", "db")
        settings = Settings.from_env()
        assert urlsplit(settings.database_url).port == 5432
        assert (
            unquote(urlsplit(settings.database_url).password or "") == "pw/with+slash="
        )


# --- against a real PostgreSQL ----------------------------------------------


@requires_db
class TestARealRoleWithAHostilePassword:
    """Parsing is not connecting. This is the one that proves the password works."""

    PASSWORD = "pwYZ1MXvvrx+eItO/Zq=:@?#%&[]{}!$' \"end"

    async def test_it_connects_and_a_wrong_password_does_not(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        target = urlsplit(DB_URL)
        admin = await asyncpg.connect(DB_URL)
        try:
            literal = await admin.fetchval(
                "select quote_literal($1::text)", self.PASSWORD
            )
            await admin.execute("drop role if exists chai_awkward")
            await admin.execute(f"create role chai_awkward login password {literal}")
            for key in ("DATABASE_URL",):
                monkeypatch.delenv(key, raising=False)
            monkeypatch.setenv("POSTGRES_USER", "chai_awkward")
            monkeypatch.setenv("POSTGRES_PASSWORD", self.PASSWORD)
            monkeypatch.setenv("POSTGRES_HOST", target.hostname or "localhost")
            monkeypatch.setenv("POSTGRES_PORT", str(target.port or 5432))
            monkeypatch.setenv("POSTGRES_DB", target.path.lstrip("/"))

            settings = Settings.from_env()
            database = Database(
                settings.database_url, min_size=1, max_size=1, connect_timeout=10
            )
            await database.connect()
            try:
                async with database.acquire() as conn:
                    assert await conn.fetchval("select current_user") == "chai_awkward"
            finally:
                await database.close()

            monkeypatch.setenv("POSTGRES_PASSWORD", self.PASSWORD + "x")
            wrong = Settings.from_env()
            with pytest.raises(asyncpg.InvalidPasswordError):
                await asyncpg.connect(wrong.database_url)
        finally:
            await admin.execute("drop role if exists chai_awkward")
            await admin.close()


# --- the shape that caused it must not come back ----------------------------


class TestComposeNeverBuildsAUrlFromThePassword:
    FILES = ("compose.yaml", "compose.dev.yaml")
    # a URL scheme, then anything, then an interpolated password
    INTERPOLATED = re.compile(r"://[^\s#]*\$\{POSTGRES_PASSWORD")

    @pytest.mark.parametrize("name", FILES)
    def test_the_password_is_not_interpolated_into_a_url(self, name: str):
        text = (REPO / name).read_text(encoding="utf-8")
        live = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        assert not self.INTERPOLATED.search(live), (
            f"{name} builds a URL from ${{POSTGRES_PASSWORD}}; compose cannot "
            "percent-encode it, and a '/' in the password breaks the stack"
        )

    def test_the_api_is_handed_the_pieces_instead(self):
        text = (REPO / "compose.yaml").read_text(encoding="utf-8")
        api = text[text.index("\n  api:") : text.index("\n  proxy:")]
        for key in (
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "POSTGRES_USER",
            "POSTGRES_DB",
        ):
            assert key in api, f"the api service is not given {key}"
