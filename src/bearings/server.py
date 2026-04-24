from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from bearings import __version__
from bearings.agent.registry import RunnerRegistry
from bearings.agent.sessions_broker import SessionsBroker
from bearings.api import (
    routes_checklists,
    routes_checkpoints,
    routes_commands,
    routes_config,
    routes_fs,
    routes_health,
    routes_history,
    routes_messages,
    routes_metrics,
    routes_pending,
    routes_reorg,
    routes_sessions,
    routes_sessions_bulk,
    routes_shell,
    routes_tags,
    routes_templates,
    routes_uploads,
    routes_vault,
    ws_agent,
    ws_sessions,
)
from bearings.config import Settings, load_settings
from bearings.db.store import init_db
from bearings.menus import load_menu_config

STATIC_DIR = Path(__file__).parent / "web" / "dist"

# WebSocket close code for "server shutdown" — clients interpret this as
# a clean disconnect and reconnect on their own backoff schedule.
CODE_GOING_AWAY = 1001


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
    try:
        yield
    finally:
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

    app.include_router(routes_health.router, prefix="/api")
    app.include_router(routes_config.router, prefix="/api")
    app.include_router(routes_sessions.router, prefix="/api")
    app.include_router(routes_sessions_bulk.router, prefix="/api")
    app.include_router(routes_reorg.router, prefix="/api")
    app.include_router(routes_tags.router, prefix="/api")
    app.include_router(routes_checklists.router, prefix="/api")
    app.include_router(routes_checkpoints.router, prefix="/api")
    app.include_router(routes_messages.router, prefix="/api")
    app.include_router(routes_templates.router, prefix="/api")
    app.include_router(routes_history.router, prefix="/api")
    app.include_router(routes_fs.router, prefix="/api")
    app.include_router(routes_uploads.router, prefix="/api")
    app.include_router(routes_commands.router, prefix="/api")
    app.include_router(routes_shell.router, prefix="/api")
    app.include_router(routes_pending.router, prefix="/api")
    app.include_router(routes_vault.router, prefix="/api")
    app.include_router(routes_metrics.router)
    app.include_router(ws_agent.router)
    app.include_router(ws_sessions.router)

    if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")

    return app
