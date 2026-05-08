"""Schema and round-trip tests for the Phase 1 analytics tables.

Covers BEARINGS_ANALYTICS_v1.md §4.1 (five new tables) and §4.2 (FTS5
index on plug_blocks.content).

Test inventory:

1. All five analytics tables exist after ``load_schema``.
2. ``turns`` — insert + read round-trip; UNIQUE(session_id, turn_index)
   constraint; ON DELETE CASCADE from sessions.
3. ``plug_blocks`` — insert + read round-trip; hash deduplication via
   INSERT OR IGNORE; FTS5 search via the ``plug_blocks_fts`` virtual table.
4. ``session_plug_blocks`` — insert + read; FK to plug_blocks(hash).
5. ``bucket_snapshots`` — insert + read; nullable window fields.
6. ``suppressed_warnings`` — insert + read; idempotent re-suppress.
7. ``_ADDED_COLUMNS`` does NOT contain any of the five new table names
   (they land via schema.sql IF NOT EXISTS, not ALTER TABLE).
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from bearings.db import get_connection_factory, load_schema
from bearings.db.analytics import (
    BucketSnapshot,
    PlugBlock,
    SessionPlugBlock,
    SuppressedWarning,
    Turn,
    get_latest_bucket_snapshot,
    get_plug_block,
    insert_bucket_snapshot,
    insert_turn,
    is_warning_suppressed,
    list_session_plug_blocks,
    list_turns_for_session,
    record_session_plug_blocks,
    search_plug_blocks_fts,
    suppress_warning,
    upsert_plug_block,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SESS_ID = "sess-analytics-test"
_MODEL = "claude-sonnet-4-6"
_HASH_A = "a" * 64
_HASH_B = "b" * 64


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "analytics_test.db"


async def _bootstrapped(database_path: Path) -> aiosqlite.Connection:
    """Open a fresh connection with schema applied and a seed session row."""
    factory = get_connection_factory(database_path)
    conn = await factory().__aenter__()
    await load_schema(conn)
    await conn.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _SESS_ID,
            "chat",
            "Analytics test session",
            "/tmp",
            _MODEL,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    await conn.commit()
    return conn


# ---------------------------------------------------------------------------
# 1. Table existence
# ---------------------------------------------------------------------------


async def test_analytics_tables_exist(database_path: Path) -> None:
    """All five analytics tables and the FTS5 virtual table exist after load_schema."""
    factory = get_connection_factory(database_path)
    async with factory() as conn:
        await load_schema(conn)
        rows = await conn.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = {str(r[0]) for r in rows}

    expected = {
        "turns",
        "plug_blocks",
        "session_plug_blocks",
        "bucket_snapshots",
        "suppressed_warnings",
        "plug_blocks_fts",
    }
    missing = expected - table_names
    assert not missing, f"analytics tables missing from schema: {missing}"


# ---------------------------------------------------------------------------
# 2. turns — round-trip, uniqueness, cascade
# ---------------------------------------------------------------------------


async def test_turns_round_trip(database_path: Path) -> None:
    """Insert a turn and read it back with correct field values."""
    conn = await _bootstrapped(database_path)
    try:
        turn = await insert_turn(
            conn,
            session_id=_SESS_ID,
            turn_index=0,
            model=_MODEL,
            input_tokens=1000,
            output_tokens=200,
            cache_read_tokens=50,
            cache_creation_tokens=10,
            timestamp=1_700_000_000_000,
        )
        assert isinstance(turn, Turn)
        assert turn.session_id == _SESS_ID
        assert turn.turn_index == 0
        assert turn.model == _MODEL
        assert turn.input_tokens == 1000
        assert turn.output_tokens == 200
        assert turn.cache_read_tokens == 50
        assert turn.cache_creation_tokens == 10
        assert turn.timestamp == 1_700_000_000_000
    finally:
        await conn.close()


async def test_turns_list_for_session(database_path: Path) -> None:
    """list_turns_for_session returns all turns in turn_index order."""
    conn = await _bootstrapped(database_path)
    try:
        for idx in (2, 0, 1):
            await insert_turn(
                conn,
                session_id=_SESS_ID,
                turn_index=idx,
                model=_MODEL,
                input_tokens=idx * 100,
                output_tokens=idx * 10,
            )
        turns = await list_turns_for_session(conn, _SESS_ID)
        assert [t.turn_index for t in turns] == [0, 1, 2]
    finally:
        await conn.close()


async def test_turns_unique_constraint_is_idempotent(database_path: Path) -> None:
    """Inserting the same (session_id, turn_index) twice uses INSERT OR IGNORE."""
    conn = await _bootstrapped(database_path)
    try:
        first = await insert_turn(
            conn,
            session_id=_SESS_ID,
            turn_index=0,
            model=_MODEL,
            input_tokens=500,
            output_tokens=100,
            timestamp=1_700_000_000_000,
        )
        # Second insert with different token counts — OR IGNORE keeps the first.
        second = await insert_turn(
            conn,
            session_id=_SESS_ID,
            turn_index=0,
            model=_MODEL,
            input_tokens=9999,
            output_tokens=9999,
            timestamp=1_700_000_001_000,
        )
        assert first.input_tokens == 500
        assert second.input_tokens == 500  # original row preserved
    finally:
        await conn.close()


async def test_turns_cascade_on_session_delete(database_path: Path) -> None:
    """Deleting a session cascades to its turns rows."""
    conn = await _bootstrapped(database_path)
    try:
        await insert_turn(
            conn,
            session_id=_SESS_ID,
            turn_index=0,
            model=_MODEL,
            input_tokens=100,
            output_tokens=20,
        )
        await conn.execute("DELETE FROM sessions WHERE id = ?", (_SESS_ID,))
        await conn.commit()
        rows = await conn.execute_fetchall("SELECT id FROM turns WHERE session_id = ?", (_SESS_ID,))
        assert not rows, "turns should cascade-delete with session"
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 3. plug_blocks — round-trip, dedup, FTS5
# ---------------------------------------------------------------------------


async def test_plug_blocks_round_trip(database_path: Path) -> None:
    """upsert_plug_block inserts a row and returns a valid PlugBlock."""
    conn = await _bootstrapped(database_path)
    try:
        block = await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="Hello from CLAUDE.md — mentions aiosqlite",
            token_count=42,
            token_count_model=_MODEL,
            source_path="~/.claude/CLAUDE.md",
            now=1_700_000_000_000,
        )
        assert isinstance(block, PlugBlock)
        assert block.hash == _HASH_A
        assert block.block_type == "claude_md"
        assert block.token_count == 42
        assert block.source_path == "~/.claude/CLAUDE.md"
        assert block.first_seen == 1_700_000_000_000
        assert block.last_seen == 1_700_000_000_000
    finally:
        await conn.close()


async def test_plug_blocks_upsert_updates_last_seen(database_path: Path) -> None:
    """Re-upserting the same hash updates last_seen without changing first_seen."""
    conn = await _bootstrapped(database_path)
    try:
        await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="block content",
            token_count=10,
            token_count_model=_MODEL,
            now=1_700_000_000_000,
        )
        updated = await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="block content",
            token_count=10,
            token_count_model=_MODEL,
            now=1_700_000_001_000,
        )
        assert updated.first_seen == 1_700_000_000_000
        assert updated.last_seen == 1_700_000_001_000
    finally:
        await conn.close()


async def test_plug_blocks_get_returns_none_for_missing(database_path: Path) -> None:
    """get_plug_block returns None when the hash is not in the table."""
    factory = get_connection_factory(database_path)
    async with factory() as conn:
        await load_schema(conn)
        result = await get_plug_block(conn, "0" * 64)
    assert result is None


async def test_plug_blocks_fts_search(database_path: Path) -> None:
    """FTS5 search via search_plug_blocks_fts finds blocks by content keyword."""
    conn = await _bootstrapped(database_path)
    try:
        await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="This block mentions aiosqlite and nothing else",
            token_count=10,
            token_count_model=_MODEL,
        )
        await upsert_plug_block(
            conn,
            hash=_HASH_B,
            block_type="tag_memory",
            content="This block is about FastAPI endpoints",
            token_count=8,
            token_count_model=_MODEL,
        )
        hits = await search_plug_blocks_fts(conn, "aiosqlite")
        assert len(hits) == 1
        assert hits[0].hash == _HASH_A

        no_hits = await search_plug_blocks_fts(conn, "nonexistent_keyword_xyz")
        assert no_hits == []
    finally:
        await conn.close()


async def test_plug_blocks_fts_update_sync(database_path: Path) -> None:
    """FTS index stays current after an UPDATE via the sync trigger."""
    conn = await _bootstrapped(database_path)
    try:
        await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="original content with keyword BEFORE",
            token_count=5,
            token_count_model=_MODEL,
        )
        # Directly update the row to test the AFTER UPDATE trigger.
        await conn.execute(
            "UPDATE plug_blocks SET content = ? WHERE hash = ?",
            ("updated content with keyword AFTER", _HASH_A),
        )
        await conn.commit()

        hits_before = await search_plug_blocks_fts(conn, "BEFORE")
        hits_after = await search_plug_blocks_fts(conn, "AFTER")
        assert hits_before == []
        assert len(hits_after) == 1
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 4. session_plug_blocks — join table round-trip
# ---------------------------------------------------------------------------


async def test_session_plug_blocks_round_trip(database_path: Path) -> None:
    """record_session_plug_blocks inserts join rows; list retrieves them."""
    conn = await _bootstrapped(database_path)
    try:
        for h, bt in [(_HASH_A, "claude_md"), (_HASH_B, "tag_memory")]:
            await upsert_plug_block(
                conn,
                hash=h,
                block_type=bt,
                content=f"content for {h}",
                token_count=5,
                token_count_model=_MODEL,
            )
        links = await record_session_plug_blocks(
            conn, _SESS_ID, [_HASH_A, _HASH_B], injected_at=1_700_000_000_000
        )
        assert len(links) == 2
        assert all(isinstance(lk, SessionPlugBlock) for lk in links)

        fetched = await list_session_plug_blocks(conn, _SESS_ID)
        assert {lk.block_hash for lk in fetched} == {_HASH_A, _HASH_B}
    finally:
        await conn.close()


async def test_session_plug_blocks_idempotent(database_path: Path) -> None:
    """Re-recording the same session+hash pair is a no-op (INSERT OR IGNORE)."""
    conn = await _bootstrapped(database_path)
    try:
        await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="content",
            token_count=5,
            token_count_model=_MODEL,
        )
        await record_session_plug_blocks(conn, _SESS_ID, [_HASH_A])
        await record_session_plug_blocks(conn, _SESS_ID, [_HASH_A])  # idempotent

        fetched = await list_session_plug_blocks(conn, _SESS_ID)
        assert len(fetched) == 1
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 5. bucket_snapshots — nullable fields, latest-row query
# ---------------------------------------------------------------------------


async def test_bucket_snapshots_round_trip(database_path: Path) -> None:
    """insert_bucket_snapshot stores all fields; get_latest returns the newest."""
    factory = get_connection_factory(database_path)
    async with factory() as conn:
        await load_schema(conn)

        # Null snapshot (fields absent).
        snap_null = await insert_bucket_snapshot(conn, timestamp=1_700_000_000_000)
        assert isinstance(snap_null, BucketSnapshot)
        assert snap_null.five_hour_used is None
        assert snap_null.weekly_used is None

        # Full snapshot.
        snap_full = await insert_bucket_snapshot(
            conn,
            five_hour_used=50_000,
            five_hour_limit=200_000,
            weekly_used=1_000_000,
            weekly_limit=5_000_000,
            raw_response='{"ok": true}',
            timestamp=1_700_000_001_000,
        )
        assert snap_full.five_hour_used == 50_000
        assert snap_full.weekly_limit == 5_000_000

        latest = await get_latest_bucket_snapshot(conn)
        assert latest is not None
        assert latest.id == snap_full.id
        assert latest.raw_response == '{"ok": true}'


async def test_get_latest_bucket_snapshot_empty(database_path: Path) -> None:
    """get_latest_bucket_snapshot returns None on an empty table."""
    factory = get_connection_factory(database_path)
    async with factory() as conn:
        await load_schema(conn)
        result = await get_latest_bucket_snapshot(conn)
    assert result is None


# ---------------------------------------------------------------------------
# 6. suppressed_warnings — insert, idempotency, check
# ---------------------------------------------------------------------------


async def test_suppressed_warnings_round_trip(database_path: Path) -> None:
    """suppress_warning inserts a row; is_warning_suppressed confirms it."""
    conn = await _bootstrapped(database_path)
    try:
        await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="content",
            token_count=5,
            token_count_model=_MODEL,
        )
        assert not await is_warning_suppressed(conn, _HASH_A, "yellow_length")

        sw = await suppress_warning(
            conn,
            block_hash=_HASH_A,
            warning_type="yellow_length",
            suppressed_at=1_700_000_000_000,
        )
        assert isinstance(sw, SuppressedWarning)
        assert sw.block_hash == _HASH_A
        assert sw.warning_type == "yellow_length"
        assert await is_warning_suppressed(conn, _HASH_A, "yellow_length")
    finally:
        await conn.close()


async def test_suppressed_warnings_idempotent(database_path: Path) -> None:
    """Calling suppress_warning twice for the same pair is a no-op."""
    conn = await _bootstrapped(database_path)
    try:
        await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="content",
            token_count=5,
            token_count_model=_MODEL,
        )
        first = await suppress_warning(
            conn, block_hash=_HASH_A, warning_type="red_length", suppressed_at=1_000
        )
        second = await suppress_warning(
            conn, block_hash=_HASH_A, warning_type="red_length", suppressed_at=2_000
        )
        # The original suppressed_at is preserved (INSERT OR IGNORE).
        assert first.suppressed_at == second.suppressed_at == 1_000
    finally:
        await conn.close()


async def test_suppressed_warnings_cascade_on_plug_block_delete(database_path: Path) -> None:
    """Deleting a plug_block cascades to its suppressed_warnings rows."""
    conn = await _bootstrapped(database_path)
    try:
        await upsert_plug_block(
            conn,
            hash=_HASH_A,
            block_type="claude_md",
            content="content",
            token_count=5,
            token_count_model=_MODEL,
        )
        await suppress_warning(conn, block_hash=_HASH_A, warning_type="yellow_length")
        await conn.execute("DELETE FROM plug_blocks WHERE hash = ?", (_HASH_A,))
        await conn.commit()

        rows = await conn.execute_fetchall(
            "SELECT block_hash FROM suppressed_warnings WHERE block_hash = ?", (_HASH_A,)
        )
        assert not rows, "suppressed_warnings should cascade-delete with plug_block"
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# 7. _ADDED_COLUMNS does not contain analytics table names
# ---------------------------------------------------------------------------


def test_analytics_tables_not_in_added_columns() -> None:
    """New analytics tables land via schema.sql IF NOT EXISTS, not ALTER TABLE.

    Verifies that _ADDED_COLUMNS does not contain entries for any of the
    five new analytics tables — they are new tables, not new columns on
    existing tables.
    """
    from bearings.db.connection import _ADDED_COLUMNS

    analytics_tables = {
        "turns",
        "plug_blocks",
        "session_plug_blocks",
        "bucket_snapshots",
        "suppressed_warnings",
    }
    added_tables = {table for table, _col, _type in _ADDED_COLUMNS}
    overlap = analytics_tables & added_tables
    assert not overlap, f"analytics tables found in _ADDED_COLUMNS (should not be there): {overlap}"
