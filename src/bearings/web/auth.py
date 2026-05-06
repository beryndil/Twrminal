"""Shared-token authentication.

Stack pin §3 — v1 auth is a single shared bearer token sent on every
authenticated request via the configurable ``auth_header_name``
(default ``X-Bearings-Token``). NOT JWT, NOT OAuth2, NOT cookies.

The dependency is wired by :func:`bearings.web.app.create_app`, which
binds the configured token + header name + disabled-flag once at app
construction time. Routers don't see config — they just declare the
dependency:

    @router.get("/api/sessions")
    async def list_sessions(_auth: None = Depends(require_auth)) -> ...:
        ...

``_auth`` is named with a leading underscore to signal "this dependency
exists for its side-effect (gating)"; the value itself is unused.

Why ``secrets.compare_digest`` and not ``==``?
:py:func:`secrets.compare_digest` runs in time proportional to the
input length but does NOT short-circuit on the first mismatched byte.
A naive ``==`` leaks the prefix length of the correct token via
response timing — recoverable over enough samples even on localhost.
The cost is one C-level fixed-time compare; the defense is free.
"""

import secrets
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from bearings.config import Settings


def build_require_auth(settings: Settings) -> Callable[[Request], Awaitable[None]]:
    """Build the FastAPI dependency callable bound to *settings*.

    Returns an async function suitable for use with ``Depends(...)``.
    The returned callable closes over the configured header name and
    expected token, so routers don't pass config around — they just
    declare the dependency they're given by the app factory.

    Construction-time gates:

    - If ``settings.auth_disabled is True`` and the token is empty:
      return a no-op dependency. The app factory logs a structured
      warning at boot so this is never silent.
    - Otherwise: the token must be non-empty (validated at app-factory
      time, not here — keeps this function pure-runtime).

    Runtime gate (per request): missing / empty / mismatched token →
    401 with the stable error envelope shape produced by
    :mod:`bearings.web.errors`.
    """
    header_scheme = APIKeyHeader(name=settings.auth_header_name, auto_error=False)
    expected_token = settings.auth_token.get_secret_value()
    auth_disabled = settings.auth_disabled

    # ``Depends(header_scheme)`` declared once and reused below; the
    # framework sees one dependency callable, FastAPI dedupes it per
    # request. Closing over it keeps the inner function signature small.
    async def _require_auth(
        _request: Request,
        provided: str | None = Depends(header_scheme),
    ) -> None:
        if auth_disabled:
            return
        if not provided or not secrets.compare_digest(provided, expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid authentication token",
            )

    return _require_auth


# Module-level placeholder so type-checkers and static analyzers can
# reference ``require_auth`` from imports. The real callable is built
# by ``create_app`` and dependency-overridden into the FastAPI app.
# Calling this raises explicitly so a forgotten override is loud, not
# silently permissive.
async def require_auth() -> None:
    """Sentinel dependency replaced by :func:`build_require_auth` output.

    Raised explicitly because reaching this means the app factory
    forgot to wire :func:`build_require_auth` into
    ``app.dependency_overrides``. That's a developer error worth
    failing fast on, not a 401-without-comment to the caller.
    """
    msg = (
        "require_auth was called without being overridden by create_app(); "
        "the FastAPI app was built incorrectly."
    )
    raise RuntimeError(msg)
