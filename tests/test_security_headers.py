"""Security headers + sanitized 500 contract.

Pins the cheap defense-in-depth surface from the 2026-04-25 standards
audit (§1 Zero-Crash + §10 security headers):

- Three baseline response headers (`X-Content-Type-Options`,
  `X-Frame-Options`, `Referrer-Policy`) plus a permissive CSP land on
  every HTTP response.
- HSTS is deliberately NOT set (no TLS at localhost — see middleware
  module docstring).
- An unhandled exception returns 500 with `{"error": "internal"}` and
  no stack content / class name / exception message leaks to the
  client.  The full traceback still hits the server log so on-host
  debugging keeps working.
- HTTPException-shaped errors continue to flow through FastAPI's
  built-in handler — the catch-all does not shadow 404 / 401 / 422.

Why a separate test module: these are contract surfaces that future
refactors should not be able to silently regress.  Anyone removing a
header without realising the audit cared should land here in red.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bearings.api.middleware import (
    DEFAULT_CSP,
    SECURITY_HEADERS,
    install_global_exception_handler,
)


@pytest.mark.parametrize(
    "header,expected",
    sorted(SECURITY_HEADERS.items()),
)
def test_health_route_carries_security_headers(
    client: TestClient, header: str, expected: str
) -> None:
    """Hit the lightweight `/api/health` route — every baseline header
    should land on the response with the canonical value."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get(header) == expected


def test_csp_allows_localhost_websockets(client: TestClient) -> None:
    """`connect-src` must list every loopback alias the bundle can be
    served under.  WS upgrade responses themselves are not bound by
    CSP, but the document that *opens* the socket is — so this
    clause has to land for the SvelteKit bundle to talk to
    /ws/sessions and /ws/agent regardless of which loopback the user
    typed into the address bar."""
    resp = client.get("/api/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert csp == DEFAULT_CSP
    assert "ws://localhost:*" in csp
    assert "ws://127.0.0.1:*" in csp
    assert "ws://[::1]:*" in csp


def test_no_hsts_header(client: TestClient) -> None:
    """HSTS is meaningless at no-TLS localhost.  Setting it would be
    cargo-culted and could trip a future deploy that *does* terminate
    TLS into accidentally inheriting an unintended `max-age`.  The
    audit explicitly called it out as a `do not add`."""
    resp = client.get("/api/health")
    assert "Strict-Transport-Security" not in resp.headers


def test_security_headers_land_on_404(client: TestClient) -> None:
    """Middleware wraps the exception-handler stack — even a 404 from
    a missing route should still carry the baseline headers.  This
    rules out a class of regressions where an early-returning router
    bypasses the header-stamping path."""
    resp = client.get("/api/this-route-does-not-exist")
    assert resp.status_code == 404
    for header, value in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == value


def test_unhandled_exception_returns_sanitized_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Forced raise → 500 with `{"error": "internal"}`. No exception
    class, message, or stack frames in the response. The original
    exception text *must* still appear in the server log so on-host
    debugging works."""
    app = FastAPI()
    install_global_exception_handler(app)

    secret = "internal-detail-DO-NOT-LEAK"

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError(secret)

    with caplog.at_level(logging.ERROR, logger="bearings.api.middleware"):
        # `raise_server_exceptions=False` keeps TestClient from
        # re-raising the exception in the test process — we want the
        # actual HTTP response the handler produces.
        with TestClient(app, raise_server_exceptions=False) as c:
            resp = c.get("/boom")

    assert resp.status_code == 500
    assert resp.json() == {"error": "internal"}

    # Negative space: the original exception's text must NOT appear
    # anywhere in what reaches the client. Walk both body and headers.
    assert secret not in resp.text
    for value in resp.headers.values():
        assert secret not in value

    # Positive space: the server log captured the traceback.
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    log_text += "\n" + "\n".join(record.exc_text or "" for record in caplog.records)
    assert secret in log_text or "RuntimeError" in log_text


def test_handler_does_not_shadow_http_exceptions() -> None:
    """FastAPI/Starlette dispatches more-specific handlers first.  A
    raised HTTPException(404) must still produce a 404 with the normal
    `{"detail": ...}` shape — *not* the sanitized 500.  If this ever
    flips, the catch-all has been wired wrong and every 4xx response
    would lose its detail body."""
    app = FastAPI()
    install_global_exception_handler(app)

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="not found")

    with TestClient(app) as c:
        resp = c.get("/missing")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "not found"}
