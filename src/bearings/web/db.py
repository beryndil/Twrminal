"""Per-request database connection dependency.

Concept: FastAPI's :func:`fastapi.Depends` accepts an async generator
function. The framework calls it on each request, takes the
``yield``-ed value, hands it to the route, then advances the generator
on response (running the ``finally`` block to close the connection).
Same shape as a context manager, but FastAPI manages the lifecycle.

This module exposes :func:`build_db_dependency` — a factory that binds
:func:`bearings.db.connect` to the configured ``db_path`` and returns
the async generator. The app factory wires the result onto
``app.dependency_overrides`` so routers can declare:

    @router.get(...)
    async def list_things(db: aiosqlite.Connection = Depends(get_db)) -> ...:
        ...

Tests override the dependency to point at an isolated tmp-path SQLite
file (or an in-memory DB, when that proves useful).
"""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import aiosqlite

from bearings.db import connect


def build_db_dependency(db_path: Path) -> Callable[[], AsyncIterator[aiosqlite.Connection]]:
    """Return an async generator dependency yielding a per-request connection.

    The returned callable is what gets attached to
    ``app.dependency_overrides[get_db]`` in :func:`create_app`. Each
    request opens a fresh connection (cheap with SQLite) and closes it
    on response — no pooling complexity for v1, no shared state across
    requests, no risk of cross-request transaction leakage.
    """

    async def _get_db() -> AsyncIterator[aiosqlite.Connection]:
        async with connect(db_path) as connection:
            yield connection

    return _get_db


async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """Sentinel dependency replaced by :func:`build_db_dependency` output.

    Mirrors the pattern in :mod:`bearings.web.auth` — calling this
    raises explicitly so a missed override surfaces as a developer
    error rather than a silent 500.
    """
    msg = (
        "get_db was called without being overridden by create_app(); "
        "the FastAPI app was built incorrectly."
    )
    raise RuntimeError(msg)
    yield  # pragma: no cover - unreachable; satisfies the AsyncIterator return type
