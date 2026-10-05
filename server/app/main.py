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

**No ``--proxy-headers``.** uvicorn's proxy-header handling rewrites the peer
address from ``X-Forwarded-For``, which the client controls. ``TRUSTED_PROXY_CIDR``
in ``app/auth.py`` checks the *real* TCP peer, and that check is only meaningful
while the real peer is what the app sees.
"""

from __future__ import annotations

import logging
import os
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
        db, channel=settings.events_channel, queue_size=settings.sse_queue_size
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
        host=os.getenv("HOST", "0.0.0.0"),
        port=settings.port,
        log_level=settings.log_level,
        # Intentionally no proxy_headers=True: see the module docstring.
        proxy_headers=False,
    )
