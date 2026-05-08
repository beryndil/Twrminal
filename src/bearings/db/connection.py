"""aiosqlite connection bootstrap for the Bearings v1 database.

Two pieces of public surface:

* :func:`get_connection_factory` returns a no-argument callable each
  invocation of which opens a fresh ``aiosqlite.Connection`` at the same
  on-disk path. Callers use it as ``async with factory() as conn:`` per the
  hand-verify recipe in the item-0.4 instructions; the factory itself does
  no I/O until called.
* :func:`load_schema` applies the canonical DDL from ``schema.sql`` to an
  open connection. The DDL is itself idempotent (every ``CREATE TABLE`` and
  every ``CREATE INDEX`` uses ``IF NOT EXISTS``; every seeded
  ``system_routing_rules`` row is wrapped in ``INSERT OR IGNORE`` against a
  partial unique index on ``(priority) WHERE seeded = 1``). Calling
  ``load_schema`` against a freshly-opened connection on an existing DB is a
  no-op.

Foreign-key enforcement is opt-in per connection in SQLite — the bootstrap
issues ``PRAGMA foreign_keys = ON`` before applying the DDL so that the
``ON DELETE`` clauses declared in ``schema.sql`` actually fire. Downstream
query modules that open their own connection must repeat the pragma; the
schema-test suite verifies this contract.

References:

* ``docs/architecture-v1.md`` §1.1.3 — bootstrap responsibility lives in
  this module; ``aiosqlite`` is the async driver pinned at the project
  level.
* ``docs/model-routing-v1-spec.md`` §3 — seven default ``system_routing_rules``
  rows are seeded on first apply, idempotent on re-init.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import aiosqlite

# Resolved at import time so a renamed/relocated schema.sql produces an
# ImportError at module load rather than a runtime failure deep inside the
# first ``load_schema`` call.
SCHEMA_PATH: Final[Path] = Path(__file__).parent / "schema.sql"


def get_connection_factory(
    database_path: Path,
) -> Callable[[], aiosqlite.Connection]:
    """Return a no-argument factory that opens connections to ``database_path``.

    The returned ``aiosqlite.Connection`` is itself an async context manager;
    callers use ``async with factory() as conn:`` to scope the lifetime. The
    factory does not load the schema — the caller invokes :func:`load_schema`
    explicitly inside the context, so test code can open a connection
    without mutating disk state.
    """

    def _factory() -> aiosqlite.Connection:
        return aiosqlite.connect(database_path)

    return _factory


async def load_schema(connection: aiosqlite.Connection) -> None:
    """Apply ``schema.sql`` to ``connection`` and seed default system rules.

    Idempotent on re-init: every ``CREATE TABLE`` / ``CREATE INDEX`` in the
    DDL uses ``IF NOT EXISTS``, and the seven default
    ``system_routing_rules`` rows use ``INSERT OR IGNORE`` against the
    partial unique index ``idx_system_routing_rules_seeded_priority``.

    Foreign keys are enabled on this connection before the DDL runs (the
    pragma is per-connection in SQLite). Downstream callers that open their
    own connection are responsible for repeating ``PRAGMA foreign_keys =
    ON``; this contract is verified by ``tests/test_db_schema.py``.
    """
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.executescript(schema_sql)
    await _ensure_added_columns(connection)
    await connection.commit()


# Columns that landed after the initial schema.sql shipped. The
# canonical CREATE TABLE in ``schema.sql`` is authoritative for fresh
# databases (it lists each column); this list catches existing
# databases — migrated from v0.17.x or carried over a prior v1
# install — that predate the column. SQLite's ``ALTER TABLE ... ADD
# COLUMN`` is not idempotent on its own, so we gate each ALTER on
# ``PRAGMA table_info``.
_ADDED_COLUMNS: Final[tuple[tuple[str, str, str], ...]] = (
    ("sessions", "closing_summary", "TEXT"),
    # Routing-decision projection — landed after initial schema.sql ship.
    # Existing rows get NULL advisor (= unknown / use legacy behaviour),
    # and the safe numeric defaults so bootstrap always reads a valid row.
    ("sessions", "routing_advisor_model", "TEXT"),
    ("sessions", "routing_advisor_max_uses", "INTEGER NOT NULL DEFAULT 5"),
    ("sessions", "routing_effort_level", "TEXT NOT NULL DEFAULT 'auto'"),
    # G3 message context-menu columns — landed after initial schema.sql ship.
    # Existing rows default to 0 (not pinned, not hidden).
    ("messages", "pinned", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "hidden_from_context", "INTEGER NOT NULL DEFAULT 0"),
    # Inspector Routing eval-chain column — JSON array of rule ids tested
    # (``RoutingDecision.evaluated_rules``). Existing rows get '[]' (empty
    # chain — pre-dates the column; treated as no-chain on read).
    ("messages", "evaluated_rules", "TEXT DEFAULT '[]'"),
    # Spawn-from-reply back-pointers (gap-cycle-03-007). FK constraints
    # cannot be added via ALTER TABLE in SQLite; declared as plain TEXT
    # here (schema.sql carries the FKs for fresh DBs; existing rows get
    # NULL — no pivot message, no parent).
    ("sessions", "pivot_message_id", "TEXT"),
    ("sessions", "parent_session_id", "TEXT"),
    # G4 tag context-menu columns — landed after initial schema.sql ship.
    # Existing tags default to 0 (unpinned).
    ("tags", "pinned", "INTEGER NOT NULL DEFAULT 0"),
    # Tag-class feature columns — landed after initial schema.sql ship.
    # Existing tags default to 'general' (legacy slash-namespaced names
    # carry forward unchanged) and sort_order 0 (alphabetical fallback
    # within the class until the user drag-reorders).
    (
        "tags",
        "class",
        "TEXT NOT NULL DEFAULT 'general' CHECK (class IN ('project', 'severity', 'general'))",
    ),
    ("tags", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
    # gap-cycle-03-011: user identity / profile columns on preferences.
    # Existing rows get NULL for all three (no identity configured yet).
    ("preferences", "display_name", "TEXT"),
    ("preferences", "avatar_path", "TEXT"),
    ("preferences", "avatar_mime_type", "TEXT"),
    # gap-cycle-07-001: desktop-notification opt-in.
    # Existing rows default to 0 (off) — the user must re-enable.
    (
        "preferences",
        "notify_on_complete",
        "INTEGER NOT NULL DEFAULT 0 CHECK (notify_on_complete IN (0, 1))",
    ),
    # feature-2-004: [stopped] annotation on interrupted assistant turns.
    # Existing rows default to 0 (not stopped — pre-dates the column).
    (
        "messages",
        "stopped",
        "INTEGER NOT NULL DEFAULT 0 CHECK (stopped IN (0, 1))",
    ),
    # analytics-phase-0: cache-creation token billing counter per Anthropic
    # API ``cacheCreationInputTokens`` field. Existing rows get NULL (no
    # data captured before this column landed; treated as 0 by COALESCE in
    # aggregation queries per analytics spec §4.1).
    ("messages", "cache_creation_tokens", "INTEGER"),
)


# Indexes that reference columns introduced via ``_ADDED_COLUMNS``.
# These must be created **after** the ALTER pass so a legacy DB
# (whose live tags table predates the column the index references)
# does not raise ``no such column`` on the very first re-init. Fresh
# DBs hit the same code path harmlessly because every CREATE INDEX
# is gated on ``IF NOT EXISTS``.
_POST_ALTER_INDEXES: Final[tuple[str, ...]] = (
    "CREATE INDEX IF NOT EXISTS idx_tags_class_sort_order ON tags(class, sort_order ASC, name ASC)",
    (
        "CREATE INDEX IF NOT EXISTS idx_sessions_pivot_message_id "
        "ON sessions(pivot_message_id) WHERE pivot_message_id IS NOT NULL"
    ),
)


async def _ensure_added_columns(connection: aiosqlite.Connection) -> None:
    """Add columns introduced after the original schema.sql ship.

    Each tuple is ``(table, column, sqlite_type)``; the column is
    added only when ``PRAGMA table_info(<table>)`` does not already
    list it. Keeps ``load_schema`` a single idempotent entrypoint
    rather than scattering ALTERs across migration files.

    After every ALTER lands, runs :data:`_POST_ALTER_INDEXES` so any
    index that references a freshly-added column is built against the
    new shape, not the stale one.
    """
    for table, column, column_type in _ADDED_COLUMNS:
        async with connection.execute(f"PRAGMA table_info({table})") as cursor:
            rows = await cursor.fetchall()
        existing = {row[1] for row in rows}
        if column not in existing:
            await connection.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {column_type}",
            )
    for index_sql in _POST_ALTER_INDEXES:
        await connection.execute(index_sql)
