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


_SESSION_BASE_COLS = (
    "id, created_at, updated_at, working_dir, model, title, description, "
    "max_budget_usd, total_cost_usd"
)
_SESSION_COUNT = "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count"
_SESSION_COLS_WITH_COUNT = f"s.{_SESSION_BASE_COLS.replace(', ', ', s.')}, {_SESSION_COUNT}"


async def create_session(
    conn: aiosqlite.Connection,
    *,
    working_dir: str,
    model: str,
    title: str | None = None,
    description: str | None = None,
    max_budget_usd: float | None = None,
) -> dict[str, Any]:
    session_id = _new_id()
    now = _now()
    await conn.execute(
        "INSERT INTO sessions "
        "(id, created_at, updated_at, working_dir, model, title, description, "
        "max_budget_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, now, now, working_dir, model, title, description, max_budget_usd),
    )
    await conn.commit()
    row = await get_session(conn, session_id)
    assert row is not None  # just inserted
    return row


async def list_sessions(
    conn: aiosqlite.Connection,
    *,
    tag_ids: list[int] | None = None,
    mode: str = "any",
) -> list[dict[str, Any]]:
    """List sessions, newest-first. Optional tag filter:

    - `tag_ids=None` (default) or empty list: no tag filter applied.
    - `mode="any"`: return sessions carrying ANY of the listed tags.
    - `mode="all"`: return sessions carrying ALL of the listed tags.

    Mode is ignored when no tag ids are supplied. Ordering stays
    `updated_at DESC, id DESC` regardless.
    """
    if not tag_ids:
        sql = (
            f"SELECT {_SESSION_COLS_WITH_COUNT} FROM sessions s "
            "ORDER BY s.updated_at DESC, s.id DESC"
        )
        async with conn.execute(sql) as cursor:
            return [dict(row) async for row in cursor]

    placeholders = ",".join("?" for _ in tag_ids)
    if mode == "all":
        # HAVING COUNT(DISTINCT tag_id) == len(tag_ids) ensures every
        # required tag is present on the session.
        sql = (
            f"SELECT {_SESSION_COLS_WITH_COUNT} FROM sessions s "
            f"JOIN session_tags st ON st.session_id = s.id "
            f"WHERE st.tag_id IN ({placeholders}) "
            f"GROUP BY s.id HAVING COUNT(DISTINCT st.tag_id) = ? "
            "ORDER BY s.updated_at DESC, s.id DESC"
        )
        params: tuple[Any, ...] = (*tag_ids, len(tag_ids))
    else:
        # mode == "any" — DISTINCT + IN (...).
        sql = (
            f"SELECT DISTINCT {_SESSION_COLS_WITH_COUNT} FROM sessions s "
            f"JOIN session_tags st ON st.session_id = s.id "
            f"WHERE st.tag_id IN ({placeholders}) "
            "ORDER BY s.updated_at DESC, s.id DESC"
        )
        params = tuple(tag_ids)
    async with conn.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]


async def get_session(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        f"SELECT {_SESSION_COLS_WITH_COUNT} FROM sessions s WHERE s.id = ?",
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
    only `title`, `description`, and `max_budget_usd` are accepted. Bumps
    updated_at. Returns the refreshed row, or None if the session doesn't
    exist."""
    allowed = {"title", "description", "max_budget_usd"}
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


async def import_session(conn: aiosqlite.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """Restore a session from the v0.1.30 export shape
    ({session, messages, tool_calls}). Generates fresh ids for the
    session, every message, and every tool call — preserves content,
    role, thinking, timestamps, and the message↔tool-call relationship
    through an id-remap table. Returns the new session row.

    Does not copy `total_cost_usd` forward — the new session starts at
    zero (restores don't count as spend). `updated_at` is stamped to
    the import time so the imported session lands at the top of the
    sidebar sort."""
    src_session = payload.get("session") or {}
    src_messages = payload.get("messages") or []
    src_tool_calls = payload.get("tool_calls") or []

    new_session_id = _new_id()
    now = _now()
    created_at = str(src_session.get("created_at") or now)
    await conn.execute(
        "INSERT INTO sessions "
        "(id, created_at, updated_at, working_dir, model, title, description, "
        "max_budget_usd) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_session_id,
            created_at,
            now,
            str(src_session.get("working_dir") or "/tmp"),
            str(src_session.get("model") or "claude-sonnet-4-6"),
            src_session.get("title"),
            src_session.get("description"),
            src_session.get("max_budget_usd"),
        ),
    )

    msg_id_map: dict[str, str] = {}
    for m in src_messages:
        old_id = str(m.get("id") or "")
        new_id = _new_id()
        if old_id:
            msg_id_map[old_id] = new_id
        await conn.execute(
            "INSERT INTO messages (id, session_id, role, content, thinking, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                new_id,
                new_session_id,
                str(m.get("role") or "user"),
                str(m.get("content") or ""),
                m.get("thinking"),
                str(m.get("created_at") or _now()),
            ),
        )

    for tc in src_tool_calls:
        old_msg_id = tc.get("message_id")
        new_msg_id = msg_id_map.get(str(old_msg_id)) if old_msg_id else None
        await conn.execute(
            "INSERT INTO tool_calls "
            "(id, session_id, message_id, name, input, output, error, "
            "started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _new_id(),
                new_session_id,
                new_msg_id,
                str(tc.get("name") or ""),
                str(tc.get("input") or "{}"),
                tc.get("output"),
                tc.get("error"),
                str(tc.get("started_at") or _now()),
                tc.get("finished_at"),
            ),
        )

    await conn.commit()
    row = await get_session(conn, new_session_id)
    assert row is not None
    return row


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
    where, params = _date_filter("s.created_at", date_from, date_to)
    sql = (
        f"SELECT {_SESSION_COLS_WITH_COUNT} FROM sessions s{where} "
        "ORDER BY s.created_at ASC, s.id ASC"
    )
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


# --- Tags (v0.2.0) ----------------------------------------------------

_TAG_COLS_WITH_COUNT = (
    "t.id, t.name, t.color, t.pinned, t.sort_order, t.created_at, "
    "(SELECT COUNT(*) FROM session_tags st WHERE st.tag_id = t.id) "
    "AS session_count"
)
# Pinned tags first, then ascending sort_order, then id — the
# canonical order used for sidebar rendering and tag-memory precedence.
_TAG_ORDER = "t.pinned DESC, t.sort_order ASC, t.id ASC"


async def create_tag(
    conn: aiosqlite.Connection,
    *,
    name: str,
    color: str | None = None,
    pinned: bool = False,
    sort_order: int = 0,
) -> dict[str, Any]:
    cursor = await conn.execute(
        "INSERT INTO tags (name, color, pinned, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, color, 1 if pinned else 0, sort_order, _now()),
    )
    await conn.commit()
    tag_id = cursor.lastrowid
    assert tag_id is not None  # just inserted
    row = await get_tag(conn, tag_id)
    assert row is not None
    return row


async def list_tags(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with conn.execute(
        f"SELECT {_TAG_COLS_WITH_COUNT} FROM tags t ORDER BY {_TAG_ORDER}"
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_tag(conn: aiosqlite.Connection, tag_id: int) -> dict[str, Any] | None:
    async with conn.execute(
        f"SELECT {_TAG_COLS_WITH_COUNT} FROM tags t WHERE t.id = ?",
        (tag_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def update_tag(
    conn: aiosqlite.Connection,
    tag_id: int,
    *,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Apply a partial update. `fields` maps column name → new value.
    Only `name`, `color`, `pinned`, `sort_order` are accepted. Returns
    the refreshed row, or None if the tag doesn't exist."""
    allowed = {"name", "color", "pinned", "sort_order"}
    filtered = {k: v for k, v in fields.items() if k in allowed}
    if "pinned" in filtered:
        filtered["pinned"] = 1 if filtered["pinned"] else 0
    if not filtered:
        return await get_tag(conn, tag_id)
    assignments = ", ".join(f"{col} = ?" for col in filtered)
    params = (*filtered.values(), tag_id)
    cursor = await conn.execute(
        f"UPDATE tags SET {assignments} WHERE id = ?",
        params,
    )
    await conn.commit()
    if cursor.rowcount == 0:
        return None
    return await get_tag(conn, tag_id)


async def delete_tag(conn: aiosqlite.Connection, tag_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    await conn.commit()
    return cursor.rowcount > 0


async def attach_tag(conn: aiosqlite.Connection, session_id: str, tag_id: int) -> bool:
    """Attach a tag to a session. Idempotent — re-attaching is a no-op.
    Returns True if the session and tag both exist (so the attach is
    semantically valid), False if either is missing."""
    session_row = await conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
    if await session_row.fetchone() is None:
        return False
    tag_row = await conn.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,))
    if await tag_row.fetchone() is None:
        return False
    now = _now()
    await conn.execute(
        "INSERT OR IGNORE INTO session_tags (session_id, tag_id, created_at) VALUES (?, ?, ?)",
        (session_id, tag_id, now),
    )
    # Touch the session so it floats to the top of the sidebar when
    # tags change — mirrors insert_message's behavior.
    await conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    await conn.commit()
    return True


async def detach_tag(conn: aiosqlite.Connection, session_id: str, tag_id: int) -> bool:
    """Detach a tag from a session. Returns True if the session exists
    (so the call was well-formed), regardless of whether the pair was
    actually present — DELETE is idempotent at this layer."""
    session_row = await conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
    if await session_row.fetchone() is None:
        return False
    now = _now()
    await conn.execute(
        "DELETE FROM session_tags WHERE session_id = ? AND tag_id = ?",
        (session_id, tag_id),
    )
    await conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    await conn.commit()
    return True


async def list_session_tags(conn: aiosqlite.Connection, session_id: str) -> list[dict[str, Any]]:
    async with conn.execute(
        f"SELECT {_TAG_COLS_WITH_COUNT} FROM tags t "
        "JOIN session_tags st ON st.tag_id = t.id "
        f"WHERE st.session_id = ? ORDER BY {_TAG_ORDER}",
        (session_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]
