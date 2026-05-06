"""Versioned schema migrations.

Convention:

- Migrations live as plain ``.sql`` files in ``bearings/db/migrations/``.
- Filenames are ``NNNN_short_label.sql`` where ``NNNN`` is a zero-padded
  integer version starting at ``0001``. Lexicographic sort matches
  numeric sort up to 9999 migrations — fine for a single-product DB.
- Each file is applied exactly once, in order, inside one transaction.
- The current version is tracked in a ``schema_version`` table that
  the runner creates on first run.
- Applied versions are recorded by inserting ``(version, applied_at)``
  rows; the runner skips any version already present.

Why hand-rolled rather than alembic / yoyo: aiosqlite + raw SQL is the
stack pick (plan §3), the migration count for v1 is small, and a
hand-rolled runner sidesteps the "ORM smuggled in via tooling" risk.
The runner is small and fully under our control.
"""

import re
from pathlib import Path

import aiosqlite
import structlog

from bearings.db.connection import open_connection

logger = structlog.get_logger(__name__)

# Path-relative-to-this-file directory holding the .sql migration files.
# Resolved at import time; constant for the lifetime of the process.
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Filename shape: 0001_label.sql. Matches the version digits as group 1.
_MIGRATION_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


def _discover_migrations(directory: Path = _MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    """Return ``(version, path)`` pairs sorted by version ascending.

    Files that don't match :data:`_MIGRATION_FILENAME` are ignored
    (e.g. README.md, editor backup files). Duplicate versions raise —
    that's a developer error caught at startup, not silently.
    """
    found: dict[int, Path] = {}
    for path in directory.iterdir():
        match = _MIGRATION_FILENAME.match(path.name)
        if match is None:
            continue
        version = int(match.group(1))
        if version in found:
            msg = f"duplicate migration version {version}: {found[version].name} and {path.name}"
            raise RuntimeError(msg)
        found[version] = path
    return sorted(found.items())


async def _load_applied_versions(connection: aiosqlite.Connection) -> set[int]:
    """Return the set of versions already recorded in ``schema_version``."""
    async with connection.execute("SELECT version FROM schema_version") as cursor:
        rows = await cursor.fetchall()
    return {int(row["version"]) for row in rows}


async def init_db(db_path: Path) -> None:
    """Apply all pending migrations to the database at *db_path*.

    Creates the parent directory and the database file if they don't
    exist. Idempotent: running twice is a no-op (every applied version
    is recorded; the runner skips already-applied ones).

    :param db_path: absolute path to the SQLite file (typically
        ``settings.db_path``).
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrations = _discover_migrations()

    connection = await open_connection(db_path)
    try:
        await connection.execute(_SCHEMA_VERSION_DDL)
        await connection.commit()

        applied = await _load_applied_versions(connection)
        pending = [(v, p) for v, p in migrations if v not in applied]

        if not pending:
            logger.info(
                "db.migrations.up_to_date",
                version=max(applied) if applied else 0,
                count=len(applied),
            )
            return

        for version, path in pending:
            sql = path.read_text(encoding="utf-8")
            await connection.executescript(sql)
            await connection.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (version,),
            )
            await connection.commit()
            logger.info("db.migrations.applied", version=version, file=path.name)
    finally:
        await connection.close()
