"""How the API learns which database role to serve as (#48).

No database needed: this is about reading the environment. The compose stack passes
the API ONLY the restricted role's credential, so a compromised API has no owner
password to find; the owner's lives in the one-shot migrate job.
"""

from __future__ import annotations

import pytest
from app.config import Settings, build_app_database_url, build_database_url
from app.roles import DbRole
from httpx import AsyncClient

from .conftest import APP_ROLE_MODE, APP_ROLE_URL, DB_URL, make_settings, requires_db

OWNER_ENV = {
    "POSTGRES_USER": "chai",
    "POSTGRES_PASSWORD": "owner-pw",
    "POSTGRES_HOST": "db",
    "POSTGRES_DB": "chai",
}


def test_no_app_credential_means_no_app_url() -> None:
    assert build_app_database_url(OWNER_ENV) == ""


def test_the_app_url_uses_its_own_user_and_password_and_the_same_database() -> None:
    url = build_app_database_url(
        {**OWNER_ENV, "APP_POSTGRES_PASSWORD": "app-pw/with+awkward=chars"}
    )
    assert url.startswith("postgresql://chai_app:")
    assert "owner-pw" not in url
    assert "app-pw%2Fwith%2Bawkward%3Dchars" in url, "percent-encoded, like the owner's"
    assert url.endswith("@db:5432/chai")


def test_the_app_user_name_is_configurable() -> None:
    url = build_app_database_url(
        {**OWNER_ENV, "APP_POSTGRES_USER": "gov_api", "APP_POSTGRES_PASSWORD": "x" * 20}
    )
    assert url.startswith("postgresql://gov_api:")


def test_an_explicit_app_url_wins_and_is_checked() -> None:
    explicit = "postgresql://api:s3cret@managed.example:5432/gov?sslmode=verify-full"
    assert (
        build_app_database_url({"APP_DATABASE_URL": explicit, **OWNER_ENV}) == explicit
    )
    with pytest.raises(RuntimeError, match="APP_DATABASE_URL is not a valid URL"):
        build_app_database_url({"APP_DATABASE_URL": "postgresql://u:p/w@h/db"})


def test_a_bad_app_url_error_does_not_echo_the_password() -> None:
    with pytest.raises(RuntimeError) as raised:
        build_app_database_url({"APP_DATABASE_URL": "postgresql://u:hunter2/x@h/db"})
    assert "hunter2" not in str(raised.value)


def test_the_api_serves_as_the_restricted_role_when_it_has_one() -> None:
    settings = Settings(
        database_url="postgresql://owner:o@db/chai",
        app_database_url="postgresql://chai_app:a@db/chai",
        run_migrations=False,
    )
    assert settings.serving_database_url.startswith("postgresql://chai_app:")


def test_without_one_it_serves_as_it_always_did() -> None:
    settings = Settings(database_url="postgresql://owner:o@db/chai")
    assert settings.serving_database_url == "postgresql://owner:o@db/chai"


def test_the_compose_api_environment_has_no_owner_credential(monkeypatch) -> None:
    """The shape compose gives the API: pieces for the app role, nothing of the owner."""
    for key in ("DATABASE_URL", "POSTGRES_PASSWORD", "APP_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_DB", "chai")
    monkeypatch.setenv("APP_POSTGRES_PASSWORD", "app-pw-0123456789")
    monkeypatch.setenv("RUN_MIGRATIONS", "false")
    settings = Settings.from_env()
    assert settings.database_url == "", "no owner URL can be built, so none exists"
    assert settings.app_database_url.startswith("postgresql://chai_app:")
    assert build_database_url({"POSTGRES_HOST": "db"}) == ""


def test_a_restricted_process_told_to_migrate_is_refused_with_the_fix(
    monkeypatch,
) -> None:
    """It cannot create tables, and the permission error it would hit says nothing."""
    monkeypatch.setenv("APP_POSTGRES_PASSWORD", "app-pw-0123456789")
    monkeypatch.delenv("RUN_MIGRATIONS", raising=False)  # the default is true
    with pytest.raises(RuntimeError) as raised:
        Settings.from_env()
    message = str(raised.value)
    assert "RUN_MIGRATIONS=false" in message and "python -m app.migrate" in message


@requires_db
async def test_health_says_which_role_the_api_serves_as(client: AsyncClient) -> None:
    body = (await client.get("/api/health")).json()
    expected = DbRole.RESTRICTED if APP_ROLE_MODE else DbRole.OWNER
    assert body["db_role"] == expected.value


async def _started(settings: Settings, caplog: pytest.LogCaptureFixture):
    """Start an app, return (health body, the warnings it logged while starting)."""
    from app.main import create_app
    from httpx import ASGITransport

    caplog.clear()
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://api.test"
        ) as http:
            body = (await http.get("/api/health")).json()
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    return body, warnings


@requires_db
async def test_serving_as_the_owner_is_reported_and_warned_about(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    body, warnings = await _started(
        make_settings(database_url=DB_URL, app_database_url="", run_migrations=True),
        caplog,
    )
    assert body["db_role"] == "owner"
    assert any("serving as the database OWNER" in w for w in warnings), warnings


@requires_db
async def test_serving_as_the_restricted_role_is_reported_and_not_warned_about(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    body, warnings = await _started(
        make_settings(
            database_url="", app_database_url=APP_ROLE_URL, run_migrations=False
        ),
        caplog,
    )
    assert body["db_role"] == "restricted"
    assert not [w for w in warnings if "OWNER" in w], warnings
