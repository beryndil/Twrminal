"""DB migration runner for the ``bearings migrate`` CLI subcommand (arch §1.1.1).

The only public surface is :func:`run_migrations` — a synchronous wrapper
that opens the DB, counts pending column additions, applies
:func:`~bearings.db.connection.load_schema` (which is idempotent), and
returns the count of columns that were actually altered.

The migration mechanism is the :data:`~bearings.db.connection._ADDED_COLUMNS`
list in :mod:`bearings.db.connection`: a ``PRAGMA table_info`` probe per
entry determines whether the column already exists before issuing the
``ALTER TABLE``.  Running against an up-to-date schema is a no-op and
returns ``0``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from bearings.config.constants import DEFAULT_DB_PATH
from bearings.db.connection import _ADDED_COLUMNS, load_schema


async def _migrate_async(db_path: Path) -> int:
    """Apply schema + added-column migrations; return count of columns added.

    The pre-flight probe (``PRAGMA table_info`` before ``load_schema``) counts
    only columns genuinely absent from the live schema, so the return value
    accurately reflects how many ``ALTER TABLE`` operations were required — not
    how many columns are tracked in :data:`~bearings.db.connection._ADDED_COLUMNS`.
    """
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("PRAGMA foreign_keys = ON")
        pending = 0
        for table, column, _ in _ADDED_COLUMNS:
            async with conn.execute(f"PRAGMA table_info({table})") as cur:
                rows = await cur.fetchall()
            existing = {row[1] for row in rows}
            if column not in existing:
                pending += 1
        await load_schema(conn)
    return pending


def run_migrations(db_path: Path = DEFAULT_DB_PATH) -> int:
    """Apply pending DB schema migrations; return the count of columns added.

    Opens *db_path*, counts any column additions required by
    :data:`~bearings.db.connection._ADDED_COLUMNS` that are not yet present,
    applies :func:`~bearings.db.connection.load_schema` (idempotent), and
    returns the count.

    A return value of ``0`` means the schema is already up to date.

    Parameters
    ----------
    db_path:
        Path to the SQLite database.  Defaults to
        :data:`~bearings.config.constants.DEFAULT_DB_PATH`.

    Raises
    ------
    FileNotFoundError
        When *db_path* does not exist.  The caller should run ``bearings init``
        first to create and initialise the database.
    OSError
        Propagated from :func:`aiosqlite.connect` on genuine filesystem failures.
    """
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    return asyncio.run(_migrate_async(db_path))


__all__ = ["run_migrations"]
