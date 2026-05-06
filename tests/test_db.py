"""Tests for bearings.db.

Cover the migration runner end-to-end on a temp SQLite file:

- First run creates the schema_version table and applies 0001.
- Re-running is idempotent (no duplicate inserts, no errors).
- The 0001 schema actually lands (app_meta table queryable).
- Connection PRAGMAs are applied (foreign_keys ON).

The autouse ``_isolate_data_dir`` fixture in conftest.py points
``Settings().data_dir`` at a per-test tmp directory; tests here
construct an explicit ``db_path`` under ``tmp_path`` to avoid coupling
to that fixture's exact layout.
"""

from pathlib import Path

import aiosqlite

from bearings.db import connect, init_db


async def test_init_db_creates_db_and_schema_version(tmp_path: Path) -> None:
    """First-run init creates the file and the schema_version table."""
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)

    assert db_path.exists()

    async with (
        connect(db_path) as conn,
        conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") as cur,
    ):
        tables = {row["name"] for row in await cur.fetchall()}

    assert "schema_version" in tables
    assert "app_meta" in tables


async def test_init_db_records_applied_version(tmp_path: Path) -> None:
    """All shipped migrations are recorded in schema_version after first run.

    The asserted list grows as new migrations land; if a developer
    forgets to add a row here when adding ``NNNN_*.sql``, the test
    fails loudly and points at the omission.
    """
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)

    async with (
        connect(db_path) as conn,
        conn.execute("SELECT version FROM schema_version") as cur,
    ):
        versions = sorted(int(row["version"]) for row in await cur.fetchall())

    assert versions == [1, 2]


async def test_init_db_is_idempotent(tmp_path: Path) -> None:
    """Running init_db twice is a no-op — no duplicate inserts, no errors.

    Counts the recorded versions; the value tracks the number of
    shipped migrations so this assertion stays meaningful as new
    migrations land.
    """
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)
    expected_count: int

    async with (
        connect(db_path) as conn,
        conn.execute("SELECT COUNT(*) AS n FROM schema_version") as cur,
    ):
        first_row = await cur.fetchone()
    assert first_row is not None
    expected_count = int(first_row["n"])

    await init_db(db_path)

    async with (
        connect(db_path) as conn,
        conn.execute("SELECT COUNT(*) AS n FROM schema_version") as cur,
    ):
        row = await cur.fetchone()

    assert row is not None
    assert int(row["n"]) == expected_count


async def test_init_db_creates_parent_dir(tmp_path: Path) -> None:
    """Missing parent directories are created automatically."""
    db_path = tmp_path / "nested" / "deep" / "test.sqlite3"
    await init_db(db_path)
    assert db_path.exists()


async def test_connect_enables_foreign_keys(tmp_path: Path) -> None:
    """The connect helper applies PRAGMA foreign_keys = ON."""
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)

    async with connect(db_path) as conn, conn.execute("PRAGMA foreign_keys") as cur:
        row = await cur.fetchone()

    assert row is not None
    assert int(row[0]) == 1


async def test_app_meta_table_is_writable(tmp_path: Path) -> None:
    """0001 schema lets us insert + read app_meta rows."""
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)

    async with connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?)",
            ("install_id", "abc-123"),
        )
        await conn.commit()

        async with conn.execute("SELECT value FROM app_meta WHERE key = ?", ("install_id",)) as cur:
            row = await cur.fetchone()

    assert row is not None
    assert row["value"] == "abc-123"


async def test_connect_is_aiosqlite_connection(tmp_path: Path) -> None:
    """connect() yields a real aiosqlite.Connection (not a wrapper)."""
    db_path = tmp_path / "test.sqlite3"
    await init_db(db_path)

    async with connect(db_path) as conn:
        assert isinstance(conn, aiosqlite.Connection)
