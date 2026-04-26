from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from bearings import __version__
from bearings.agent.registry import RunnerRegistry
from bearings.agent.sessions_broker import SessionsBroker
from bearings.api import (
    routes_artifacts,
    routes_checklists,
    routes_checkpoints,
    routes_commands,
    routes_config,
    routes_diag,
    routes_fs,
    routes_health,
    routes_history,
    routes_messages,
    routes_metrics,
    routes_pending,
    routes_preferences,
    routes_regenerate,
    routes_reorg,
    routes_reply_actions,
    routes_sessions,
    routes_sessions_bulk,
    routes_shell,
    routes_spawn_from_reply,
    routes_tags,
    routes_templates,
    routes_uploads,
    routes_vault,
    ws_agent,
    ws_sessions,
)
from bearings.api.middleware import (
    install_global_exception_handler,
    install_security_headers,
)
from bearings.config import Settings, load_settings
from bearings.db.store import init_db
from bearings.menus import load_menu_config

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "web" / "dist"

# WebSocket close code for "server shutdown" — clients interpret this as
# a clean disconnect and reconnect on their own backoff schedule.
CODE_GOING_AWAY = 1001


class _BundleStaticFiles(StaticFiles):
    """StaticFiles that distinguishes content-addressed bundle chunks
    from the entry-point HTML and tells the browser to cache each
    appropriately.

    Default `StaticFiles` ships no `Cache-Control` header at all, so
    Chromium / Firefox apply heuristic caching — which works fine for
    hashed chunks (their filenames carry a content hash, so a stale
    cache entry is by definition still correct) but breaks `index.html`,
    which is NOT hashed and references the *current* bundle's chunk
    filenames. After a `npm run build`, the chunks land at fresh
    hashes; if the browser's cached `index.html` still points at the
    previous build's chunks, the user runs old code until they Ctrl+
    Shift+R. That's exactly the "I have to force-reload to see your
    fixes" complaint.

    Headers we set:
      - `_app/immutable/*` — `public, max-age=31536000, immutable`.
        Hashed filenames mean a byte change always changes the path,
        so a cached entry can never be stale. `immutable` tells modern
        browsers to skip revalidation entirely.
      - everything else (`index.html`, `manifest.webmanifest`,
        `favicon.png`, etc.) — `no-cache`. Counter-intuitively this
        does NOT mean "don't cache"; it means "always revalidate
        before serving from cache." Combined with the ETag/Last-
        Modified that StaticFiles already emits, the revalidation is
        a cheap 304 when nothing changed and a fresh 200 when we've
        rebuilt — so a new bundle reaches Daisy on her next page
        load without a forced reload, but unchanged bytes don't
        re-download.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.startswith("_app/immutable/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            # `must-revalidate` belt-and-suspenders for proxies that
            # honor it differently from raw `no-cache`. Both ensure
            # the browser checks back with us before reusing.
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.db = await init_db(settings.storage.db_path)
    active: set[WebSocket] = set()
    app.state.active_ws = active
    # Server-wide sessions-list pubsub. Every mutation to a session row
    # (create / update / close / reopen / delete / viewed) and every
    # runner state transition fans out to every open sidebar via
    # `/ws/sessions`. Phase-1 `softRefresh` poll stays as a belt-and-
    # suspenders reconciliation path — if the broadcast drops, the
    # poll converges within 3 s.
    app.state.sessions_broker = SessionsBroker()
    # RunnerRegistry owns per-session agent loops decoupled from WS
    # lifetime. Sessions keep running when the UI walks away; see
    # bearings.agent.runner for the contract. The reaper evicts
    # runners that have been idle + unsubscribed past the configured
    # TTL so a long-lived server doesn't accumulate one worker +
    # ring buffer per session the user ever opened.
    app.state.runners = RunnerRegistry(
        idle_ttl_seconds=settings.runner.idle_ttl_seconds,
        reap_interval_seconds=settings.runner.reap_interval_seconds,
    )
    app.state.runners.start_reaper()
    # AutoDriverRegistry owns running autonomous-checklist drivers.
    # Each POST /sessions/{id}/checklist/run lands an entry; DELETE
    # or app shutdown drains them. After migration 0031 the per-run
    # bookkeeping is durable — the rehydrate scan below re-creates
    # asyncio.Tasks for any run that was alive at the last lifespan
    # teardown so a systemd restart no longer evaporates an autonomous
    # tour mid-walk. The driver's outer loop picks up at the next
    # unchecked item; an in-flight leg from the prior life is dropped.
    from bearings.agent.auto_driver_runtime import AutoDriverRegistry

    app.state.auto_drivers = AutoDriverRegistry()
    try:
        rehydrated = await app.state.auto_drivers.rehydrate(app)
        if rehydrated:
            log.info(
                "auto-driver: rehydrated %d running run(s) from auto_run_state: %s",
                len(rehydrated),
                rehydrated,
            )
    except Exception:
        # Rehydrate failures are non-fatal: the user can re-POST any
        # run they care about, but the rest of the app must still
        # come up. Log loudly so the failure is visible.
        log.exception("auto-driver: rehydrate scan failed at startup")
    try:
        yield
    finally:
        # Stop autonomous drivers before runners so the driver's
        # current leg gets a chance to tear down cleanly via the
        # runtime's teardown_leg call. Any driver still mid-leg when
        # this returns has already had its stop flag set.
        await app.state.auto_drivers.shutdown_all()
        # Drain runners first so in-flight SDK subprocesses get a
        # clean interrupt before the DB handle goes away.
        await app.state.runners.shutdown_all()
        for ws in list(app.state.active_ws):
            try:
                await ws.close(code=CODE_GOING_AWAY, reason="server shutdown")
            except Exception:
                # Socket already closed by peer or underlying transport — not
                # actionable during shutdown, and we still need to close the
                # remaining connections + the DB.
                pass
        app.state.active_ws.clear()
        await app.state.db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or load_settings()
    app = FastAPI(title="Bearings", version=__version__, lifespan=lifespan)
    app.state.settings = cfg
    # Load `menus.toml` once at app construction. Phase 10 deliberately
    # has no hot-reload: a server restart is required to pick up
    # override edits. The frontend reads the parsed shape at boot via
    # `/api/ui-config` and merges it into the in-memory action registry.
    app.state.menus = load_menu_config(cfg.menus_file)

    # Cheap defense-in-depth: stamp baseline security headers on every
    # HTTP response, and convert otherwise-unhandled exceptions into a
    # sanitized 500 (no stack content to the client; full traceback in
    # the log). See `bearings.api.middleware` for rationale, including
    # why HSTS is deliberately omitted at localhost. Both calls must
    # happen before the first request — `include_router` does not
    # trigger middleware build, so order with the route registrations
    # below is irrelevant in practice, but installing here keeps the
    # security wiring co-located with app construction.
    install_security_headers(app)
    install_global_exception_handler(app)

    app.include_router(routes_health.router, prefix="/api")
    app.include_router(routes_config.router, prefix="/api")
    app.include_router(routes_sessions.router, prefix="/api")
    app.include_router(routes_sessions_bulk.router, prefix="/api")
    app.include_router(routes_reorg.router, prefix="/api")
    app.include_router(routes_tags.router, prefix="/api")
    app.include_router(routes_checklists.router, prefix="/api")
    app.include_router(routes_checkpoints.router, prefix="/api")
    app.include_router(routes_regenerate.router, prefix="/api")
    app.include_router(routes_spawn_from_reply.router, prefix="/api")
    app.include_router(routes_reply_actions.router, prefix="/api")
    app.include_router(routes_messages.router, prefix="/api")
    app.include_router(routes_templates.router, prefix="/api")
    app.include_router(routes_history.router, prefix="/api")
    app.include_router(routes_fs.router, prefix="/api")
    app.include_router(routes_uploads.router, prefix="/api")
    app.include_router(routes_artifacts.session_router, prefix="/api")
    app.include_router(routes_artifacts.serve_router, prefix="/api")
    app.include_router(routes_commands.router, prefix="/api")
    app.include_router(routes_shell.router, prefix="/api")
    app.include_router(routes_pending.router, prefix="/api")
    app.include_router(routes_preferences.router, prefix="/api")
    app.include_router(routes_vault.router, prefix="/api")
    app.include_router(routes_diag.router, prefix="/api")
    app.include_router(routes_metrics.router)
    app.include_router(ws_agent.router)
    app.include_router(ws_sessions.router)

    if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
        app.mount("/", _BundleStaticFiles(directory=STATIC_DIR, html=True), name="frontend")

    return app
