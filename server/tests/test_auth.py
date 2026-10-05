"""Identity header handling.

No database: these exercise ``app/auth.py`` through a two-route app, so a
failure points at the auth code rather than at the stack around it.
"""

from __future__ import annotations

import base64
import json
import time

import pytest
from app.auth import Identity
from app.config import IDENTITY_PRESETS, Settings
from app.routes import get_identity
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from .conftest import make_settings


def auth_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings

    @app.get("/api/me")
    async def me(identity: Identity = Depends(get_identity)) -> dict[str, object]:
        return {
            "id": identity.id,
            "name": identity.name,
            "email": identity.email,
            "dev": identity.dev,
        }

    return app


async def call(settings: Settings, headers: dict[str, str] | None = None):
    transport = ASGITransport(app=auth_app(settings))
    async with AsyncClient(transport=transport, base_url="http://api.test") as http:
        return await http.get("/api/me", headers=headers or {})


def jwt(claims: dict[str, object], header: dict[str, object] | None = None) -> str:
    """An unsigned stand-in for ``x-amzn-oidc-data``.

    The signature is not checked, so a placeholder is honest about what the
    plain-trust mode actually verifies -- which is the point of the test below
    that says so out loud.
    """

    def segment(data: dict[str, object]) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{segment(header or {'alg': 'ES256'})}.{segment(claims)}.c2ln"


# --- the default -----------------------------------------------------------


async def test_default_header_is_x_forwarded_email() -> None:
    assert IDENTITY_PRESETS["proxy"].header == "X-Forwarded-Email"
    assert Settings().identity_header == "X-Forwarded-Email"


async def test_identity_comes_from_the_configured_header() -> None:
    response = await call(
        make_settings(),
        {"X-Forwarded-Email": "ann@hospital.example", "X-Forwarded-User": "Ann R"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "ann@hospital.example",
        "name": "Ann R",
        "email": "ann@hospital.example",
        "dev": False,
    }


async def test_missing_header_is_401_not_an_anonymous_user() -> None:
    """The failure mode that matters: no identity must never mean "someone"."""
    response = await call(make_settings())
    assert response.status_code == 401
    assert "X-Forwarded-Email" in response.json()["detail"]


async def test_whitespace_only_header_is_401() -> None:
    response = await call(make_settings(), {"X-Forwarded-Email": "   "})
    assert response.status_code == 401


async def test_the_header_name_is_configurable() -> None:
    settings = make_settings(identity_header="X-Auth-Request-Email")
    assert (
        await call(settings, {"X-Forwarded-Email": "ann@x.example"})
    ).status_code == 401
    ok = await call(settings, {"X-Auth-Request-Email": "ann@x.example"})
    assert ok.status_code == 200
    assert ok.json()["email"] == "ann@x.example"


async def test_auth_header_email_is_accepted_as_an_alias(monkeypatch) -> None:
    """``compose.yaml`` configures the API with the AUTH_HEADER_* spelling."""
    monkeypatch.setenv("AUTH_HEADER_EMAIL", "X-Auth-Request-Email")
    monkeypatch.setenv("AUTH_HEADER_ID", "X-Auth-Request-User")
    monkeypatch.delenv("IDENTITY_HEADER", raising=False)
    monkeypatch.delenv("IDENTITY_ID_HEADER", raising=False)
    settings = Settings.from_env()
    assert settings.identity_header == "X-Auth-Request-Email"
    assert settings.identity_id_header == "X-Auth-Request-User"


# --- per-cloud presets ------------------------------------------------------


async def test_iap_preset_strips_the_accounts_google_com_prefix() -> None:
    """IAP sends ``accounts.google.com:person@example.org``.

    Storing the prefix would put a user id in the audit log that no directory
    lookup can resolve.
    """
    preset = IDENTITY_PRESETS["iap"]
    settings = make_settings(
        identity_mode="iap",
        identity_header=preset.header,
        identity_id_header=preset.id_header,
        identity_name_header="",
        identity_strip_prefix=preset.strip_prefix,
    )
    response = await call(
        settings,
        {
            "X-Goog-Authenticated-User-Email": "accounts.google.com:ann@hospital.example",
            "X-Goog-Authenticated-User-Id": "accounts.google.com:1234567890",
        },
    )
    assert response.status_code == 200
    assert response.json()["email"] == "ann@hospital.example"
    assert response.json()["id"] == "1234567890"


async def test_easyauth_preset_reads_the_azure_principal_headers() -> None:
    preset = IDENTITY_PRESETS["easyauth"]
    settings = make_settings(
        identity_mode="easyauth",
        identity_header=preset.header,
        identity_id_header=preset.id_header,
        identity_name_header="",
    )
    response = await call(
        settings,
        {
            "X-MS-CLIENT-PRINCIPAL-NAME": "ann@hospital.example",
            "X-MS-CLIENT-PRINCIPAL-ID": "9f1c-aaaa",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "9f1c-aaaa",
        "name": "ann@hospital.example",
        "email": "ann@hospital.example",
        "dev": False,
    }


def alb_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "identity_mode": "alb",
        "identity_header": "x-amzn-oidc-data",
        "identity_header_format": "jwt",
        "identity_name_header": "",
    }
    base.update(overrides)
    return make_settings(**base)


async def test_alb_preset_reads_claims_out_of_the_signed_assertion() -> None:
    """``x-amzn-oidc-identity`` is only the opaque ``sub``; the email is in the JWT."""
    token = jwt({"sub": "aws-sub-1", "email": "ann@hospital.example", "name": "Ann R"})
    response = await call(alb_settings(), {"x-amzn-oidc-data": token})
    assert response.status_code == 200
    assert response.json() == {
        "id": "aws-sub-1",
        "name": "Ann R",
        "email": "ann@hospital.example",
        "dev": False,
    }


async def test_alb_falls_back_to_sub_when_there_is_no_email_claim() -> None:
    token = jwt({"sub": "aws-sub-1"})
    response = await call(alb_settings(), {"x-amzn-oidc-data": token})
    assert response.status_code == 200
    assert response.json()["email"] == "aws-sub-1"


async def test_unreadable_assertion_is_401() -> None:
    response = await call(alb_settings(), {"x-amzn-oidc-data": "not-a-jwt"})
    assert response.status_code == 401


async def test_expired_assertion_is_rejected() -> None:
    token = jwt({"sub": "s", "email": "a@b.example", "exp": int(time.time()) - 60})
    response = await call(alb_settings(), {"x-amzn-oidc-data": token})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


async def test_audience_mismatch_is_rejected() -> None:
    settings = alb_settings(identity_audience="arn:aws:elasticloadbalancing:ours")
    wrong = jwt({"sub": "s", "email": "a@b.example"}, {"signer": "arn:aws:...theirs"})
    assert (await call(settings, {"x-amzn-oidc-data": wrong})).status_code == 401

    right = jwt(
        {"sub": "s", "email": "a@b.example"},
        {"signer": "arn:aws:elasticloadbalancing:ours"},
    )
    assert (await call(settings, {"x-amzn-oidc-data": right})).status_code == 200


async def test_audience_check_accepts_an_aud_claim_too() -> None:
    """IAP and Entra ID put the audience in ``aud``, not in a header field."""
    settings = alb_settings(identity_audience="/projects/42/services/chai-api")
    token = jwt(
        {"sub": "s", "email": "a@b.example", "aud": "/projects/42/services/chai-api"}
    )
    assert (await call(settings, {"x-amzn-oidc-data": token})).status_code == 200


# --- the second locks -------------------------------------------------------


async def test_shared_secret_blocks_a_request_that_skipped_the_proxy() -> None:
    settings = make_settings(proxy_shared_secret="s3cret")
    forged = {"X-Forwarded-Email": "ceo@hospital.example"}
    assert (await call(settings, forged)).status_code == 403
    allowed = {**forged, "X-Proxy-Secret": "s3cret"}
    assert (await call(settings, allowed)).status_code == 200


async def test_shared_secret_rejects_a_wrong_value() -> None:
    settings = make_settings(proxy_shared_secret="s3cret")
    response = await call(
        settings,
        {"X-Forwarded-Email": "ceo@hospital.example", "X-Proxy-Secret": "guess"},
    )
    assert response.status_code == 403


async def test_trusted_proxy_cidr_rejects_an_outside_peer() -> None:
    """ASGITransport reports the peer as 127.0.0.1."""
    settings = make_settings(trusted_proxy_cidrs=["10.0.0.0/8"])
    response = await call(settings, {"X-Forwarded-Email": "ann@hospital.example"})
    assert response.status_code == 403

    settings = make_settings(trusted_proxy_cidrs=["127.0.0.0/8", "10.0.0.0/8"])
    response = await call(settings, {"X-Forwarded-Email": "ann@hospital.example"})
    assert response.status_code == 200


async def test_x_forwarded_for_cannot_satisfy_the_peer_check() -> None:
    """The check must look at the TCP peer, not at a header the client sets.

    This is why the container does not run uvicorn with ``--proxy-headers``.
    """
    settings = make_settings(trusted_proxy_cidrs=["10.0.0.0/8"])
    response = await call(
        settings,
        {"X-Forwarded-Email": "ann@hospital.example", "X-Forwarded-For": "10.1.2.3"},
    )
    assert response.status_code == 403


# --- dev mode ---------------------------------------------------------------


async def test_dev_mode_injects_a_fixed_identity_and_says_so() -> None:
    settings = make_settings(
        dev_insecure_auth=True,
        dev_identity_email="dev@localhost",
        dev_identity_name="Local Dev (INSECURE)",
    )
    response = await call(settings)  # no headers at all
    assert response.status_code == 200
    assert response.json() == {
        "id": "dev@localhost",
        "name": "Local Dev (INSECURE)",
        "email": "dev@localhost",
        "dev": True,
    }


async def test_dev_mode_ignores_a_supplied_header() -> None:
    """Dev mode is fixed, not "whatever you send". It cannot be used to switch users."""
    settings = make_settings(dev_insecure_auth=True)
    response = await call(settings, {"X-Forwarded-Email": "ceo@hospital.example"})
    assert response.json()["email"] == "dev@localhost"


async def test_dev_mode_is_off_by_default() -> None:
    assert Settings().dev_insecure_auth is False
    assert Settings.from_env().dev_insecure_auth is False


def test_auth_mode_string_names_the_danger() -> None:
    """``/api/health`` and every response header carry this string."""
    assert make_settings(dev_insecure_auth=True).auth_mode == "DEV-INSECURE"
    assert make_settings().auth_mode == "proxy-header:proxy"
    assert "anonymous" in make_settings(require_identity=False).auth_mode


async def test_require_identity_false_degrades_to_anonymous() -> None:
    settings = make_settings(require_identity=False)
    response = await call(settings)
    assert response.status_code == 200
    assert response.json()["id"] == "anonymous"


def test_unknown_identity_mode_fails_at_startup(monkeypatch) -> None:
    """Better a container that refuses to start than one trusting the wrong header."""
    monkeypatch.setenv("IDENTITY_MODE", "gcp")
    with pytest.raises(RuntimeError, match="IDENTITY_MODE"):
        Settings.from_env()
