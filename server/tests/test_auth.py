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


async def test_iap_behind_caddy_strips_the_prefix_from_canonical_headers() -> None:
    """The topology compose.yaml actually deploys, which is not the one above.

    With Caddy in front, the API does NOT read X-Goog-* -- Caddy normalizes
    every front door into X-Auth-Request-*. So IDENTITY_MODE stays unset (the
    `proxy` preset) and the prefix has to arrive from IDENTITY_STRIP_PREFIX
    instead of from a preset.

    That combination is what a Google Cloud deployment of this repository
    runs, and it was untested: the preset test above passes with
    IDENTITY_STRIP_PREFIX doing nothing at all, because the preset supplies
    the prefix itself. compose.yaml also did not pass the variable through
    until recently, so the live behavior was "prefix retained" while the
    suite was green.

    Retaining it puts `accounts.google.com:1234` in every access list and
    every sign-off -- an id no directory lookup resolves.
    """
    settings = make_settings(
        identity_mode="proxy",
        identity_header="X-Auth-Request-Email",
        identity_id_header="X-Auth-Request-User",
        identity_name_header="X-Auth-Request-Name",
        identity_strip_prefix="accounts.google.com:",
    )
    response = await call(
        settings,
        {
            "X-Auth-Request-Email": "accounts.google.com:ann@hospital.example",
            "X-Auth-Request-User": "accounts.google.com:1234567890",
            "X-Auth-Request-Name": "accounts.google.com:ann@hospital.example",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "ann@hospital.example"
    assert body["id"] == "1234567890"
    assert body["name"] == "ann@hospital.example"
    assert "accounts.google.com" not in str(body), body


async def test_an_unset_strip_prefix_leaves_the_value_alone() -> None:
    """Every front door other than IAP sends an unprefixed value."""
    settings = make_settings(
        identity_mode="proxy",
        identity_header="X-Auth-Request-Email",
        identity_id_header="X-Auth-Request-User",
    )
    response = await call(
        settings,
        {
            "X-Auth-Request-Email": "ann@hospital.example",
            "X-Auth-Request-User": "entra-oid-999",
        },
    )
    assert response.json()["email"] == "ann@hospital.example"
    assert response.json()["id"] == "entra-oid-999"


async def test_the_strip_prefix_is_not_a_substring_match() -> None:
    """Only a LEADING prefix is removed.

    An address that merely contains the prefix text, or a different issuer,
    must survive intact rather than be silently rewritten.
    """
    settings = make_settings(
        identity_mode="proxy",
        identity_header="X-Auth-Request-Email",
        identity_strip_prefix="accounts.google.com:",
    )
    for value in (
        "ann+accounts.google.com:tag@hospital.example",
        "accounts.google.com.evil.test:ann@hospital.example",
    ):
        response = await call(settings, {"X-Auth-Request-Email": value})
        assert response.json()["email"] == value, value


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


class TestInsecureAuthIsGuarded:
    """A log line is not a guard.

    DEV_INSECURE_AUTH authenticates every request as one fixed user;
    REQUIRE_IDENTITY=false turns off access control for everyone. Both used to
    be guarded only by a startup warning, so one stale variable in a task
    definition was a full compromise. They are now refused unless the process
    binds loopback or a second, differently-named variable says so too.
    """

    def _from_env(self, monkeypatch, **env: str) -> Settings:
        for key in (
            "DEV_INSECURE_AUTH",
            "REQUIRE_IDENTITY",
            "I_UNDERSTAND_THIS_IS_INSECURE",
            "HOST",
            "IDENTITY_MODE",
            "IDENTITY_AUDIENCE",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return Settings.from_env()

    def test_dev_auth_off_loopback_is_refused(self, monkeypatch):
        with pytest.raises(RuntimeError, match="Refusing to start"):
            self._from_env(monkeypatch, DEV_INSECURE_AUTH="1", HOST="0.0.0.0")

    def test_anonymous_access_off_loopback_is_refused(self, monkeypatch):
        with pytest.raises(RuntimeError, match="Refusing to start"):
            self._from_env(monkeypatch, REQUIRE_IDENTITY="false", HOST="0.0.0.0")

    def test_the_message_names_the_variable_and_the_way_out(self, monkeypatch):
        with pytest.raises(RuntimeError) as exc:
            self._from_env(monkeypatch, DEV_INSECURE_AUTH="1", HOST="0.0.0.0")
        text = str(exc.value)
        assert "DEV_INSECURE_AUTH" in text
        assert "HOST=127.0.0.1" in text
        assert "I_UNDERSTAND_THIS_IS_INSECURE" in text

    def test_dev_auth_on_loopback_is_allowed(self, monkeypatch):
        settings = self._from_env(monkeypatch, DEV_INSECURE_AUTH="1", HOST="127.0.0.1")
        assert settings.dev_insecure_auth
        assert settings.auth_mode == "DEV-INSECURE"

    def test_an_explicit_acknowledgment_is_honored(self, monkeypatch):
        settings = self._from_env(
            monkeypatch,
            DEV_INSECURE_AUTH="1",
            HOST="0.0.0.0",
            I_UNDERSTAND_THIS_IS_INSECURE="1",
        )
        assert settings.dev_insecure_auth

    def test_a_normal_deployment_is_unaffected(self, monkeypatch):
        settings = self._from_env(monkeypatch, HOST="0.0.0.0")
        assert settings.require_identity
        assert not settings.dev_insecure_auth


class TestNetworkLocksApplyInDevMode:
    """DEV_INSECURE_AUTH should weaken one layer, not all three.

    The dev short-circuit used to return before _check_peer and
    _check_shared_secret ran, so setting it also disabled TRUSTED_PROXY_CIDR
    and PROXY_SHARED_SECRET -- the two controls documented as defense in depth
    for exactly this situation.
    """

    async def test_the_shared_secret_is_still_required(self):
        response = await call(
            make_settings(dev_insecure_auth=True, proxy_shared_secret="s3kr1t")
        )
        assert response.status_code == 403

    async def test_a_correct_shared_secret_still_gets_the_dev_identity(self):
        response = await call(
            make_settings(dev_insecure_auth=True, proxy_shared_secret="s3kr1t"),
            headers={"X-Proxy-Secret": "s3kr1t"},
        )
        assert response.status_code == 200
        assert response.json()["dev"] is True

    async def test_without_a_shared_secret_dev_mode_is_unchanged(self):
        response = await call(make_settings(dev_insecure_auth=True))
        assert response.status_code == 200
        assert response.json()["dev"] is True


class TestAlbAudienceIsTheLoadBalancerArn:
    """An ALB signs with its load balancer ARN, never its listener's (#51).

    ``x-amzn-oidc-data`` carries the ARN in the token header's ``signer``, and
    that is a ``loadbalancer/`` ARN. The deployment guide told operators to
    paste a ``listener/`` ARN, which can never match, so every request was a 401
    that looks like an SSO fault. Worse, an operator who concludes the audience
    check is broken leaves it unset, which turns off the one check that catches
    a token minted for another service.
    """

    LOAD_BALANCER = (
        "arn:aws:elasticloadbalancing:us-east-1:1234:loadbalancer/app/chai/a"
    )
    LISTENER = "arn:aws:elasticloadbalancing:us-east-1:1234:listener/app/chai/a/b"

    def _from_env(self, monkeypatch, audience: str) -> Settings:
        for key in ("DEV_INSECURE_AUTH", "REQUIRE_IDENTITY", "HOST"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("IDENTITY_MODE", "alb")
        monkeypatch.setenv("IDENTITY_AUDIENCE", audience)
        return Settings.from_env()

    def test_a_listener_arn_is_refused_at_startup(self, monkeypatch):
        with pytest.raises(RuntimeError, match="load balancer") as exc:
            self._from_env(monkeypatch, self.LISTENER)
        assert "listener" in str(exc.value)

    def test_a_listener_rule_arn_is_refused_too(self, monkeypatch):
        rule = self.LISTENER.replace("listener/", "listener-rule/")
        with pytest.raises(RuntimeError, match="load balancer"):
            self._from_env(monkeypatch, rule)

    def test_the_load_balancer_arn_starts(self, monkeypatch):
        settings = self._from_env(monkeypatch, self.LOAD_BALANCER)
        assert settings.identity_audience == self.LOAD_BALANCER

    async def test_the_load_balancer_arn_is_what_the_alb_signs(self):
        """End to end through the decoder: the signer matches, so it is accepted."""
        settings = alb_settings(identity_audience=self.LOAD_BALANCER)
        token = jwt(
            {"sub": "s", "email": "a@b.example"}, {"signer": self.LOAD_BALANCER}
        )
        assert (await call(settings, {"x-amzn-oidc-data": token})).status_code == 200

    def test_every_arn_the_docs_show_for_the_audience_starts(self, monkeypatch):
        """The guide's own example must not be one the API refuses (#51, as #62)."""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        shown = []
        for doc in [root / "README.md", *sorted((root / "docs").glob("*.md"))]:
            text = doc.read_text(encoding="utf-8")
            shown += re.findall(
                r'"name":\s*"IDENTITY_AUDIENCE",\s*"value":\s*"(arn:[^"]+)"', text
            )
            shown += re.findall(r"IDENTITY_AUDIENCE=(arn:\S+)", text)
        assert shown, "the docs show no AWS IDENTITY_AUDIENCE; this scan checks nothing"
        for arn in shown:
            self._from_env(monkeypatch, arn)
