"""Idempotent data-directory initialisation for ``bearings init`` (arch §1.1.1).

The public surface is a single synchronous callable,
:func:`ensure_data_dir`, that the ``bearings init`` CLI subcommand calls.
Everything async lives in the private :func:`_init_async` coroutine so the
sync wrapper can use ``asyncio.run`` without exposing the event-loop detail
to callers.

Layer isolation
---------------
This module may import from ``bearings.db.*`` and ``bearings.config.*``
(arch §3 line 549 — the forbidden imports are ``bearings.agent.*``,
``bearings.web.*``, and ``bearings.cli.*``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from bearings.config.constants import (
    DEFAULT_AVATARS_STORAGE_ROOT,
    DEFAULT_DB_PATH,
    DEFAULT_UPLOADS_STORAGE_ROOT,
)
from bearings.db.connection import load_schema


async def _init_db(db_path: Path) -> None:
    """Initialise the SQLite schema on *db_path*.

    Only DB I/O lives here; all filesystem ``mkdir`` calls happen in the
    synchronous :func:`ensure_data_dir` wrapper so ASYNC240 (pathlib in
    async context) is not triggered.
    """
    async with aiosqlite.connect(db_path) as conn:
        await load_schema(conn)


def ensure_data_dir(
    db_path: Path = DEFAULT_DB_PATH,
    uploads_root: Path = DEFAULT_UPLOADS_STORAGE_ROOT,
    avatars_root: Path = DEFAULT_AVATARS_STORAGE_ROOT,
) -> bool:
    """Create ``~/.local/share/bearings-v1/`` layout and initialise the DB.

    Creates (with ``parents=True, exist_ok=True``) the data directory, the
    upload-store root, and the avatar-store root.  Applies the canonical DB
    schema via :func:`~bearings.db.connection.load_schema`, which is itself
    fully idempotent (every ``CREATE TABLE`` / ``CREATE INDEX`` is guarded by
    ``IF NOT EXISTS`` and every seeded row uses ``INSERT OR IGNORE``).

    Safe to run on an already-initialised installation — the second and
    subsequent calls are no-ops.

    Returns
    -------
    bool
        ``True`` when the data directory was freshly created; ``False`` when
        it already existed.

    Raises
    ------
    OSError
        Propagated from :func:`pathlib.Path.mkdir` or
        :func:`aiosqlite.connect` on genuine filesystem failures.
    """
    data_dir = db_path.parent
    fresh = not data_dir.exists()
    data_dir.mkdir(parents=True, exist_ok=True)
    uploads_root.mkdir(parents=True, exist_ok=True)
    avatars_root.mkdir(parents=True, exist_ok=True)
    asyncio.run(_init_db(db_path))
    return fresh


__all__ = ["ensure_data_dir"]
