from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from bearings import __version__

router = APIRouter(tags=["health"])

# Resolved once at import; the actual stat() runs every /version call
# but the path is constant.
_INDEX_HTML = Path(__file__).parent.parent / "web" / "dist" / "index.html"


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    enabled = request.app.state.settings.auth.enabled
    return {
        "auth": "required" if enabled else "disabled",
        "version": __version__,
    }


@router.get("/version")
async def version() -> dict[str, str | None]:
    """Bundle-identity probe for the SPA's seamless-reload watcher.

    Returns the package `version` (release string, e.g. "0.10.0") plus
    a `build` token that changes every time the frontend bundle is
    rebuilt. The frontend pins `build` on boot and compares future
    poll responses / WS-handshake announcements against that pin; a
    mismatch flags the SPA as stale and arms the visibility-triggered
    reload (see `frontend/src/lib/stores/version_watcher.svelte.ts`).

    `build` is the nanosecond mtime of `dist/index.html`. SvelteKit's
    adapter-static rewrites that file on every `npm run build` (it
    references the current build's hashed chunk filenames in the head
    tag), so the mtime bumps whenever a real frontend change has
    shipped — no extra build-step plumbing required, no hashing.
    One stat() per request.

    `build` is `None` when the bundle directory is absent (developer
    running the API without having built the frontend yet). The
    watcher treats `None` as "version unknown" and does not arm a
    reload, so the dev workflow stays quiet."""
    if not _INDEX_HTML.exists():
        return {"version": __version__, "build": None}
    return {
        "version": __version__,
        "build": str(_INDEX_HTML.stat().st_mtime_ns),
    }
