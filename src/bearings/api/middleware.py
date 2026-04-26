"""Cheap defense-in-depth HTTP layer: security headers + sanitized 500.

Two install hooks, both wired by `bearings.server.create_app`:

- `install_security_headers(app)` — `@app.middleware("http")` that
  stamps four baseline headers on every HTTP response.
- `install_global_exception_handler(app)` — catches otherwise-
  unhandled exceptions, logs the full traceback locally, and returns
  a sanitized 500 body with no stack content to the client.

## Headers

- `X-Content-Type-Options: nosniff` — prevents MIME-type sniffing on
  resources we serve. Free harden.
- `X-Frame-Options: DENY` — refuses framing entirely. Cosmetic at
  localhost (no public origin to embed us), but free.
- `Referrer-Policy: no-referrer` — outbound nav from the UI never
  leaks an internal URL to an external site.
- `Content-Security-Policy` — narrows the document's loadable
  origins. Permissive for v1 so the SvelteKit bundle keeps working;
  tighten as we move toward audited inline-style usage.

## Deliberately omitted

- `Strict-Transport-Security` (HSTS) — meaningless without TLS, and
  Bearings binds to 127.0.0.1 with no certificate. Setting it would
  be cargo-culted, and a future deploy that *does* terminate TLS
  should add it explicitly with a sensible `max-age` rather than
  inherit a copy-pasted default.

## WebSocket scope

Starlette's HTTP middleware only fires when `scope['type'] == 'http'`,
so the WS handshake (`scope['type'] == 'websocket'`) bypasses this
layer entirely. That's deliberate — CSP on a WS upgrade response has
no effect, and adding response headers to the upgrade carries a small
risk of breaking the protocol negotiation in a future Starlette
revision.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

log = logging.getLogger(__name__)

# Permissive CSP baseline. Audit (2026-04-25) called for "start
# permissive so the SvelteKit bundle keeps working; tighten later."
#
# `connect-src` covers fetch / EventSource / WebSocket. The browser
# does NOT fold ws:// into `'self'` even when the document was loaded
# over http://same-origin — the schemes differ — so the explicit
# ws:// entries are required for /ws/sessions to work. Three loopback
# aliases are included because `auth.py:_allowed_origins()` already
# treats all three as valid bundle origins; pruning [::1] here would
# silently break the WS for any user on the IPv6 loopback.
#
# `style-src 'self' 'unsafe-inline'` accommodates the inline styles
# Tailwind / SvelteKit emit during hydration. Removing 'unsafe-inline'
# is a follow-up audit item once we've inventoried which inline
# styles are actually load-bearing vs. removable.
DEFAULT_CSP = (
    "default-src 'self'; "
    "connect-src 'self' "
    "ws://localhost:* ws://127.0.0.1:* ws://[::1]:*; "
    "style-src 'self' 'unsafe-inline'"
)

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": DEFAULT_CSP,
}


def install_security_headers(app: FastAPI) -> None:
    """Wire the security-headers middleware onto `app`.

    Applies to every HTTP response, including the ones FastAPI
    synthesizes for HTTPException and the sanitized 500 below
    (middleware wraps the exception-handler stack). WebSocket
    handshakes are not affected — see module docstring.

    `setdefault` is used rather than direct assignment so a specific
    route that legitimately needs a different value (e.g. a future
    embed endpoint relaxing X-Frame-Options) can opt out by setting
    the header explicitly on its response. Today no such route
    exists; the posture is defensive against later additions.
    """

    @app.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def install_global_exception_handler(app: FastAPI) -> None:
    """Catch otherwise-unhandled exceptions; log + return sanitized 500.

    Starlette dispatches more-specific handlers (HTTPException,
    RequestValidationError, the per-status-code map) before this
    catch-all, so 404 / 401 / 422 responses are unchanged — only
    genuinely unexpected exceptions hit this path.

    The full traceback is logged via `logger.exception` so on-host
    debugging keeps working. The client only sees
    `{"error": "internal"}` with no exception class, message, module
    path, or stack frames. Audit §1 (Zero-Crash) called this out as
    a real leak; the rest of the section was already covered by the
    lifespan teardown.
    """

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # %r so the log line carries the exception type + repr;
        # logger.exception attaches the full traceback automatically.
        log.exception("unhandled exception in request: %r", exc)
        return JSONResponse(status_code=500, content={"error": "internal"})
