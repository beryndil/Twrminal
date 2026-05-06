"""FastAPI app factory.

Builds the :class:`fastapi.FastAPI` instance with everything wired:
middleware, exception handlers, dependency overrides, and routers.

Boot order matters:

1. Validate auth config — refuse to construct the app if auth is
   enabled but the token is empty (Op directive: Zero-Crash).
2. Construct the FastAPI app.
3. Register the request-context middleware FIRST so every later layer
   (handlers, routers) sees the bound ``request_id``.
4. Register exception handlers so a route raising during a request
   produces the canonical envelope, not a stack trace.
5. Bind dependencies — :func:`require_auth` and :func:`get_db` get
   their settings-bound implementations via ``dependency_overrides``.
6. Include routers — health (unauthenticated) and per-resource routers.

Tests construct the app directly via :func:`create_app` and an
:class:`httpx.AsyncClient` against ``app=`` — no live server needed.
"""

import structlog
from fastapi import FastAPI

from bearings import __version__
from bearings.config import Settings
from bearings.errors import ConfigurationError
from bearings.web.auth import build_require_auth, require_auth
from bearings.web.db import build_db_dependency, get_db
from bearings.web.errors import register_exception_handlers
from bearings.web.logging import RequestContextMiddleware
from bearings.web.routers import health, sessions

logger = structlog.get_logger(__name__)


def _validate_auth_config(settings: Settings) -> None:
    """Refuse to build the app if auth is enabled with an empty token.

    Raises :class:`ConfigurationError` so the bootstrap fails fast at
    the boundary instead of silently exposing an unauthenticated API.
    """
    if settings.auth_disabled:
        logger.warning(
            "auth.disabled",
            note=(
                "auth_disabled=True — every API route is reachable without "
                "a token. Intended for tests and dev only."
            ),
        )
        return
    if not settings.auth_token.get_secret_value():
        msg = (
            "auth_token is empty and auth_disabled=False; refusing to boot "
            "an unauthenticated server. Set BEARINGS_AUTH_TOKEN or set "
            "BEARINGS_AUTH_DISABLED=true for local development."
        )
        raise ConfigurationError(msg)


def create_app(settings: Settings) -> FastAPI:
    """Construct and configure the FastAPI application.

    :param settings: fully-loaded :class:`Settings` instance. The
        factory does not call ``Settings()`` itself — the caller owns
        config loading so tests can pass tailored instances.
    """
    _validate_auth_config(settings)

    app = FastAPI(
        title="Bearings",
        version=__version__,
        description="Localhost UI to drive Claude Code agent sessions.",
        # Disable the default 422 response shape — our exception
        # handlers produce the envelope. Keep the OpenAPI docs.
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    # Bind the runtime implementations of the placeholder dependencies.
    # Routers import the placeholders; FastAPI substitutes the bound
    # versions during request resolution.
    app.dependency_overrides[require_auth] = build_require_auth(settings)
    app.dependency_overrides[get_db] = build_db_dependency(settings.db_path)

    app.include_router(health.router)
    app.include_router(sessions.router)

    return app
