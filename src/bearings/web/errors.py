"""HTTP-layer exception handlers.

Translates Python exceptions to a stable JSON envelope so callers
program against one shape regardless of which layer raised. All
responses look like::

    {"error": {"code": "<machine_code>", "message": "<human text>"}}

Design notes:

- ``HTTPException`` (raised by routes/dependencies) — log at info/warning,
  return the envelope with the route's status code. The detail string
  carries the human message; the code is derived from the status code.
- ``RequestValidationError`` (Pydantic 422 from request-body parsing)
  — log at info, return 422 with the per-field detail Pydantic provides.
- ``Exception`` catch-all — Op directive: Zero-Crash. Log full traceback
  via structlog, but return only a generic 500 envelope. Sec rule:
  stack traces never leak to clients — they're an attacker-aided
  reconnaissance gift.

The handlers are registered by :func:`bearings.web.app.create_app`.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)

# Map common HTTP status codes to short machine-readable codes used
# in the error envelope. Anything not in this table falls back to
# ``http_<status>`` (e.g. ``http_418``) so the shape stays predictable.
_STATUS_CODE_NAMES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "unprocessable_entity",
    429: "too_many_requests",
    500: "internal_server_error",
}


def _status_code_name(status_code: int) -> str:
    """Return the canonical machine code for a status code."""
    return _STATUS_CODE_NAMES.get(status_code, f"http_{status_code}")


def _envelope(code: str, message: str, **extra: object) -> dict[str, Any]:
    """Build the canonical ``{"error": {...}}`` JSON envelope.

    ``extra`` is typed as ``object`` (not ``Any``) per ANN401; callers
    pass JSON-serializable values which are accepted polymorphically
    when the dict serializes through Starlette's ``JSONResponse``.
    """
    body: dict[str, Any] = {"code": code, "message": message}
    if extra:
        body.update(extra)
    return {"error": body}


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    """Convert FastAPI/Starlette ``HTTPException`` into the envelope.

    Typed as ``exc: Exception`` to match Starlette's
    :py:meth:`add_exception_handler` signature; we narrow inside.
    """
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover - defensive
        raise exc
    code = _status_code_name(exc.status_code)
    detail = exc.detail if isinstance(exc.detail, str) else "request rejected"
    log_method = (
        logger.warning if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR else logger.info
    )
    log_method(
        "http.request.rejected",
        method=request.method,
        path=request.url.path,
        status_code=exc.status_code,
        code=code,
    )
    headers = exc.headers if exc.headers else None
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(code, detail),
        headers=headers,
    )


async def _handle_validation_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Convert Pydantic validation errors into a 422 envelope.

    The ``errors`` field carries Pydantic's per-field error list so
    clients can render targeted UI messages without parsing free text.
    """
    if not isinstance(exc, RequestValidationError):  # pragma: no cover - defensive
        raise exc
    logger.info(
        "http.request.validation_failed",
        method=request.method,
        path=request.url.path,
        error_count=len(exc.errors()),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_envelope(
            code=_status_code_name(status.HTTP_422_UNPROCESSABLE_ENTITY),
            message="request body failed validation",
            errors=_serialise_validation_errors(exc.errors()),
        ),
    )


# Keys we strip from each per-field error dict before serializing.
# ``ctx`` is dropped because for ``field_validator``-raised ValueErrors
# it carries the live exception instance, which json.dumps can't
# serialize. ``url`` is dropped because the pydantic.dev/errors URL
# isn't actionable for our clients.
_VALIDATION_ERROR_DROP_KEYS: frozenset[str] = frozenset({"ctx", "url"})


def _serialise_validation_errors(
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Strip non-serializable / unhelpful keys from each error dict.

    FastAPI's :py:class:`RequestValidationError` exposes only the
    no-args ``errors()``; we can't ask Pydantic to leave ``ctx`` out
    upstream, so we filter here.
    """
    return [
        {key: value for key, value in entry.items() if key not in _VALIDATION_ERROR_DROP_KEYS}
        for entry in errors
    ]


async def _handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all 500 handler.

    Op directive: Zero-Crash — log every uncaught exception with full
    traceback. Sec rule: never return the traceback to the client.
    """
    logger.error(
        "http.request.unhandled_exception",
        method=request.method,
        path=request.url.path,
        exc_type=type(exc).__name__,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_envelope(
            code=_status_code_name(status.HTTP_500_INTERNAL_SERVER_ERROR),
            message="an internal error occurred; check server logs",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the three handlers above onto *app*.

    Idempotent in practice — FastAPI replaces a handler when one is
    re-registered for the same exception class. Called once by
    :func:`bearings.web.app.create_app`.
    """
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_exception)
