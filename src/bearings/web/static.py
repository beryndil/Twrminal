"""Static-bundle serving + SPA fallback for the SvelteKit frontend.

Per ``docs/architecture-v1.md`` §1.1.5, the FastAPI app's static-bundle
mount lives in its own module so ``web/app.py`` stays a thin factory.
The SvelteKit build artifact (item 2.1) lands at
``src/bearings/web/dist/`` so it ships inside the Python wheel via
``[tool.hatch.build.targets.wheel] packages = ["src/bearings"]``;
this module locates that directory at import time and serves it.

Two serving concerns are bundled here:

* **Asset serving** — every file inside ``dist/`` (the SvelteKit
  `index.html`, the Vite-hashed JS / CSS / font assets, favicons) is
  served by ``StaticFiles`` at the standard MIME types.

* **SPA fallback** — SvelteKit's client-side router handles routes
  like ``/sessions/<id>`` that the server never produced as a separate
  HTML file. When the static layer 404s, this module rewrites the
  response to the bundle's ``index.html`` so the client-side router
  picks up the path. The fallback is gated to *html-accepting* GET
  requests so an unknown ``/api/<endpoint>`` path or asset miss still
  surfaces as a real 404.

API routes registered before the static mount take precedence —
``/openapi.json``, every ``/api/*`` and ``/ws/*`` route resolves
normally. Only paths that fall through to the static mount go through
the SPA fallback.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

# Directory the SvelteKit static adapter writes to (configured in
# ``frontend/svelte.config.js``). Resolved relative to *this* file so
# the bundle ships inside the wheel and the lookup works the same in
# editable installs as in installed wheels.
_BUNDLE_DIR: Path = Path(__file__).resolve().parent / "dist"

# SvelteKit's default fallback document name (configured in
# ``frontend/svelte.config.js`` as ``fallback: "index.html"``). Named
# here so the path appears in only one place.
_FALLBACK_HTML: str = "index.html"


class _BundleStaticFiles(StaticFiles):
    """``StaticFiles`` subclass that falls back to the SPA shell.

    Behavior:

    * Existing files inside the bundle resolve normally — the
      hash-named JS / CSS / font assets, favicon, etc.
    * Non-existent paths fall back to ``index.html`` so the SvelteKit
      client-side router can resolve them, *but only* when the request
      looks like a navigation: GET method and ``Accept`` includes
      ``text/html``.
    * All other misses (POST to a non-existent path, an asset reference
      with no ``Accept: text/html``) return a real 404 instead of an
      HTML body the caller cannot consume.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except Exception as exc:  # pragma: no cover - delegated below
            from starlette.exceptions import HTTPException as StarletteHTTPException

            if (
                not isinstance(exc, StarletteHTTPException)
                or exc.status_code != status.HTTP_404_NOT_FOUND
            ):
                raise
            request = Request(scope)
            if request.method != "GET":
                raise
            if "text/html" not in request.headers.get("accept", ""):
                raise
            fallback = self._resolve_fallback()
            if fallback is None:
                raise
            return FileResponse(fallback)

    def _resolve_fallback(self) -> Path | None:
        # ``self.directory`` is set by ``StaticFiles.__init__``. Wrap
        # in ``Path`` so the join is platform-safe and the existence
        # check survives a missing bundle (e.g. a fresh checkout
        # before ``npm run build``).
        if not self.directory:
            return None
        candidate = Path(self.directory) / _FALLBACK_HTML
        return candidate if candidate.is_file() else None


# Prefixes and exact paths that must never be swallowed by the SPA
# catch-all.  API / WS / metrics / OpenAPI surfaces always take
# precedence because their routers are registered first; the catch-all
# never fires for those paths in normal operation.  This set is a
# defensive guard for unmatched sub-paths that fall through (e.g. a
# typo'd ``/api/…`` route with no handler).
_SPA_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "/api/",
    "/ws/",
    "/metrics",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/static/",
)


def _spa_path_excluded(path: str) -> bool:
    """Return ``True`` when *path* must bypass the SPA catch-all.

    Matches both the bare prefix (``/metrics``) and any sub-path below
    it (``/metrics/foo``).
    """
    for prefix in _SPA_EXCLUDED_PREFIXES:
        bare = prefix.rstrip("/")
        if path == bare or path.startswith(bare + "/"):
            return True
    return False


async def spa_fallback_handler(request: Request) -> Response:
    """Serve the SvelteKit shell for any non-API navigation path.

    Registered as ``GET /{path:path}`` in
    :func:`bearings.web.app.create_app` after all API / WS / metrics
    routers but *before* the static-bundle mount, so named API routes
    always resolve through their own handlers first.

    Serving rules:

    * Paths matching an excluded prefix (``/api/``, ``/ws/``, etc.)
      raise HTTP 404 — the caller expected an API response, not an
      SPA shell.
    * Paths whose last segment contains a ``.`` are treated as asset
      references; they also raise HTTP 404 so a JS loader is never
      fed an HTML body.
    * All other paths receive ``dist/index.html`` with
      ``Content-Type: text/html`` so the SvelteKit client-side router
      resolves the route.
    * If the bundle is absent (backend-only test run) HTTP 404 is
      raised so tests that do not build the frontend see a clear miss.
    """
    path = request.url.path
    if _spa_path_excluded(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if "." in Path(path).name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    index = bundle_dir() / _FALLBACK_HTML
    if not index.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return FileResponse(str(index), media_type="text/html")


def bundle_dir() -> Path:
    """Return the on-disk path the static bundle is served from.

    Exposed as a function (rather than the module-level constant) so
    tests can monkeypatch it without import-time side effects.
    """
    return _BUNDLE_DIR


def mount_static_bundle(app: FastAPI) -> None:
    """Mount ``dist/`` at the app root with SPA fallback.

    Idempotent on a missing bundle: if ``dist/`` does not exist (e.g.
    a backend-only test run), no mount is added and the app continues
    to serve API + WS routes only. Production callers run
    ``npm run build`` before serving so the bundle is always present.
    """
    directory = bundle_dir()
    if not directory.is_dir():
        return
    app.mount(
        "/",
        _BundleStaticFiles(directory=str(directory), html=True),
        name="bearings_frontend",
    )


__all__ = ["bundle_dir", "mount_static_bundle", "spa_fallback_handler"]
