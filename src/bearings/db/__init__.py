"""Database layer.

Bearings uses SQLite via aiosqlite, with raw SQL and a per-resource
query module convention — no ORM. The split:

- :mod:`bearings.db.connection` — open / close / configure connections.
- :mod:`bearings.db.migrations` — apply versioned schema migrations.
- :mod:`bearings.db.queries` — one module per resource (sessions,
  tags, …); added as resources land in §8.

Public API: :func:`init_db` (run from app bootstrap), :func:`connect`
(async context manager for request-scoped or one-shot work).
"""

from bearings.db.connection import connect
from bearings.db.migrations import init_db

__all__ = ["connect", "init_db"]
