"""Runtime configuration, read once from the environment at startup.

Every knob is an environment variable, because the three clouds this is meant
to run on -- Google Cloud, AWS and Azure -- all inject configuration that way,
and all three send a *different* identity header.

Two ways to say the same thing:

``IDENTITY_MODE``
    A preset: ``iap``, ``alb``, ``easyauth``, or ``proxy`` (the default). Picks
    the header name, the value format and any prefix to strip. This is what
    ``docs/deploy.md`` sets.

``IDENTITY_HEADER`` and friends
    Explicit overrides, for a proxy none of the presets covers -- nginx with
    oauth2-proxy, Cloudflare Access, a hospital's own gateway. Anything set
    explicitly wins over the preset.

``IDENTITY_HEADER`` defaults to ``X-Forwarded-Email``, the de-facto name used
by oauth2-proxy and most nginx auth_request setups.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_IDENTITY_HEADER = "X-Forwarded-Email"


@dataclass(frozen=True)
class IdentityPreset:
    """Which headers one front door sets, and how to read them."""

    header: str
    fmt: str = "plain"  # "plain" | "jwt"
    name_header: str = ""
    id_header: str = ""
    strip_prefix: str = ""
    description: str = ""


IDENTITY_PRESETS: dict[str, IdentityPreset] = {
    # Generic reverse proxy: oauth2-proxy, nginx auth_request, Cloudflare
    # Access with a transform rule, a hospital gateway.
    "proxy": IdentityPreset(
        header=DEFAULT_IDENTITY_HEADER,
        name_header="X-Forwarded-User",
        description="generic reverse proxy",
    ),
    # Google Cloud Identity-Aware Proxy. The value is prefixed with the
    # issuer: "accounts.google.com:person@example.org". Code that forgets to
    # strip that prefix stores a user id nobody can match to a directory.
    "iap": IdentityPreset(
        header="X-Goog-Authenticated-User-Email",
        id_header="X-Goog-Authenticated-User-Id",
        strip_prefix="accounts.google.com:",
        description="Google Cloud Identity-Aware Proxy",
    ),
    # AWS Application Load Balancer with an authenticate-oidc listener rule.
    # x-amzn-oidc-identity carries only the opaque `sub`, so read the claims
    # out of x-amzn-oidc-data instead -- that is where the email lives.
    "alb": IdentityPreset(
        header="x-amzn-oidc-data",
        fmt="jwt",
        description="AWS ALB authenticate-oidc",
    ),
    # Azure App Service / Container Apps built-in authentication ("Easy Auth").
    # Easy Auth strips any client-supplied copy of these headers before it
    # forwards, which is one fewer thing to get wrong.
    "easyauth": IdentityPreset(
        header="X-MS-CLIENT-PRINCIPAL-NAME",
        id_header="X-MS-CLIENT-PRINCIPAL-ID",
        description="Azure Easy Auth",
    ),
}


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _alias(primary: str, alias: str, default: str = "") -> str:
    """First of two spellings that is set.

    The repository's Docker Compose stack puts Caddy in front and normalizes
    every cloud's header into ``X-Auth-Request-*``, so it configures the API
    with ``AUTH_HEADER_EMAIL`` and friends. Accepting both spellings means the
    same image runs under compose and under a raw cloud front door without a
    wrapper script translating variables.
    """
    value = os.getenv(primary)
    if value is not None and value.strip():
        return value.strip()
    value = os.getenv(alias)
    if value is not None and value.strip():
        return value.strip()
    return default


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - startup failure
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


def _csv(name: str) -> list[str]:
    return [part.strip() for part in _str(name).split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the environment."""

    # --- database ---------------------------------------------------------
    database_url: str = ""
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_connect_timeout: float = 10.0
    run_migrations: bool = True

    # --- identity ---------------------------------------------------------
    identity_mode: str = "proxy"
    identity_header: str = DEFAULT_IDENTITY_HEADER
    identity_name_header: str = "X-Forwarded-User"
    identity_id_header: str = ""
    identity_strip_prefix: str = ""
    identity_header_format: str = "plain"
    identity_audience: str = ""
    identity_jwt_email_claim: str = "email"
    identity_jwt_name_claim: str = "name"
    identity_jwt_id_claim: str = "sub"

    # --- dev-only escape hatch -------------------------------------------
    dev_insecure_auth: bool = False
    dev_identity_email: str = "dev@localhost"
    dev_identity_name: str = "Local Dev (INSECURE)"

    require_identity: bool = True

    # --- transport --------------------------------------------------------
    cors_origins: list[str] = field(default_factory=list)
    proxy_shared_secret: str = ""
    proxy_secret_header: str = "X-Proxy-Secret"
    trusted_proxy_cidrs: list[str] = field(default_factory=list)
    log_level: str = "info"
    port: int = 8000

    # --- events -----------------------------------------------------------
    events_channel: str = "chai_events"
    sse_keepalive_seconds: float = 15.0
    sse_queue_size: int = 256

    # --- misc -------------------------------------------------------------
    version: str = "0.1.0"
    log_page_size: int = 60

    @property
    def auth_mode(self) -> str:
        """One short string for ``/api/health`` and the startup log."""
        if self.dev_insecure_auth:
            return "DEV-INSECURE"
        if not self.require_identity:
            return f"proxy-header:{self.identity_mode}:anonymous-allowed"
        return f"proxy-header:{self.identity_mode}"

    def _reject_silent_misconfiguration(self) -> None:
        """Refuse to start on settings that would be ignored without a word.

        IDENTITY_AUDIENCE is only ever read while decoding a JWT. Set it
        alongside a `plain` header format -- which is what IDENTITY_MODE=iap
        and IDENTITY_MODE=easyauth select -- and it does nothing at all, while
        looking in the deployment config exactly like an audience check is in
        force. An operator who believes their deployment is pinned to one
        service, and is not, is worse off than one who knows it is not pinned.
        So this is fatal rather than a warning: a misconfiguration that only
        weakens security is precisely the kind that survives in production.
        """
        if self.identity_audience and self.identity_header_format != "jwt":
            raise RuntimeError(
                "IDENTITY_AUDIENCE is set but IDENTITY_HEADER_FORMAT is "
                f"{self.identity_header_format!r}, so the audience is never "
                "checked. Either set IDENTITY_HEADER_FORMAT=jwt with a header "
                "that carries a signed assertion (x-goog-iap-jwt-assertion, "
                "x-amzn-oidc-data, X-MS-TOKEN-AAD-ID-TOKEN), or unset "
                "IDENTITY_AUDIENCE. See docs/deploy.md."
            )

    @classmethod
    def from_env(cls) -> Settings:
        mode = _str("IDENTITY_MODE", "proxy").lower()
        if mode not in IDENTITY_PRESETS:
            known = ", ".join(sorted(IDENTITY_PRESETS))
            raise RuntimeError(f"IDENTITY_MODE must be one of: {known} (got {mode!r})")
        preset = IDENTITY_PRESETS[mode]

        fmt = _str("IDENTITY_HEADER_FORMAT", preset.fmt).lower()
        if fmt not in {"plain", "jwt"}:
            raise RuntimeError(
                f"IDENTITY_HEADER_FORMAT must be 'plain' or 'jwt', got {fmt!r}"
            )

        settings = cls(
            database_url=_str("DATABASE_URL"),
            db_pool_min=_int("DB_POOL_MIN", 1),
            db_pool_max=_int("DB_POOL_MAX", 10),
            db_connect_timeout=float(_int("DB_CONNECT_TIMEOUT", 10)),
            run_migrations=_bool("RUN_MIGRATIONS", True),
            identity_mode=mode,
            identity_header=_alias(
                "IDENTITY_HEADER", "AUTH_HEADER_EMAIL", preset.header
            ),
            identity_name_header=_alias(
                "IDENTITY_NAME_HEADER", "AUTH_HEADER_NAME", preset.name_header
            ),
            identity_id_header=_alias(
                "IDENTITY_ID_HEADER", "AUTH_HEADER_ID", preset.id_header
            ),
            identity_strip_prefix=_str("IDENTITY_STRIP_PREFIX", preset.strip_prefix),
            identity_header_format=fmt,
            identity_audience=_str("IDENTITY_AUDIENCE"),
            identity_jwt_email_claim=_str("IDENTITY_JWT_EMAIL_CLAIM", "email"),
            identity_jwt_name_claim=_str("IDENTITY_JWT_NAME_CLAIM", "name"),
            identity_jwt_id_claim=_str("IDENTITY_JWT_ID_CLAIM", "sub"),
            dev_insecure_auth=_bool("DEV_INSECURE_AUTH", False),
            dev_identity_email=_alias(
                "DEV_IDENTITY_EMAIL", "DEV_IDENTITY_ID", "dev@localhost"
            ),
            dev_identity_name=_str("DEV_IDENTITY_NAME", "Local Dev (INSECURE)"),
            require_identity=_bool("REQUIRE_IDENTITY", True),
            cors_origins=_csv("CORS_ORIGINS"),
            proxy_shared_secret=_str("PROXY_SHARED_SECRET"),
            proxy_secret_header=_str("PROXY_SECRET_HEADER", "X-Proxy-Secret"),
            trusted_proxy_cidrs=_csv("TRUSTED_PROXY_CIDR"),
            log_level=_str("LOG_LEVEL", "info").lower(),
            port=_int("PORT", _int("API_PORT", 8000)),
            events_channel=_str("EVENTS_CHANNEL", "chai_events"),
            sse_keepalive_seconds=float(_int("SSE_KEEPALIVE_SECONDS", 15)),
            sse_queue_size=_int("SSE_QUEUE_SIZE", 256),
            version=_str("APP_VERSION", "0.1.0"),
            log_page_size=_int("LOG_PAGE_SIZE", 60),
        )
        settings._reject_silent_misconfiguration()
        return settings
