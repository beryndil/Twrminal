"""Application entry point.

Wires up the foundational components in the only order that's safe:

1. Config first (so logging can read ``log_level`` and ``log_json``
   from it).
2. Logging second (so the exception handler can use a structlog
   logger and the migration runner can log progress).
3. Exception handler third (now that logging is up, uncaught
   exceptions can be logged structurally).
4. Database migrations fourth (logging is up to record progress; the
   process should exit non-zero if migrations fail, which the
   exception handler now ensures).

The §7 foundation builds the bootstrap up to the migrations step and
exits cleanly. §8 (web layer) replaces the trailing ``hello`` event
with starting the FastAPI server in this same ordering.
"""

import asyncio

from bearings.config import Settings
from bearings.db import init_db
from bearings.errors import setup_exception_handler
from bearings.log import configure_logging, get_logger


async def _bootstrap() -> None:
    """Async bootstrap: build settings, init logging+errors, run migrations.

    Separated from :func:`main` so tests can drive the async path
    without re-implementing the ``asyncio.run`` plumbing.
    """
    settings = Settings()
    configure_logging(level=settings.log_level, json=settings.log_json)
    setup_exception_handler()

    logger = get_logger(__name__)
    logger.info(
        "app.starting",
        app_name=settings.app_name,
        environment=settings.environment,
        data_dir=str(settings.data_dir),
    )

    await init_db(settings.db_path)

    logger.info("app.ready", db_path=str(settings.db_path))


def main() -> None:
    """Synchronous entry point for the ``bearings`` console script."""
    asyncio.run(_bootstrap())


if __name__ == "__main__":
    main()
