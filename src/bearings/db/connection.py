"""SQLite connection lifecycle.

Two helpers, one pattern:

- :func:`open_connection` returns a configured :class:`aiosqlite.Connection`.
  Caller owns the close. Used by :mod:`bearings.db.migrations` where the
  migration runner controls the connection's lifetime explicitly.
- :func:`connect` is an ``async with`` context manager that opens, hands
  out, and closes. Used by everything else — request handlers, tests,
  one-shot scripts.

Both apply the same PRAGMAs:

- ``foreign_keys = ON`` — SQLite ships this OFF for backward
  compatibility; we want referential integrity enforced.
- ``journal_mode = WAL`` — write-ahead logging gives concurrent reads
  during writes. Persists on the file (sticky pragma); set on every
  connect anyway because no-op is cheap and explicit beats implicit.
- ``synchronous = NORMAL`` — paired with WAL is the recommended setting
  for a balance of durability and write throughput; FULL is overkill
  for a localhost dev tool.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


async def open_connection(db_path: Path) -> aiosqlite.Connection:
    """Open a connection to *db_path* and apply standard PRAGMAs.

    The parent directory must exist; the migration runner creates it
    before calling this helper. The connection is returned in
    ``aiosqlite.Row`` row-factory mode so query results are accessed
    by column name (``row["id"]``) rather than positional index.
    """
    connection = await aiosqlite.connect(db_path)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.execute("PRAGMA journal_mode = WAL")
    await connection.execute("PRAGMA synchronous = NORMAL")
    return connection


@asynccontextmanager
async def connect(db_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Async context manager wrapping :func:`open_connection`.

    Usage::

        async with connect(settings.db_path) as conn:
            async with conn.execute("SELECT 1") as cur:
                row = await cur.fetchone()

    Ensures the connection is closed even if the body raises. Prefer
    this over :func:`open_connection` unless you specifically need to
    own the connection's lifetime.
    """
    connection = await open_connection(db_path)
    try:
        yield connection
    finally:
        await connection.close()
