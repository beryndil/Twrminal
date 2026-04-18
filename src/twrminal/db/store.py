from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def init_db(path: Path) -> aiosqlite.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode = WAL")
    await conn.execute("PRAGMA foreign_keys = ON")
    await _apply_migrations(conn)
    await conn.commit()
    return conn


async def _apply_migrations(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] async for row in await conn.execute("SELECT name FROM schema_migrations")}
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if migration.name in applied:
            continue
        await conn.executescript(migration.read_text())
        await conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, datetime('now'))",
            (migration.name,),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid4().hex


async def create_session(
    conn: aiosqlite.Connection,
    *,
    working_dir: str,
    model: str,
    title: str | None = None,
) -> dict[str, Any]:
    session_id = _new_id()
    now = _now()
    await conn.execute(
        "INSERT INTO sessions (id, created_at, updated_at, working_dir, model, title) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, now, now, working_dir, model, title),
    )
    await conn.commit()
    row = await get_session(conn, session_id)
    assert row is not None  # just inserted
    return row


async def list_sessions(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with conn.execute(
        "SELECT id, created_at, updated_at, working_dir, model, title "
        "FROM sessions ORDER BY created_at DESC, id DESC"
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_session(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        "SELECT id, created_at, updated_at, working_dir, model, title FROM sessions WHERE id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def delete_session(conn: aiosqlite.Connection, session_id: str) -> bool:
    cursor = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def insert_message(
    conn: aiosqlite.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
) -> dict[str, Any]:
    message_id = _new_id()
    now = _now()
    await conn.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (message_id, session_id, role, content, now),
    )
    await conn.commit()
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": now,
    }


async def list_messages(conn: aiosqlite.Connection, session_id: str) -> list[dict[str, Any]]:
    async with conn.execute(
        "SELECT id, session_id, role, content, created_at "
        "FROM messages WHERE session_id = ? ORDER BY created_at ASC, id ASC",
        (session_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]
