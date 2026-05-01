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

import base64
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

log = logging.getLogger(__name__)

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
#
# `script-src` is built dynamically from the inline-script hashes in
# the served `index.html` — see `compute_inline_script_hashes` and
# `build_csp` below. The audit-shipped CSP omitted `script-src` and
# fell through to `default-src 'self'`, which forbids inline scripts;
# that broke SvelteKit's hydration bootstrap (3 inline <script> tags
# the SPA can't run without). Pinning the actual hashes preserves
# CSP's protection without the `'unsafe-inline'` downgrade.

_INLINE_SCRIPT_RE = re.compile(r"<script(?:\s[^>]*)?>(.*?)</script>", re.DOTALL)


def compute_inline_script_hashes(html: str) -> list[str]:
    """Extract the SHA-256 hash of every non-empty inline `<script>`
    body in `html`, formatted as CSP source expressions
    (`sha256-<base64>`). Scripts with a `src=` attribute (i.e. empty
    body) are skipped — they're already covered by `script-src 'self'`.
    """
    hashes: list[str] = []
    for match in _INLINE_SCRIPT_RE.finditer(html):
        body = match.group(1)
        if not body.strip():
            continue
        digest = hashlib.sha256(body.encode("utf-8")).digest()
        hashes.append("sha256-" + base64.b64encode(digest).decode("ascii"))
    return hashes


def build_csp(*, script_hashes: Sequence[str] = ()) -> str:
    """Assemble the Content-Security-Policy string.

    `script_hashes` are the SvelteKit hydration scripts permitted to
    run inline. When empty, no `script-src` directive is emitted and
    the browser falls through to `default-src 'self'` (no inline
    scripts allowed). Callers serving the SPA should pass the hashes
    computed from `index.html`; callers that don't serve a frontend
    can leave it empty.
    """
    parts = [
        "default-src 'self'",
        # IPv6 host-sources (e.g. `ws://[::1]:*`) are not part of the
        # CSP host-source grammar — every browser logs an "invalid
        # source" warning and ignores the entry. Bearings binds
        # 127.0.0.1 by default, so the IPv4 + DNS forms cover the
        # actual reachable WS endpoints; users on a machine that
        # binds the IPv6 loopback can override CSP via config if it
        # ever matters.
        "connect-src 'self' ws://localhost:* ws://127.0.0.1:*",
        "style-src 'self' 'unsafe-inline'",
    ]
    if script_hashes:
        quoted = " ".join(f"'{h}'" for h in script_hashes)
        parts.append(f"script-src 'self' {quoted}")
    return "; ".join(parts)


def csp_from_static_dir(static_dir: Path) -> str:
    """Hash inline scripts from every `*.html` in `static_dir` and build
    the CSP. SvelteKit's static adapter emits multiple HTML entry
    points (`index.html` for `/`, `200.html` for the SPA fallback,
    plus any standalone routes like `vault.html`), and each one
    carries its own hydration bootstrap with a slightly different
    third inline script. Hashing only `index.html` left hard-refresh
    on `/sessions/<id>` (served from `200.html`) blocked by CSP — the
    bug this function exists to prevent. If no HTML files are present
    (server running without a built bundle) returns `build_csp()` with
    no script hashes.
    """
    hashes: list[str] = []
    seen: set[str] = set()
    for html_path in sorted(static_dir.glob("*.html")):
        html = html_path.read_text(encoding="utf-8")
        for h in compute_inline_script_hashes(html):
            if h not in seen:
                seen.add(h)
                hashes.append(h)
    return build_csp(script_hashes=hashes)


def static_csp_provider(static_dir: Path) -> Callable[[], str]:
    """Return a CSP factory that tracks `static_dir`'s HTML files.

    The factory is consulted per request by `install_security_headers`.
    Cache key is the tuple of `(name, mtime_ns, size)` for every
    `*.html` in the dir — adding, removing, or rebuilding any entry
    point invalidates and forces a recompute.

    This fixes the failure mode where the CSP is snapshotted at app
    construction, the frontend is rebuilt later, and the served HTML's
    new inline-script hashes don't appear in the stale allowlist —
    SvelteKit's hydration bootstrap is then blocked by CSP and the
    SPA never starts. Per-request resolution lets `npm run build`
    take effect without a server restart.

    The cache is cleared before each insert: only the latest CSP is
    retained, so repeated rebuilds don't accumulate dead entries.
    """
    cache: dict[tuple[tuple[str, int, int], ...], str] = {}

    def provider() -> str:
        key = tuple(
            sorted(
                (p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in static_dir.glob("*.html")
            )
        )
        cached = cache.get(key)
        if cached is None:
            cached = csp_from_static_dir(static_dir)
            cache.clear()
            cache[key] = cached
        return cached

    return provider


_BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def install_security_headers(app: FastAPI, *, csp: str | Callable[[], str] | None = None) -> None:
    """Wire the security-headers middleware onto `app`.

    Applies to every HTTP response, including the ones FastAPI
    synthesizes for HTTPException and the sanitized 500 below
    (middleware wraps the exception-handler stack). WebSocket
    handshakes are not affected — see module docstring.

    `csp` may be a fixed string (snapshot once, never changes) or a
    callable that returns the current CSP (consulted per request).
    Callers serving the SvelteKit bundle should pass the callable
    form via `static_csp_provider`, so a frontend rebuild propagates
    without a server restart.

    `setdefault` is used rather than direct assignment so a specific
    route that legitimately needs a different value (e.g. a future
    embed endpoint relaxing X-Frame-Options) can opt out by setting
    the header explicitly on its response. Today no such route
    exists; the posture is defensive against later additions.
    """

    csp_provider: Callable[[], str]
    if callable(csp):
        csp_provider = csp
    else:
        fixed_csp = csp if csp is not None else build_csp()

        def csp_provider() -> str:  # noqa: E306
            return fixed_csp

    @app.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for header, value in _BASE_HEADERS.items():
            response.headers.setdefault(header, value)
        response.headers.setdefault("Content-Security-Policy", csp_provider())
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
