"""Tags, session_tags, tag_memories. Everything tag-adjacent lives
here since the three tables are tightly coupled:

- session_tags FKs to both sessions and tags, cascade-on-delete.
- tag_memories is PK=FK to tags, cascade-on-delete.
- Canonical tag ordering (`_TAG_ORDER`) is used everywhere tags are
  rendered (sidebar list, per-session list) and is also the tag-
  memory precedence rule.
"""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _now

TAG_COLS_WITH_COUNT = (
    "t.id, t.name, t.color, t.pinned, t.sort_order, t.created_at, "
    "t.default_working_dir, t.default_model, "
    "(SELECT COUNT(*) FROM session_tags st WHERE st.tag_id = t.id) "
    "AS session_count, "
    # Open-only partition of session_count. The sidebar shows this in
    # green to the left of the total so Daisy can see at a glance which
    # tags have live work vs. archived work. Joins sessions to filter
    # by closed_at IS NULL (migration 0015's lifecycle flag).
    "(SELECT COUNT(*) FROM session_tags st "
    "JOIN sessions s ON s.id = st.session_id "
    "WHERE st.tag_id = t.id AND s.closed_at IS NULL) "
    "AS open_session_count"
)
# Pinned tags first, then ascending sort_order, then id — the canonical
# order used for sidebar rendering and tag-memory precedence.
TAG_ORDER = "t.pinned DESC, t.sort_order ASC, t.id ASC"


async def create_tag(
    conn: aiosqlite.Connection,
    *,
    name: str,
    color: str | None = None,
    pinned: bool = False,
    sort_order: int = 0,
    default_working_dir: str | None = None,
    default_model: str | None = None,
) -> dict[str, Any]:
    cursor = await conn.execute(
        "INSERT INTO tags "
        "(name, color, pinned, sort_order, created_at, "
        "default_working_dir, default_model) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            color,
            1 if pinned else 0,
            sort_order,
            _now(),
            default_working_dir,
            default_model,
        ),
    )
    await conn.commit()
    tag_id = cursor.lastrowid
    assert tag_id is not None  # just inserted
    row = await get_tag(conn, tag_id)
    assert row is not None
    return row


async def list_tags(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with conn.execute(
        f"SELECT {TAG_COLS_WITH_COUNT} FROM tags t ORDER BY {TAG_ORDER}"
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_tag(conn: aiosqlite.Connection, tag_id: int) -> dict[str, Any] | None:
    async with conn.execute(
        f"SELECT {TAG_COLS_WITH_COUNT} FROM tags t WHERE t.id = ?",
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
    Only `name`, `color`, `pinned`, `sort_order`, `default_working_dir`,
    and `default_model` are accepted. Returns the refreshed row, or
    None if the tag doesn't exist."""
    allowed = {
        "name",
        "color",
        "pinned",
        "sort_order",
        "default_working_dir",
        "default_model",
    }
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


async def list_session_ids_for_tag(conn: aiosqlite.Connection, tag_id: int) -> list[str]:
    """Return every session id currently attached to `tag_id`. Used by
    the tag-memory edit routes to decide whose runner needs to be
    respawned so its system prompt picks up the new memory content on
    the next turn. Cheap — one indexed scan on session_tags.tag_id."""
    async with conn.execute(
        "SELECT session_id FROM session_tags WHERE tag_id = ?",
        (tag_id,),
    ) as cursor:
        return [row["session_id"] async for row in cursor]


async def list_session_tags(conn: aiosqlite.Connection, session_id: str) -> list[dict[str, Any]]:
    async with conn.execute(
        f"SELECT {TAG_COLS_WITH_COUNT} FROM tags t "
        "JOIN session_tags st ON st.tag_id = t.id "
        f"WHERE st.session_id = ? ORDER BY {TAG_ORDER}",
        (session_id,),
    ) as cursor:
        return [dict(row) async for row in cursor]


async def get_tag_memory(conn: aiosqlite.Connection, tag_id: int) -> dict[str, Any] | None:
    """Return `{tag_id, content, updated_at}` for the given tag, or
    None if the tag has no memory (or doesn't exist — callers route
    that to 404)."""
    async with conn.execute(
        "SELECT tag_id, content, updated_at FROM tag_memories WHERE tag_id = ?",
        (tag_id,),
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row is not None else None


async def put_tag_memory(
    conn: aiosqlite.Connection, tag_id: int, content: str
) -> dict[str, Any] | None:
    """Upsert the tag's memory. Returns None if the tag doesn't exist
    (so the FK would fail); otherwise returns the stored row."""
    tag_row = await conn.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,))
    if await tag_row.fetchone() is None:
        return None
    await conn.execute(
        "INSERT INTO tag_memories (tag_id, content, updated_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(tag_id) DO UPDATE SET content = excluded.content, "
        "updated_at = excluded.updated_at",
        (tag_id, content, _now()),
    )
    await conn.commit()
    return await get_tag_memory(conn, tag_id)


async def delete_tag_memory(conn: aiosqlite.Connection, tag_id: int) -> bool:
    cursor = await conn.execute("DELETE FROM tag_memories WHERE tag_id = ?", (tag_id,))
    await conn.commit()
    return cursor.rowcount > 0
