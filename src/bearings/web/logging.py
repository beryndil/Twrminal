"""Request-context logging middleware.

Concept: structlog's :mod:`structlog.contextvars` module backs a
context-local dict that any logger.info/error/etc. picks up via the
``merge_contextvars`` processor (already in §7's pipeline). Binding
``request_id`` here means every event emitted *during* the request —
in routers, services, query modules — automatically carries the
request_id, with no per-call plumbing.

Two events bracket each request:

- ``http.request.start`` — method, path, client_ip.
- ``http.request.finish`` — status_code, duration_ms.

This is the operational-event channel from coding-standards.md
(programmer / operational / user-caused split). Validation failures,
auth rejections, and uncaught exceptions log their own events from
:mod:`bearings.web.errors`.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a fresh ``request_id`` per request and log start/finish."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Wrap the downstream handler with structured logging context."""
        # ``clear_contextvars`` defends against context-leak between
        # requests on the same task; under uvicorn each request runs on
        # its own task, but middleware reuse and test runners can blur
        # that boundary, so an explicit clear costs nothing.
        structlog.contextvars.clear_contextvars()
        request_id = uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)

        client_ip = request.client.host if request.client else None
        logger.info(
            "http.request.start",
            method=request.method,
            path=request.url.path,
            client_ip=client_ip,
        )

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The catch-all in errors.py logs the exception. We don't
            # log a duplicate here, but we do measure duration so the
            # 500 path stays observable. ``raise`` propagates to the
            # exception handler which renders the 500 envelope.
            duration_ms = (time.perf_counter() - start) * 1000.0
            logger.warning(
                "http.request.finish",
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=round(duration_ms, 2),
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000.0
        logger.info(
            "http.request.finish",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        # Surface request_id back to the client for log-correlation
        # support — debuggers can grep server logs by the value they
        # see in the response header.
        response.headers["X-Request-ID"] = request_id
        return response
