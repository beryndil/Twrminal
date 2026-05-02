"""``bearings serve`` subcommand — production entry point for the web UI.

Per ``docs/architecture-v1.md`` §1.1.1 the CLI is the only supported
boot path; per ``docs/behavior/bearings-cli.md`` §"bearings serve"
the subcommand wires :class:`Settings` → :func:`create_app` →
``aiosqlite`` startup hook → ``uvicorn.run``.

The body deliberately mirrors the v1.0 ``launch.py`` stopgap that
``~/.local/share/bearings-v1/launch.py`` ships — the v1.1
closing-sweep moves that wiring into the CLI so the systemd unit can
call ``bearings serve`` instead of a stopgap script (TODO.md
"Stopgap launcher → ``bearings serve`` CLI").

Per arch §1.1.1 the subcommand body stays thin: parsing args, calling
:func:`create_app`, registering the DB lifecycle hooks, handing off
to ``uvicorn``. No business logic — every observable behavior comes
from :mod:`bearings.web.app`.
"""

from __future__ import annotations

import argparse

import aiosqlite
import uvicorn

from bearings.config.constants import CLI_EXIT_OK
from bearings.config.settings import Settings
from bearings.web.app import create_app


def build_subparser(parent: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Wire the ``serve`` subcommand into ``parent``."""
    serve = parent.add_parser(
        "serve",
        help="Run the Bearings web UI on the configured host/port",
        description=(
            "Boot the FastAPI app from `bearings.config.settings.Settings` and serve "
            "it via uvicorn. The DB connection on `app.state.db_connection` opens "
            "during the FastAPI startup event and closes on shutdown."
        ),
    )
    serve.add_argument(
        "--host",
        default=None,
        help="bind host (defaults to Settings.host — '127.0.0.1' under loopback policy)",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="bind port (defaults to Settings.port — 8788 in v1)",
    )
    serve.add_argument(
        "--log-level",
        default="info",
        choices=("critical", "error", "warning", "info", "debug", "trace"),
        help="uvicorn log level (default: info)",
    )
    serve.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    """Hand off to uvicorn with the DB lifecycle hooks attached.

    Returns :data:`CLI_EXIT_OK` once uvicorn exits cleanly; any
    exception bubbles up as a non-zero exit per the CLI alphabet.
    """
    settings = Settings()
    app = create_app()

    @app.on_event("startup")
    async def _open_db() -> None:
        db = await aiosqlite.connect(settings.db_path)
        db.row_factory = aiosqlite.Row
        app.state.db_connection = db

    @app.on_event("shutdown")
    async def _close_db() -> None:
        db = getattr(app.state, "db_connection", None)
        if db is not None:
            await db.close()

    host = args.host if args.host is not None else settings.host
    port = args.port if args.port is not None else settings.port
    uvicorn.run(app, host=host, port=port, log_level=args.log_level)
    return CLI_EXIT_OK


__all__ = ["build_subparser"]
