"""Tests for the Bearings database import layer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
import pytest

from bearings.db.import_bearings import import_from_bearings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def dest(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Destination (v1) database connection with fresh schema."""
    from bearings.db.connection import load_schema

    db_path = tmp_path / "dest.db"
    async with aiosqlite.connect(db_path) as conn:
        await load_schema(conn)
        yield conn


async def _create_source_db(path: Path) -> aiosqlite.Connection:
    """Create a minimal v0.17-schema source database.

    Uses TEXT ISO timestamps (as v0.17 stored them) and INTEGER tag IDs
    (matching v0.17's integer PK on tags).
    """
    conn = await aiosqlite.connect(path)
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            color TEXT,
            created_at TEXT NOT NULL,
            default_working_dir TEXT,
            default_model TEXT
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            working_dir TEXT,
            model TEXT,
            title TEXT,
            max_budget_usd REAL,
            total_cost_usd REAL,
            description TEXT,
            session_instructions TEXT,
            permission_mode TEXT,
            last_context_pct REAL,
            last_context_tokens INTEGER,
            last_context_max INTEGER,
            closed_at TEXT,
            kind TEXT,
            pinned INTEGER DEFAULT 0,
            error_pending INTEGER DEFAULT 0
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            created_at TEXT NOT NULL,
            thinking TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_creation_tokens INTEGER,
            replay_attempted_at TEXT,
            pinned INTEGER DEFAULT 0,
            hidden_from_context INTEGER DEFAULT 0,
            attachments TEXT
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_tags (
            session_id TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (session_id, tag_id)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tag_memories (
            tag_id INTEGER PRIMARY KEY,
            content TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS checklist_items (
            id INTEGER PRIMARY KEY,
            checklist_id TEXT NOT NULL,
            parent_item_id INTEGER,
            label TEXT NOT NULL,
            notes TEXT,
            sort_order INTEGER DEFAULT 0,
            checked_at TEXT,
            chat_session_id TEXT,
            blocked_at TEXT,
            blocked_reason_category TEXT,
            blocked_reason_text TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    await conn.commit()
    return conn


async def test_source_not_found(dest: aiosqlite.Connection) -> None:
    """Import from nonexistent source raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        await import_from_bearings(
            dest=dest,
            source_path=Path("/nonexistent/path/db.sqlite"),
        )


async def test_import_empty_source(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Import from empty source returns zero counts, no errors."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.tags_imported == 0
    assert result.sessions_imported == 0
    assert result.messages_imported == 0
    assert result.session_tags_imported == 0
    assert result.tag_memories_imported == 0
    assert result.checklist_items_imported == 0
    assert result.errors == []


async def test_import_tags(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Import tags with column mapping: default_working_dir → working_dir."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)
    await src.execute(
        "INSERT INTO tags (id, name, color, created_at, default_working_dir, default_model)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Test Tag", "#ff0000", "2024-01-01T00:00:00+00:00", "/home/user/proj", "sonnet"),
    )
    await src.commit()
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.tags_imported == 1
    assert result.tags_skipped == 0

    # Verify the tag in dest has correct mapping
    async with dest.execute(
        "SELECT id, name, color, created_at, updated_at, working_dir, default_model"
        " FROM tags WHERE id = 1"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    tag_id, name, color, created_at, updated_at, working_dir, _default_model = row
    assert tag_id == 1
    assert name == "Test Tag"
    assert color == "#ff0000"
    assert working_dir == "/home/user/proj"  # mapped from default_working_dir
    assert updated_at == created_at  # synthesized


async def test_import_sessions(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Import sessions with schema transformation."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)
    await src.execute(
        "INSERT INTO sessions"
        " (id, created_at, updated_at, working_dir, model, title, max_budget_usd,"
        "  total_cost_usd, description, session_instructions, permission_mode,"
        "  last_context_pct, last_context_tokens, last_context_max, closed_at,"
        "  kind, pinned, error_pending)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ses_123",
            "2024-01-01T00:00:00+00:00",
            "2024-01-02T00:00:00+00:00",
            "/home/user",
            "opus",
            "My Session",
            10.0,
            5.0,
            "Test description",
            "Test instructions",
            "bypassPermissions",
            50.0,
            5000,
            10000,
            None,
            "chat",
            1,
            0,
        ),
    )
    await src.commit()
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.sessions_imported == 1
    assert result.sessions_skipped == 0

    # Verify the session in dest
    async with dest.execute(
        "SELECT id, created_at, updated_at, model, title, message_count, closing_summary"
        " FROM sessions WHERE id = 'ses_123'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    (
        session_id,
        _created_at,
        _updated_at,
        model,
        title,
        message_count,
        closing_summary,
    ) = row
    assert session_id == "ses_123"
    assert model == "opus"
    assert title == "My Session"
    assert message_count == 0  # default for imported sessions
    assert closing_summary is None  # default for imported sessions


async def test_import_sessions_null_title_coerced(
    tmp_path: Path, dest: aiosqlite.Connection
) -> None:
    """NULL title in v0 is coerced to '(untitled)' on import."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)
    await src.execute(
        "INSERT INTO sessions"
        " (id, created_at, updated_at, working_dir, model, title, kind)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "ses_null_title",
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            "/home/user",
            "haiku",
            None,
            "chat",
        ),
    )
    await src.commit()
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.sessions_imported == 1

    async with dest.execute("SELECT title FROM sessions WHERE id = 'ses_null_title'") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "(untitled)"


async def test_import_messages(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Import messages with v0-to-v1 column transformation."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)

    # First create a session in dest (messages FK to sessions)
    await dest.execute(
        "INSERT INTO sessions"
        " (id, created_at, updated_at, model, kind, title, working_dir)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "ses_123",
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            "opus",
            "chat",
            "Test",
            "/tmp",
        ),
    )
    await dest.commit()  # close implicit transaction before import starts its own BEGIN

    # Insert message in source (with v0-specific extra columns that get dropped)
    await src.execute(
        "INSERT INTO messages"
        " (id, session_id, role, content, created_at, thinking,"
        "  input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,"
        "  replay_attempted_at, pinned, hidden_from_context, attachments)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "msg_1",
            "ses_123",
            "user",
            "Hello",
            "2024-01-01T01:00:00+00:00",
            None,
            10,
            20,
            0,
            0,
            None,
            0,
            0,
            None,
        ),
    )
    await src.commit()
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.messages_imported == 1
    assert result.messages_skipped == 0

    # Verify the message in dest (v1 columns only)
    async with dest.execute(
        "SELECT id, session_id, role, content, input_tokens, routing_source"
        " FROM messages WHERE id = 'msg_1'"
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    msg_id, session_id, role, content, input_tokens, routing_source = row
    assert msg_id == "msg_1"
    assert session_id == "ses_123"
    assert role == "user"
    assert content == "Hello"
    assert input_tokens == 10
    assert routing_source is None  # only assistant messages get 'unknown_legacy'


async def test_import_messages_assistant_gets_legacy_routing(
    tmp_path: Path, dest: aiosqlite.Connection
) -> None:
    """Assistant messages get routing_source='unknown_legacy' on import."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)

    await dest.execute(
        "INSERT INTO sessions"
        " (id, created_at, updated_at, model, kind, title, working_dir)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "ses_a",
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            "opus",
            "chat",
            "T",
            "/",
        ),
    )
    await dest.commit()  # close implicit transaction before import starts its own BEGIN
    await src.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        ("msg_a", "ses_a", "assistant", "Hi there", "2024-01-01T01:00:00+00:00"),
    )
    await src.commit()
    await src.close()

    await import_from_bearings(dest=dest, source_path=src_path)

    async with dest.execute("SELECT routing_source FROM messages WHERE id = 'msg_a'") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "unknown_legacy"


async def test_import_session_tags(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Import session_tags (requires tag and session in dest)."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)

    # Create tag and session in dest (must satisfy v1 NOT NULL constraints)
    await dest.execute(
        "INSERT INTO tags (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (1, "Test", "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
    )
    await dest.execute(
        "INSERT INTO sessions"
        " (id, created_at, updated_at, model, kind, title, working_dir)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "ses_1",
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            "sonnet",
            "chat",
            "T",
            "/",
        ),
    )
    await dest.commit()  # close implicit transaction before import starts its own BEGIN

    # Insert in source (tag_id is INTEGER in v0 too)
    await src.execute(
        "INSERT INTO session_tags (session_id, tag_id, created_at) VALUES (?, ?, ?)",
        ("ses_1", 1, "2024-01-01T00:00:00+00:00"),
    )
    await src.commit()
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.session_tags_imported == 1
    assert result.session_tags_skipped == 0


async def test_import_tag_memories(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Import tag_memories (requires tag in dest)."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)

    # Create tag in dest
    await dest.execute(
        "INSERT INTO tags (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (1, "Test", "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
    )
    await dest.commit()  # close implicit transaction before import starts its own BEGIN

    # Insert memory in source (tag_id is INTEGER)
    await src.execute(
        "INSERT INTO tag_memories (tag_id, content, updated_at) VALUES (?, ?, ?)",
        (1, "Some memory content", "2024-01-01T00:00:00+00:00"),
    )
    await src.commit()
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.tag_memories_imported == 1
    assert result.tag_memories_skipped == 0

    # Verify the memory in dest — v1 schema uses ``body`` not ``content``
    async with dest.execute("SELECT tag_id, body FROM tag_memories WHERE tag_id = 1") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    tag_id, body = row
    assert tag_id == 1
    assert body == "Some memory content"


async def test_import_checklist_items(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Import checklist_items (requires checklist session in dest)."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)

    # Create checklist session in dest
    await dest.execute(
        "INSERT INTO sessions"
        " (id, created_at, updated_at, model, kind, title, working_dir)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "check_1",
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            "sonnet",
            "checklist",
            "Checklist",
            "/",
        ),
    )
    await dest.commit()  # close implicit transaction before import starts its own BEGIN

    # Insert item in source (v0 uses INTEGER id, matching v1's INTEGER PRIMARY KEY)
    await src.execute(
        "INSERT INTO checklist_items"
        " (id, checklist_id, parent_item_id, label, notes, sort_order, checked_at,"
        "  chat_session_id, blocked_at, blocked_reason_category, blocked_reason_text,"
        "  created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            1,
            "check_1",
            None,
            "Test Item",
            "Notes",
            0,
            None,
            None,
            None,
            None,
            None,
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
        ),
    )
    await src.commit()
    await src.close()

    result = await import_from_bearings(dest=dest, source_path=src_path)

    assert result.checklist_items_imported == 1
    assert result.checklist_items_skipped == 0


async def test_idempotent_reimport(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """Second import of same data results in skipped rows."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)
    await src.execute(
        "INSERT INTO tags (id, name, color, created_at, default_working_dir, default_model)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Test Tag", "#ff0000", "2024-01-01T00:00:00+00:00", "/home", "sonnet"),
    )
    await src.commit()
    await src.close()

    # First import
    result1 = await import_from_bearings(dest=dest, source_path=src_path)
    assert result1.tags_imported == 1
    assert result1.tags_skipped == 0

    # Second import (same source, same dest)
    result2 = await import_from_bearings(dest=dest, source_path=src_path)
    assert result2.tags_imported == 0
    assert result2.tags_skipped == 1  # duplicate key, ignored


async def test_on_progress_called(tmp_path: Path, dest: aiosqlite.Connection) -> None:
    """on_progress callback is called for each table."""
    src_path = tmp_path / "src.db"
    src = await _create_source_db(src_path)
    await src.execute(
        "INSERT INTO tags (id, name, color, created_at, default_working_dir, default_model)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Test Tag", "#ff0000", "2024-01-01T00:00:00+00:00", "/home", "sonnet"),
    )
    await src.commit()
    await src.close()

    tables_called: list[str] = []

    async def on_progress(table: str, imported: int, skipped: int) -> None:
        tables_called.append(table)

    await import_from_bearings(
        dest=dest,
        source_path=src_path,
        on_progress=on_progress,
    )

    # Callback should be called for each table, even if counts are 0
    assert "tags" in tables_called
    assert "sessions" in tables_called
    assert "messages" in tables_called
    assert "session_tags" in tables_called
    assert "tag_memories" in tables_called
    assert "checklist_items" in tables_called


__all__ = [
    "dest",
    "test_idempotent_reimport",
    "test_import_checklist_items",
    "test_import_empty_source",
    "test_import_messages",
    "test_import_messages_assistant_gets_legacy_routing",
    "test_import_session_tags",
    "test_import_sessions",
    "test_import_sessions_null_title_coerced",
    "test_import_tag_memories",
    "test_import_tags",
    "test_on_progress_called",
    "test_source_not_found",
]
