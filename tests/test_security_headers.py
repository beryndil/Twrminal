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
    _INLINE_SCRIPT_RE,
    build_csp,
    compute_inline_script_hashes,
    csp_from_static_dir,
    install_global_exception_handler,
    install_security_headers,
    static_csp_provider,
)

_BASELINE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@pytest.mark.parametrize(
    "header,expected",
    sorted(_BASELINE_HEADERS.items()),
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
    typed into the address bar.

    IPv6 host-sources (e.g. `ws://[::1]:*`) are intentionally NOT
    asserted: they're rejected by the CSP host-source grammar in
    every browser (logged as 'invalid source' and ignored). Surfaced
    by the v1.0.0 Playwright smoke pass on 2026-04-30."""
    resp = client.get("/api/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "ws://localhost:*" in csp
    assert "ws://127.0.0.1:*" in csp
    assert "ws://[::1]:*" not in csp


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/sessions/abc",
        "/vault.html",
    ],
)
def test_csp_permits_bundle_inline_scripts(client: TestClient, path: str) -> None:
    """SvelteKit's static adapter emits multiple HTML entry points
    (`index.html` for `/`, `200.html` for the SPA fallback used by
    deep-linked routes like `/sessions/<id>`, plus standalone
    `vault.html`). Each carries its own hydration bootstrap with a
    different third inline script, so the CSP must hash them all.
    Hashing only `index.html` left hard-refresh on `/sessions/<id>`
    blocked by CSP — the document loaded but its third script was
    rejected, so the SPA never hydrated. This parametrised test
    fetches each entry point and asserts every inline script is
    permitted by the response's CSP."""
    resp = client.get(path)
    if resp.status_code == 404:
        pytest.skip("frontend bundle not built into web/dist; nothing to check")
    assert resp.status_code == 200
    csp = resp.headers.get("Content-Security-Policy", "")
    hashes = compute_inline_script_hashes(resp.text)
    assert hashes, f"served {path} has no inline scripts to verify"
    for digest in hashes:
        assert f"'{digest}'" in csp, f"inline script {digest} at {path} not in CSP"


def test_compute_inline_script_hashes_skips_external_scripts() -> None:
    """`<script src=...>` tags carry no inline body; CSP `'self'`
    already covers them. The hasher must skip them so we don't pollute
    `script-src` with hashes that don't correspond to anything."""
    html = (
        '<script src="/_app/foo.js"></script>'
        "<script>console.log('hi')</script>"
        '<script type="module" src="/bar.js"></script>'
    )
    hashes = compute_inline_script_hashes(html)
    assert len(hashes) == 1
    assert hashes[0].startswith("sha256-")


def test_inline_script_regex_matches_attribute_variants() -> None:
    """Sanity: SvelteKit emits inline scripts both with and without
    attributes (`<script>` and `<script type="module">`). The regex
    must catch both forms."""
    html = '<script>a()</script><script type="module">b()</script>'
    bodies = [m.group(1) for m in _INLINE_SCRIPT_RE.finditer(html)]
    assert bodies == ["a()", "b()"]


def test_build_csp_omits_script_src_when_no_hashes() -> None:
    """No hashes → no `script-src` directive emitted, so callers that
    don't serve a frontend (API-only embeddings, tests) inherit the
    same baseline as `default-src 'self'`."""
    csp = build_csp()
    assert "script-src" not in csp
    assert "default-src 'self'" in csp


def test_build_csp_includes_provided_hashes() -> None:
    csp = build_csp(script_hashes=["sha256-abc", "sha256-def"])
    assert "script-src 'self' 'sha256-abc' 'sha256-def'" in csp


def test_csp_from_static_dir_unions_hashes_across_html_entry_points(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """SvelteKit emits `index.html` + `200.html` (SPA fallback) + any
    standalone routes (e.g. `vault.html`), and each has its own
    hydration bootstrap. `csp_from_static_dir` must hash inline
    scripts across every `*.html` in the dir and dedupe — otherwise
    the entry point not chosen for hashing serves with a CSP that
    rejects its own scripts."""
    static_dir = tmp_path  # type: ignore[assignment]
    (static_dir / "index.html").write_text(  # type: ignore[attr-defined]
        "<script>shared()</script><script>indexOnly()</script>",
        encoding="utf-8",
    )
    (static_dir / "200.html").write_text(  # type: ignore[attr-defined]
        "<script>shared()</script><script>fallbackOnly()</script>",
        encoding="utf-8",
    )
    (static_dir / "vault.html").write_text(  # type: ignore[attr-defined]
        "<script>shared()</script><script>vaultOnly()</script>",
        encoding="utf-8",
    )
    csp = csp_from_static_dir(static_dir)  # type: ignore[arg-type]
    expected = [
        compute_inline_script_hashes("<script>shared()</script>")[0],
        compute_inline_script_hashes("<script>indexOnly()</script>")[0],
        compute_inline_script_hashes("<script>fallbackOnly()</script>")[0],
        compute_inline_script_hashes("<script>vaultOnly()</script>")[0],
    ]
    for digest in expected:
        assert f"'{digest}'" in csp, f"{digest} missing from unioned CSP"
    # Dedupe: `shared` should appear exactly once even though three
    # files contributed it.
    assert csp.count(f"'{expected[0]}'") == 1


def test_csp_from_static_dir_handles_missing_dir(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Server running with no built frontend → no HTML files → fall
    back to the no-`script-src` baseline."""
    csp = csp_from_static_dir(tmp_path)  # type: ignore[arg-type]
    assert "script-src" not in csp
    assert "default-src 'self'" in csp


def test_install_security_headers_recomputes_csp_on_static_dir_change(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """A frontend rebuild while the server is running must not lock
    the UI out. `static_csp_provider` is consulted per request, so
    edits to the static dir's HTML propagate without a server restart.

    Regression for 2026-04-27: the CSP was snapshotted at app start.
    A subsequent `npm run build` rewrote `index.html`'s third inline
    script, the new hash never made it into the allowlist, and
    SvelteKit's hydration bootstrap was blocked — the sidebar
    rendered empty because the SPA never started its first
    `/api/sessions` fetch.
    """
    import os

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    static_dir = tmp_path  # type: ignore[assignment]
    index_html = static_dir / "index.html"  # type: ignore[attr-defined]
    index_html.write_text(
        "<script>shared()</script><script>oldScript()</script>",
        encoding="utf-8",
    )

    app = FastAPI()
    install_security_headers(app, csp=static_csp_provider(static_dir))  # type: ignore[arg-type]

    @app.get("/probe")
    async def probe() -> dict[str, str]:
        return {"ok": "1"}

    old_hash = compute_inline_script_hashes("<script>oldScript()</script>")[0]
    new_hash = compute_inline_script_hashes("<script>newScript()</script>")[0]

    with TestClient(app) as c:
        first_csp = c.get("/probe").headers.get("Content-Security-Policy", "")
    assert f"'{old_hash}'" in first_csp, "initial CSP should pin the original script"
    assert f"'{new_hash}'" not in first_csp

    # Simulate a rebuild. Bump mtime explicitly so the cache key
    # changes regardless of filesystem mtime resolution.
    index_html.write_text(
        "<script>shared()</script><script>newScript()</script>",
        encoding="utf-8",
    )
    stat = index_html.stat()
    os.utime(index_html, ns=(stat.st_mtime_ns + 1_000_000_000,) * 2)

    with TestClient(app) as c:
        second_csp = c.get("/probe").headers.get("Content-Security-Policy", "")
    assert f"'{new_hash}'" in second_csp, "rebuilt CSP must include the new script's hash"
    assert f"'{old_hash}'" not in second_csp, "rebuilt CSP must drop the stale hash"


def test_install_security_headers_accepts_static_csp_string() -> None:
    """The string form of `csp=` still works for callers that don't
    serve a frontend (API-only embeddings, tests). Per-request
    resolution is gated on the callable form."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    install_security_headers(app, csp="default-src 'self'; img-src data:")

    @app.get("/probe")
    async def probe() -> dict[str, str]:
        return {"ok": "1"}

    with TestClient(app) as c:
        csp = c.get("/probe").headers.get("Content-Security-Policy", "")
    assert csp == "default-src 'self'; img-src data:"


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
    for header, value in _BASELINE_HEADERS.items():
        assert resp.headers.get(header) == value
    assert "Content-Security-Policy" in resp.headers


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
