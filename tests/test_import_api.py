"""Tests for the import API route."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.db.connection import load_schema
from bearings.web.app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def app_and_db(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection, Path]]:
    """Create FastAPI app and v1 database connection."""
    db_path = tmp_path / "v1.db"
    conn = await aiosqlite.connect(db_path)
    await load_schema(conn)
    app = create_app(db_connection=conn)
    yield app, conn, tmp_path
    await conn.close()


async def _create_v0_source_db(path: Path) -> None:
    """Create a minimal v0.17-schema source database with sample data.

    Uses correct v0.17 schema: INTEGER tag PKs and TEXT ISO timestamps.
    """
    conn = await aiosqlite.connect(path)

    # Create v0.17 schema (INTEGER tag PK, TEXT ISO timestamps)
    await conn.execute(
        """
        CREATE TABLE tags (
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
        CREATE TABLE sessions (
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
        CREATE TABLE messages (
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
        CREATE TABLE session_tags (
            session_id TEXT NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (session_id, tag_id)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE tag_memories (
            tag_id INTEGER PRIMARY KEY,
            content TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE checklist_items (
            id TEXT PRIMARY KEY,
            checklist_id TEXT NOT NULL,
            parent_item_id TEXT,
            label TEXT NOT NULL,
            notes TEXT,
            checked_at TEXT,
            sort_order INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            chat_session_id TEXT,
            blocked_at TEXT,
            blocked_reason_category TEXT,
            blocked_reason_text TEXT
        )
        """
    )

    # Insert sample data: 1 tag, 1 session, 1 message
    await conn.execute(
        "INSERT INTO tags"
        " (id, name, color, created_at, default_working_dir, default_model)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (1, "Import Test", "#0000ff", "2024-01-01T00:00:00+00:00", "/home/test", "opus"),
    )
    await conn.execute(
        "INSERT INTO sessions"
        " (id, created_at, updated_at, working_dir, model, title, max_budget_usd,"
        "  total_cost_usd, description, session_instructions, permission_mode,"
        "  last_context_pct, last_context_tokens, last_context_max, closed_at,"
        "  kind, pinned, error_pending)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ses_test",
            "2024-01-01T00:00:00+00:00",
            "2024-01-02T00:00:00+00:00",
            "/home/test",
            "opus",
            "Imported Session",
            10.0,
            2.5,
            "Test description",
            "Test instructions",
            "default",
            50.0,
            5000,
            10000,
            None,
            "chat",
            0,
            0,
        ),
    )
    await conn.execute(
        "INSERT INTO messages"
        " (id, session_id, role, content, created_at, thinking,"
        "  input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,"
        "  replay_attempted_at, pinned, hidden_from_context, attachments)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "msg_test",
            "ses_test",
            "user",
            "Test message",
            "2024-01-01T01:00:00+00:00",
            None,
            100,
            200,
            0,
            0,
            None,
            0,
            0,
            None,
        ),
    )

    await conn.commit()
    await conn.close()


async def test_post_import_success(
    app_and_db: tuple[FastAPI, aiosqlite.Connection, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful import returns 200 with counts."""
    app, _dest_conn, tmp_path = app_and_db

    # Create source database with sample data
    src_path = tmp_path / "v0_source.db"
    await _create_v0_source_db(src_path)

    # Monkeypatch the source path in the import_db module
    import bearings.web.routes.import_db as import_module

    monkeypatch.setattr(import_module, "_source_db_path", lambda: src_path)

    with TestClient(app) as client:
        response = client.post("/api/import/bearings")

    assert response.status_code == 200
    data = response.json()
    assert data["tags_imported"] == 1
    assert data["sessions_imported"] == 1
    assert data["messages_imported"] == 1
    assert data["tags_skipped"] == 0
    assert data["sessions_skipped"] == 0
    assert data["messages_skipped"] == 0
    assert data["errors"] == []


async def test_post_import_no_source_file(
    app_and_db: tuple[FastAPI, aiosqlite.Connection, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing source file returns 404."""
    app, _dest_conn, tmp_path = app_and_db

    # Monkeypatch to point to a nonexistent file
    import bearings.web.routes.import_db as import_module

    monkeypatch.setattr(import_module, "_source_db_path", lambda: tmp_path / "missing.db")

    with TestClient(app) as client:
        response = client.post("/api/import/bearings")

    assert response.status_code == 404


async def test_post_import_idempotent(
    app_and_db: tuple[FastAPI, aiosqlite.Connection, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second import has skipped rows, no new imports."""
    app, _dest_conn, tmp_path = app_and_db

    # Create source database
    src_path = tmp_path / "v0_source.db"
    await _create_v0_source_db(src_path)

    # Monkeypatch the source path
    import bearings.web.routes.import_db as import_module

    monkeypatch.setattr(import_module, "_source_db_path", lambda: src_path)

    with TestClient(app) as client:
        # First import
        response1 = client.post("/api/import/bearings")
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["tags_imported"] == 1
        assert data1["sessions_imported"] == 1
        assert data1["messages_imported"] == 1

        # Second import (same source)
        response2 = client.post("/api/import/bearings")
        assert response2.status_code == 200
        data2 = response2.json()
        # All rows should be skipped (duplicate keys)
        assert data2["tags_imported"] == 0
        assert data2["tags_skipped"] == 1
        assert data2["sessions_imported"] == 0
        assert data2["sessions_skipped"] == 1
        assert data2["messages_imported"] == 0
        assert data2["messages_skipped"] == 1


__all__ = [
    "app_and_db",
    "test_post_import_idempotent",
    "test_post_import_no_source_file",
    "test_post_import_success",
]
