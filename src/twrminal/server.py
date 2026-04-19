from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from twrminal import __version__
from twrminal.api import (
    routes_health,
    routes_history,
    routes_metrics,
    routes_sessions,
    routes_tags,
    ws_agent,
)
from twrminal.config import Settings, load_settings
from twrminal.db.store import init_db

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
    try:
        yield
    finally:
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
    app = FastAPI(title="Twrminal", version=__version__, lifespan=lifespan)
    app.state.settings = cfg

    app.include_router(routes_health.router, prefix="/api")
    app.include_router(routes_sessions.router, prefix="/api")
    app.include_router(routes_tags.router, prefix="/api")
    app.include_router(routes_history.router, prefix="/api")
    app.include_router(routes_metrics.router)
    app.include_router(ws_agent.router)

    if STATIC_DIR.exists() and any(STATIC_DIR.iterdir()):
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")

    return app
