"""The FastAPI application.

Serves the API only. The dashboard itself is static and is served by the proxy
in front (``proxy/Caddyfile``), which is also what terminates SSO -- see
``docs/deploy.md``.

Two defaults here are deliberate and worth not changing by accident:

**CORS is off.** The browser app is served from the same origin as the API, by
the same proxy, so it never makes a cross-origin request. Turning CORS on would
only widen who can call the API from a page they control. ``CORS_ORIGINS`` can
switch it on for a split deployment, and takes an explicit list -- never ``*``,
which with credentials is both insecure and rejected by browsers anyway.

**Cross-site writes are refused.** Identity comes from a proxy that decides
based on its own session, which a browser attaches to cross-site requests too.
``Sec-Fetch-Site`` is checked on every non-GET; see the middleware below.

**No ``--proxy-headers``.** uvicorn's proxy-header handling rewrites the peer
address from ``X-Forwarded-For``, which the client controls. ``TRUSTED_PROXY_CIDR``
in ``app/auth.py`` checks the *real* TCP peer, and that check is only meaningful
while the real peer is what the app sees.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import log_auth_posture
from .config import Settings
from .db import Database
from .events import EventBroker
from .routes import router

log = logging.getLogger("chai")

# Methods that cannot change state, and so need no cross-site check.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
API_CSP = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
HSTS_VALUE = "max-age=31536000; includeSubDomains"


class FixedWindowRateLimiter:
    def __init__(self, window_seconds: int, max_requests: int) -> None:
        self.window_seconds = max(1, window_seconds)
        self.max_requests = max(1, max_requests)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _is_tls(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        proto = forwarded.split(",", 1)[0].strip().lower()
        if proto == "https":
            return True
    return request.url.scheme == "https"


def _rate_limit_key(request: Request, settings: Settings) -> str:
    identity = request.headers.get(settings.identity_header, "").strip()
    if (
        identity
        and settings.identity_strip_prefix
        and identity.startswith(settings.identity_strip_prefix)
    ):
        identity = identity[len(settings.identity_strip_prefix) :]
    if identity:
        return f"id:{identity.lower()}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the pool, migrate, start listening; tear all three down in order."""
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    log.info("CHAI governance API %s starting", settings.version)
    log_auth_posture(settings)

    db = Database(
        settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        connect_timeout=settings.db_connect_timeout,
    )
    await db.connect()
    if settings.run_migrations:
        await db.migrate()
    else:
        log.info("RUN_MIGRATIONS=false: assuming the schema is already current")

    broker = EventBroker(
        db,
        channel=settings.events_channel,
        queue_size=settings.sse_queue_size,
        max_streams_per_user=settings.sse_max_streams_per_user,
    )
    await broker.start()

    app.state.db = db
    app.state.broker = broker
    log.info("ready")
    try:
        yield
    finally:
        log.info("shutting down")
        await broker.stop()
        await db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Taking settings as an argument is what makes it testable."""
    settings = settings or Settings.from_env()

    app = FastAPI(
        title="CHAI governance review API",
        version=settings.version,
        summary=(
            "Shared storage for the CHAI governance dashboard: projects, an "
            "append-only audit log, and a change stream."
        ),
        description=__doc__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    rate_limiter = FixedWindowRateLimiter(
        settings.rate_limit_window_seconds,
        settings.rate_limit_max_requests,
    )

    if settings.cors_origins:
        log.warning(
            "CORS enabled for %s. The app does not need this when it is served "
            "from the same origin as the API.",
            ", ".join(settings.cors_origins),
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
        )

    @app.middleware("http")
    async def api_hardening(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if _is_api_path(path):
            if request.method in BODY_METHODS:
                limit = max(1, settings.request_body_limit_bytes)
                content_length = request.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError:
                        declared = limit + 1
                    if declared > limit:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "detail": (
                                    f"Request body exceeds the {limit}-byte limit."
                                )
                            },
                        )
                else:
                    body = await request.body()
                    if len(body) > limit:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "detail": (
                                    f"Request body exceeds the {limit}-byte limit."
                                )
                            },
                        )

                    async def receive() -> dict[str, object]:
                        return {
                            "type": "http.request",
                            "body": body,
                            "more_body": False,
                        }

                    request._receive = receive

            if request.method != "OPTIONS" and path != "/api/health":
                key = _rate_limit_key(request, settings)
                allowed = await rate_limiter.allow(key)
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        headers={
                            "Retry-After": str(settings.rate_limit_window_seconds)
                        },
                        content={"detail": "Too many requests; please retry shortly."},
                    )

        response = await call_next(request)

        if _is_api_path(path):
            response.headers.setdefault("Content-Security-Policy", API_CSP)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            if _is_tls(request):
                response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
        return response

    @app.middleware("http")
    async def reject_cross_site_writes(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Refuse a state-changing request that a different site initiated.

        Every write here is authenticated by a header the proxy adds, and the
        proxy adds it based on ITS session -- an oauth2-proxy cookie, an Easy
        Auth cookie, an IAP or ALB session. The browser attaches that session
        to a cross-site request just as readily as to a same-site one, so a
        page a signed-in user visits could issue

            fetch('https://governance.hospital.org/api/projects/x',
                  {method: 'DELETE', credentials: 'include'})

        and the API would accept it as them. CORS does not help: it governs
        whether the response can be READ, and a delete does not need to be
        read to have happened.

        ``Sec-Fetch-Site`` is the check. It is set by the browser, cannot be
        altered by script, and says where the request came from. Requests
        without it are allowed through: every browser that has shipped it
        since 2023 sends it on every request, so an absent header means a
        non-browser client -- curl, a health probe, an integration -- which is
        not what a cross-site attack looks like. Blocking those would break
        real callers to defend against nothing.

        ``CSRF_TRUSTED_SITES=cross-site`` relaxes this for a deployment that
        genuinely serves the app from a different origin than the API. That is
        the same deployment that needs ``CORS_ORIGINS``, and both should be
        rare.
        """
        if request.method not in SAFE_METHODS:
            site = request.headers.get("sec-fetch-site")
            if site is not None and site not in settings.csrf_trusted_sites:
                log.warning(
                    "rejected cross-site %s %s (Sec-Fetch-Site: %s)",
                    request.method,
                    request.url.path,
                    site,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Cross-site write rejected. This API only accepts "
                            "state-changing requests from its own origin."
                        )
                    },
                )
        return await call_next(request)

    @app.middleware("http")
    async def mark_auth_mode(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Stamp the auth posture on every response.

        In dev mode this is the header that makes a screenshot of the network
        tab enough to tell that the identity is fake.
        """
        response = await call_next(request)
        response.headers["X-Chai-Auth-Mode"] = settings.auth_mode
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Log the traceback; return a body that does not contain it.

        A stack trace in an API response tells an attacker the file layout, the
        library versions and often the SQL.
        """
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error."}
        )

    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(
        "app.main:app",
        # Settings.bind_host reads the same HOST variable. Going through
        # settings rather than os.getenv here keeps the value that the
        # startup check in config.py reasons about and the value actually
        # bound from drifting apart.
        host=settings.bind_host,
        port=settings.port,
        log_level=settings.log_level,
        # Intentionally no proxy_headers=True: see the module docstring.
        proxy_headers=False,
    )
