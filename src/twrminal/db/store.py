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


_SESSION_COLS = (
    "id, created_at, updated_at, working_dir, model, title, max_budget_usd, total_cost_usd"
)


async def create_session(
    conn: aiosqlite.Connection,
    *,
    working_dir: str,
    model: str,
    title: str | None = None,
    max_budget_usd: float | None = None,
) -> dict[str, Any]:
    session_id = _new_id()
    now = _now()
    await conn.execute(
        "INSERT INTO sessions "
        "(id, created_at, updated_at, working_dir, model, title, max_budget_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (session_id, now, now, working_dir, model, title, max_budget_usd),
    )
    await conn.commit()
    row = await get_session(conn, session_id)
    assert row is not None  # just inserted
    return row


async def list_sessions(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions ORDER BY updated_at DESC, id DESC"
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_session(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions WHERE id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def update_session(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a partial update. `fields` maps column name → new value;
    only `title` and `max_budget_usd` are accepted. Bumps updated_at.
    Returns the refreshed row, or None if the session doesn't exist."""
    allowed = {"title", "max_budget_usd"}
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if not filtered:
        return await get_session(conn, session_id)
    assignments = ", ".join(f"{col} = ?" for col in filtered)
    params = (*filtered.values(), _now(), session_id)
    cursor = await conn.execute(
        f"UPDATE sessions SET {assignments}, updated_at = ? WHERE id = ?",
        params,
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    return await get_session(conn, session_id)


async def delete_session(conn: aiosqlite.Connection, session_id: str) -> bool:
    cursor = await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def add_session_cost(conn: aiosqlite.Connection, session_id: str, delta_usd: float) -> bool:
    """Accumulate SDK-reported cost onto the session row. Returns False if
    the session row is gone (e.g. deleted mid-stream)."""
    cursor = await conn.execute(
        "UPDATE sessions SET total_cost_usd = total_cost_usd + ? WHERE id = ?",
        (delta_usd, session_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def insert_message(
    conn: aiosqlite.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    id: str | None = None,
    thinking: str | None = None,
) -> dict[str, Any]:
    message_id = id or _new_id()
    now = _now()
    await conn.execute(
        "INSERT INTO messages (id, session_id, role, content, thinking, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (message_id, session_id, role, content, thinking, now),
    )
    # Bump the owning session's updated_at so active sessions sort to
    # the top of list_sessions. Uses a shared timestamp with the
    # message row for coherence.
    await conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    await conn.commit()
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "thinking": thinking,
        "created_at": now,
    }


async def list_messages(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    before: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Without `limit`, returns every message in the session in
    creation order — keeps the v0.1.0 behavior for small sessions.

    With `limit`, returns the N most-recent messages in newest-first
    order (so routes / callers that want oldest-first rendering
    reverse the page). Pass `before` (ISO timestamp) to fetch the
    page immediately older than a known cursor."""
    cols = "id, session_id, role, content, thinking, created_at"
    if limit is None:
        async with conn.execute(
            f"SELECT {cols} FROM messages WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        ) as cursor:
            return [dict(row) async for row in cursor]
    if before is None:
        params: tuple[Any, ...] = (session_id, limit)
        sql = (
            f"SELECT {cols} FROM messages WHERE session_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?"
        )
    else:
        params = (session_id, before, limit)
        sql = (
            f"SELECT {cols} FROM messages "
            "WHERE session_id = ? AND created_at < ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?"
        )
    async with conn.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]


async def insert_tool_call_start(
    conn: aiosqlite.Connection,
    *,
    session_id: str,
    tool_call_id: str,
    name: str,
    input_json: str,
) -> dict[str, Any]:
    now = _now()
    await conn.execute(
        "INSERT INTO tool_calls (id, session_id, name, input, started_at) VALUES (?, ?, ?, ?, ?)",
        (tool_call_id, session_id, name, input_json, now),
    )
    await conn.commit()
    return {
        "id": tool_call_id,
        "session_id": session_id,
        "message_id": None,
        "name": name,
        "input": input_json,
        "output": None,
        "error": None,
        "started_at": now,
        "finished_at": None,
    }


async def finish_tool_call(
    conn: aiosqlite.Connection,
    *,
    tool_call_id: str,
    output: str | None,
    error: str | None,
) -> bool:
    cursor = await conn.execute(
        "UPDATE tool_calls SET output = ?, error = ?, finished_at = ? WHERE id = ?",
        (output, error, _now(), tool_call_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def attach_tool_calls_to_message(
    conn: aiosqlite.Connection,
    *,
    message_id: str,
    tool_call_ids: list[str],
) -> int:
    """Backfill tool_calls.message_id for a just-persisted assistant turn.

    Called after `insert_message(role="assistant")` — at that point the
    messages row exists so the FK can be populated. Returns the number
    of rows updated.
    """
    if not tool_call_ids:
        return 0
    placeholders = ",".join("?" for _ in tool_call_ids)
    cursor = await conn.execute(
        f"UPDATE tool_calls SET message_id = ? WHERE id IN ({placeholders})",
        (message_id, *tool_call_ids),
    )
    await conn.commit()
    return cursor.rowcount


async def list_tool_calls(conn: aiosqlite.Connection, session_id: str) -> list[dict[str, Any]]:
    async with conn.execute(
        "SELECT id, session_id, message_id, name, input, output, error, "
        "started_at, finished_at "
        "FROM tool_calls WHERE session_id = ? ORDER BY started_at ASC, id ASC",
        (session_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]


def _date_filter(
    column: str, date_from: str | None, date_to: str | None
) -> tuple[str, tuple[str, ...]]:
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


async def list_all_sessions(
    conn: aiosqlite.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _date_filter("created_at", date_from, date_to)
    sql = f"SELECT {_SESSION_COLS} FROM sessions{where} ORDER BY created_at ASC, id ASC"
    async with conn.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]


async def list_all_messages(
    conn: aiosqlite.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _date_filter("created_at", date_from, date_to)
    sql = (
        "SELECT id, session_id, role, content, thinking, created_at "
        "FROM messages" + where + " ORDER BY created_at ASC, id ASC"
    )
    async with conn.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]


async def search_messages(
    conn: aiosqlite.Connection, query: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Case-insensitive LIKE match across message content and thinking,
    joined with sessions for the title. Newest matches first."""
    pattern = f"%{query}%"
    sql = (
        "SELECT m.id AS message_id, m.session_id, m.role, m.content, "
        "m.thinking, m.created_at, s.title AS session_title, s.model "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE m.content LIKE ? OR m.thinking LIKE ? "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
    )
    async with conn.execute(sql, (pattern, pattern, limit)) as cursor:
        return [dict(row) async for row in cursor]


async def list_all_tool_calls(
    conn: aiosqlite.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _date_filter("started_at", date_from, date_to)
    sql = (
        "SELECT id, session_id, message_id, name, input, output, error, "
        "started_at, finished_at "
        "FROM tool_calls" + where + " ORDER BY started_at ASC, id ASC"
    )
    async with conn.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]
