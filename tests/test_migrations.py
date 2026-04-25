"""Tests for the schema_migrations checksum + drift-detection logic
(2026-04-21 security audit §4).

The migration runner must:
  - Record a sha256 of each migration file alongside the row.
  - Backfill a NULL checksum on startup (preserves DBs created before
    the machinery existed).
  - Refuse to start when a row names a migration file that's missing
    on disk (code downgrade / deleted file).
  - Refuse to start when the stored checksum doesn't match the current
    file's content (someone edited a migration after it ran).
  - Remain idempotent across repeated `init_db` calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import aiosqlite
import pytest

from bearings.db._common import (
    MIGRATIONS_DIR,
    MigrationDriftError,
    _apply_migrations,
    init_db,
)


def _digest(name: str) -> str:
    return hashlib.sha256((MIGRATIONS_DIR / name).read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_checksum_recorded_on_fresh_apply(tmp_path: Path) -> None:
    """Every migration applied against a fresh DB must land with its
    current sha256 recorded."""
    conn = await init_db(tmp_path / "fresh.sqlite")
    try:
        async with conn.execute(
            "SELECT name, checksum FROM schema_migrations ORDER BY name"
        ) as cur:
            rows = [(r[0], r[1]) async for r in cur]
        assert rows, "fresh init should record at least one migration"
        for name, stored in rows:
            assert stored == _digest(name), f"{name} checksum mismatch on fresh apply"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_null_checksum_is_backfilled(tmp_path: Path) -> None:
    """Pre-2026-04-23 DBs have applied rows without a checksum. On
    next boot the runner backfills those rows from the current file
    rather than rejecting them — by construction the DB state matches
    the file content already (the migration was applied from that
    file). Simulated here by NULLing an existing checksum."""
    db_path = tmp_path / "old.sqlite"
    conn = await init_db(db_path)
    try:
        await conn.execute(
            "UPDATE schema_migrations SET checksum = NULL WHERE name = ?",
            ("0001_initial.sql",),
        )
        await conn.commit()
    finally:
        await conn.close()

    conn2 = await init_db(db_path)
    try:
        async with conn2.execute(
            "SELECT checksum FROM schema_migrations WHERE name = ?",
            ("0001_initial.sql",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == _digest("0001_initial.sql"), "NULL checksum was not backfilled"
    finally:
        await conn2.close()


@pytest.mark.asyncio
async def test_unknown_applied_row_is_fatal(tmp_path: Path) -> None:
    """A row whose `name` isn't present in MIGRATIONS_DIR is a signal
    that either the code was downgraded or a file was deleted. Either
    way, continuing would run against an unknown schema — refuse to
    start."""
    db_path = tmp_path / "ghost.sqlite"
    conn = await init_db(db_path)
    try:
        await conn.execute(
            "INSERT INTO schema_migrations (name, applied_at, checksum) "
            "VALUES (?, datetime('now'), ?)",
            ("9999_from_the_future.sql", "deadbeef"),
        )
        await conn.commit()
    finally:
        await conn.close()

    with pytest.raises(MigrationDriftError) as excinfo:
        await init_db(db_path)
    assert "9999_from_the_future.sql" in str(excinfo.value)
    assert "Refusing to start" in str(excinfo.value)


@pytest.mark.asyncio
async def test_checksum_mismatch_is_fatal(tmp_path: Path) -> None:
    """Stored checksum differs from the current file hash → someone
    edited a migration after application. The DB no longer reflects
    the file, so halt rather than silently drift further."""
    db_path = tmp_path / "drift.sqlite"
    conn = await init_db(db_path)
    try:
        await conn.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE name = ?",
            ("0" * 64, "0001_initial.sql"),
        )
        await conn.commit()
    finally:
        await conn.close()

    with pytest.raises(MigrationDriftError) as excinfo:
        await init_db(db_path)
    msg = str(excinfo.value)
    assert "0001_initial.sql" in msg
    assert "edited after it ran" in msg


@pytest.mark.asyncio
async def test_repeat_init_is_idempotent_with_checksums(tmp_path: Path) -> None:
    """Back-to-back `init_db` calls must not re-insert rows or change
    stored checksums. Mirrors `test_store.test_init_db_is_idempotent`
    but also verifies the checksum-pass side effect is a no-op on a
    clean DB."""
    db_path = tmp_path / "idem.sqlite"
    conn1 = await init_db(db_path)
    try:
        async with conn1.execute(
            "SELECT name, checksum FROM schema_migrations ORDER BY name"
        ) as cur:
            before = [(r[0], r[1]) async for r in cur]
    finally:
        await conn1.close()

    conn2 = await init_db(db_path)
    try:
        async with conn2.execute(
            "SELECT name, checksum FROM schema_migrations ORDER BY name"
        ) as cur:
            after = [(r[0], r[1]) async for r in cur]
    finally:
        await conn2.close()

    assert before == after


@pytest.mark.asyncio
async def test_migrations_table_upgraded_in_place(tmp_path: Path) -> None:
    """A DB created with the pre-checksum shape (no `checksum` column)
    is upgraded via `ALTER TABLE ADD COLUMN` and then populated on the
    next `_apply_migrations` pass. Simulated by creating the table in
    its historical shape before init_db runs — including actually
    executing 0001's SQL so later migrations (which ALTER tables from
    0001) find what they need."""
    db_path = tmp_path / "legacy.sqlite"
    conn = await aiosqlite.connect(db_path)
    try:
        await conn.execute(
            "CREATE TABLE schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        # Actually run 0001 so the schema it creates exists, matching
        # what a legacy DB would look like — the row below asserts it
        # was applied, and that assertion must be true for the rest of
        # the chain to make sense.
        await conn.executescript((MIGRATIONS_DIR / "0001_initial.sql").read_text())
        await conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, datetime('now'))",
            ("0001_initial.sql",),
        )
        await conn.commit()
    finally:
        await conn.close()

    # init_db should: add the column, backfill the checksum, and apply
    # every other migration on top. The 0001 row survives with its
    # checksum filled in.
    conn2 = await init_db(db_path)
    try:
        async with conn2.execute(
            "SELECT checksum FROM schema_migrations WHERE name = ?",
            ("0001_initial.sql",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == _digest("0001_initial.sql")
    finally:
        await conn2.close()


@pytest.mark.asyncio
async def test_apply_migrations_can_be_called_on_open_connection(tmp_path: Path) -> None:
    """Direct coverage of `_apply_migrations` without going through
    `init_db`. Mirrors how future tests or tooling might invoke the
    runner against a prepared connection."""
    conn = await aiosqlite.connect(tmp_path / "direct.sqlite")
    try:
        await _apply_migrations(conn)
        await conn.commit()
        async with conn.execute("SELECT count(*) FROM schema_migrations") as cur:
            row = await cur.fetchone()
        assert row is not None and row[0] == len(list(MIGRATIONS_DIR.glob("*.sql")))
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_init_db_clamps_db_and_sidecars_to_0600(tmp_path: Path) -> None:
    """2026-04-21 security audit §2: the SQLite file and its WAL/SHM
    sidecars must not be world- or group-readable after init. Skips
    when the test filesystem doesn't honor unix perms (Windows, some
    tmpfs configs) — the check returns `0o666` or similar and chmod
    can't narrow it."""
    import stat
    import sys

    if sys.platform.startswith("win"):
        pytest.skip("POSIX-only permission check")

    db_path = tmp_path / "perms.sqlite"
    conn = await init_db(db_path)
    try:
        # Force a WAL/SHM pair to exist by issuing a write.
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS _probe(x INTEGER PRIMARY KEY)",
        )
        await conn.commit()
    finally:
        await conn.close()

    # Re-run init_db to exercise the idempotent re-clamp path and to
    # catch sidecars the second connect creates.
    conn = await init_db(db_path)
    await conn.close()

    for name in (db_path.name, db_path.name + "-wal", db_path.name + "-shm"):
        p = tmp_path / name
        if not p.exists():
            continue
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == 0o600, f"{name} is {oct(mode)}, expected 0o600"


@pytest.mark.asyncio
async def test_permission_mode_check_constraint_blocks_invalid_writes(
    tmp_path: Path,
) -> None:
    """Migration 0030 wires triggers that ABORT any INSERT or UPDATE
    landing a non-NULL `permission_mode` outside the four
    PermissionMode literals. The Python-side `set_session_permission_mode`
    helper rejects bad values too, but the trigger is the safety net for
    any path that bypasses it (security audit 2026-04-21 §2)."""
    from bearings.db.store import create_session, init_db

    conn = await init_db(tmp_path / "pm.sqlite")
    try:
        sess = await create_session(conn, working_dir="/tmp", model="m")
        # Direct UPDATE bypassing the helper — the trigger must reject.
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "UPDATE sessions SET permission_mode = ? WHERE id = ?",
                ("definitely-not-a-mode", sess["id"]),
            )
            await conn.commit()
        # NULL stays valid (== "default" semantics) and the four
        # documented modes round-trip cleanly.
        for mode in ("default", "plan", "acceptEdits", "bypassPermissions", None):
            await conn.execute(
                "UPDATE sessions SET permission_mode = ? WHERE id = ?",
                (mode, sess["id"]),
            )
            await conn.commit()
    finally:
        await conn.close()
