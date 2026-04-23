"""Shared DB primitives — connection bootstrap, migration runner,
timestamp + id helpers. Imported by every `_*.py` module in this
package; must not itself import from them.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiosqlite

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# SQLite tuning — safe under WAL. Negative cache_size is KB, positive is pages.
_CACHE_SIZE_KB = -64000  # 64 MB page cache
_MMAP_SIZE_BYTES = 128 * 1024 * 1024  # 128 MB memory-mapped reads


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
    await conn.commit()
    return conn


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
