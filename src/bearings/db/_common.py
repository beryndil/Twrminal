"""Shared DB primitives — connection bootstrap, migration runner,
timestamp + id helpers. Imported by every `_*.py` module in this
package; must not itself import from them.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiosqlite

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# SQLite tuning — safe under WAL. Negative cache_size is KB, positive is pages.
_CACHE_SIZE_KB = -64000  # 64 MB page cache
_MMAP_SIZE_BYTES = 128 * 1024 * 1024  # 128 MB memory-mapped reads

# Migration names that have been intentionally retired forward-only —
# the file no longer exists on disk, but historical DBs still carry
# the applied row. The drift pass deletes these rows on startup
# rather than refusing to start; the corresponding `00NN_retire_*.sql`
# file documents the retirement and locks the decision via checksum.
#
# Adding a name here is a deliberate ratchet: it permits a row to
# exist in the DB that has no corresponding file. Only add a name
# after confirming the original migration's effects have been undone
# (or are intentionally kept) and the file is safely deletable.
# See TODO.md "Drift detector lacks forward-only-revert tombstones"
# for the v1 case (0011_sdk_reported_cost.sql, retired by 0032).
_RETIRED_MIGRATIONS: frozenset[str] = frozenset(
    {
        "0011_sdk_reported_cost.sql",
    }
)

# Columns added by retired migrations whose effects still linger in
# affected DBs and need cleanup. Each entry is `(table, column)`.
# Idempotent on every boot: pragma_table_info gates the ALTER, so DBs
# that never had the column or already had it dropped are a no-op.
# Pure SQL would have to be migration-driven, but SQLite has no
# `DROP COLUMN IF EXISTS` and a non-idempotent ALTER would crashloop
# on every fresh DB. Doing it Python-side from `init_db` keeps the
# migration files honest and the cleanup harmless.
_RETIRED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("sessions", "sdk_reported_cost_usd"),  # from retired 0011_sdk_reported_cost.sql
)


class MigrationDriftError(RuntimeError):
    """Raised when `schema_migrations` has a row we can't reconcile
    against the files in `MIGRATIONS_DIR`.

    Two cases both map here:
      1. **Unknown applied row.** A row names a migration file that
         no longer exists on disk (code downgrade, deleted file, or
         DB from a newer build). Continuing would silently run against
         a schema we didn't author.
      2. **Checksum mismatch.** A row's stored checksum doesn't match
         the current file on disk. Someone edited a migration after
         it was applied — the DB state no longer reflects the file.

    Both are fatal: we refuse to start so the user sees the drift in
    the startup log rather than discovering it hours later as a
    cryptic runtime error. Added 2026-04-21 security audit §4.
    """


async def init_db(path: Path) -> aiosqlite.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA synchronous = NORMAL")
    await conn.execute(f"PRAGMA cache_size = {_CACHE_SIZE_KB}")
    await conn.execute("PRAGMA temp_store = MEMORY")
    await conn.execute(f"PRAGMA mmap_size = {_MMAP_SIZE_BYTES}")
    await conn.execute("PRAGMA foreign_keys = ON")
    await _apply_migrations(conn)
    await _drop_retired_columns(conn)
    await conn.commit()
    # Tighten permissions to owner-only *after* WAL has materialized so
    # the sidecar files (`-wal`, `-shm`) exist and can be chmod'd too.
    # SQLite creates them at default umask — on multi-user hosts that
    # leaves session contents readable by other local accounts.
    # 2026-04-21 security audit §2 (2026-04-23 fix). Idempotent: runs
    # on every boot, so a DB created before this fix gets clamped on
    # next startup. `os.chmod` swallowed on OSError — some filesystems
    # (tmpfs subsets, network mounts) reject chmod even with owner
    # perms; the data still belongs to the right uid, refusing to
    # start would hurt more than leaving the bit set.
    _clamp_db_permissions(path)
    return conn


def _clamp_db_permissions(path: Path) -> None:
    """Force `0o600` on the SQLite DB and its WAL/SHM sidecars.

    Called from `init_db` after the connection is open. Failures are
    logged-silent (see init_db comment) because the function is
    best-effort defense-in-depth; the real gate is the `0600` umask
    on the process itself where it can be controlled."""
    import os
    from contextlib import suppress

    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            with suppress(OSError):
                os.chmod(candidate, 0o600)


def _checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def _ensure_migrations_table(conn: aiosqlite.Connection) -> None:
    """Create/upgrade the tracking table. `checksum` is machinery-level,
    not user schema, so it's managed here rather than as a numbered SQL
    migration — otherwise the migration runner would depend on its own
    output column existing before the migration that adds it has run.
    """
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT)"
    )
    # Pre-existing DBs (pre-2026-04-23) have the table without the
    # checksum column. SQLite has no `ADD COLUMN IF NOT EXISTS`, so
    # inspect `pragma_table_info` and add it only when missing.
    async with conn.execute("SELECT name FROM pragma_table_info('schema_migrations')") as cur:
        cols = {row[0] async for row in cur}
    if "checksum" not in cols:
        await conn.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")


async def _apply_migrations(conn: aiosqlite.Connection) -> None:
    await _ensure_migrations_table(conn)
    known: dict[str, str] = {
        mig.name: _checksum(mig.read_bytes()) for mig in sorted(MIGRATIONS_DIR.glob("*.sql"))
    }
    async with conn.execute("SELECT name, checksum FROM schema_migrations") as cur:
        applied: dict[str, str | None] = {row[0]: row[1] async for row in cur}

    # Drift pass: every applied row must correspond to a shipped
    # migration, and its stored checksum (if any) must match. A NULL
    # checksum means "applied before this machinery existed" — backfill
    # it from the current file since by construction the DB already
    # reflects that file's content.
    for name, stored in applied.items():
        if name not in known:
            if name in _RETIRED_MIGRATIONS:
                # Forward-only retirement: drop the orphan row and
                # carry on. The retiring migration (e.g. 0032) has
                # been written under the assumption that any column
                # adds from the original migration are handled by
                # `_drop_retired_columns`, so the row deletion is
                # safe to do unattended.
                await conn.execute("DELETE FROM schema_migrations WHERE name = ?", (name,))
                log.info(
                    "schema_migrations: retired orphan row %r dropped (tombstone)",
                    name,
                )
                continue
            raise MigrationDriftError(
                f"schema_migrations has applied row {name!r} but no such file "
                f"in {MIGRATIONS_DIR}. Downgrade or deletion? Refusing to start."
            )
        if stored is None:
            await conn.execute(
                "UPDATE schema_migrations SET checksum = ? WHERE name = ?",
                (known[name], name),
            )
            continue
        if stored != known[name]:
            raise MigrationDriftError(
                f"schema_migrations row {name!r} has checksum {stored} but the "
                f"file now hashes to {known[name]}. A migration was edited "
                f"after it ran. Refusing to start."
            )

    # Apply pass: anything in `known` that wasn't already applied gets
    # executed and recorded with its checksum. `executescript` auto-
    # commits inside SQLite, so there's no useful `BEGIN/COMMIT` we can
    # wrap around the script itself — but the INSERT is only issued on
    # success, so a failure mid-script leaves the row unrecorded and
    # the next boot re-runs it. Migrations must therefore stay
    # idempotent (`IF NOT EXISTS` for creates; `ALTER TABLE` changes
    # are inherently one-shot and need manual cleanup on failure).
    for name, digest in known.items():
        if name in applied:
            continue
        migration = MIGRATIONS_DIR / name
        await conn.executescript(migration.read_text())
        await conn.execute(
            "INSERT INTO schema_migrations (name, applied_at, checksum) "
            "VALUES (?, datetime('now'), ?)",
            (name, digest),
        )


async def _drop_retired_columns(conn: aiosqlite.Connection) -> None:
    """Idempotently drop columns left behind by retired migrations.

    Each `(table, column)` pair in `_RETIRED_COLUMNS` is gated on the
    column actually being present — `pragma_table_info` is the source
    of truth, so DBs that never ran the retired migration (or that
    already had the column dropped on a prior boot) skip the ALTER.

    This is in Python rather than SQL because SQLite has no
    `ALTER TABLE ... DROP COLUMN IF EXISTS` and a non-idempotent
    column drop in a numbered migration file would crashloop on
    every fresh DB that never had the column to begin with.

    Failures are logged but never fatal: a leftover dead column is
    harmless (the canonical schema has already been cleaned of any
    references) and the next boot retries.
    """
    for table, column in _RETIRED_COLUMNS:
        # Table names are constants from `_RETIRED_COLUMNS`, never
        # user input — safe to interpolate. PRAGMA table_info doesn't
        # accept bound parameters in every SQLite build, so the
        # f-string is the portable form.
        async with conn.execute(f"SELECT name FROM pragma_table_info('{table}')") as cur:
            cols = {row[0] async for row in cur}
        if column not in cols:
            continue
        try:
            await conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
            log.info("retired column dropped: %s.%s", table, column)
        except aiosqlite.OperationalError as exc:
            # SQLite refuses DROP COLUMN if the column is referenced
            # by an index, view, trigger, or CHECK constraint. The
            # canonical schema has none of those for retired columns
            # by construction, but log + carry on rather than crash
            # on an unexpected dependency.
            log.warning(
                "retired column drop deferred: %s.%s — %s (harmless; will retry next boot)",
                table,
                column,
                exc,
            )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid4().hex


def _date_filter(
    column: str, date_from: str | None, date_to: str | None
) -> tuple[str, tuple[str, ...]]:
    """Build a `WHERE substr(column, 1, 10) BETWEEN ...` fragment. Shared
    by the history aggregate queries (`list_all_*`). Returns an empty
    clause + empty params tuple when neither bound is set."""
    clauses: list[str] = []
    params: list[str] = []
    if date_from is not None:
        clauses.append(f"substr({column}, 1, 10) >= ?")
        params.append(date_from)
    if date_to is not None:
        clauses.append(f"substr({column}, 1, 10) <= ?")
        params.append(date_to)
    if not clauses:
        return "", ()
    return " WHERE " + " AND ".join(clauses), tuple(params)
