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
    "t.default_working_dir, t.default_model, t.tag_group, "
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

# Name of the tag that auto-attaches to every newly-created session
# that didn't explicitly request a severity (migration 0021 / v0.8.x
# design). Looked up by name so the user can recolor / reorder / rename
# any of the seeded severity tags without a code change — but renaming
# this one specifically breaks the auto-attach, which is an intentional
# part of the "physical law, not DB constraint" design: if the user
# kills the default, new sessions simply land without a severity.
_DEFAULT_SEVERITY_NAME = "Low"


async def create_tag(
    conn: aiosqlite.Connection,
    *,
    name: str,
    color: str | None = None,
    pinned: bool = False,
    sort_order: int = 0,
    default_working_dir: str | None = None,
    default_model: str | None = None,
    tag_group: str = "general",
) -> dict[str, Any]:
    cursor = await conn.execute(
        "INSERT INTO tags "
        "(name, color, pinned, sort_order, created_at, "
        "default_working_dir, default_model, tag_group) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            color,
            1 if pinned else 0,
            sort_order,
            _now(),
            default_working_dir,
            default_model,
            tag_group,
        ),
    )
    await conn.commit()
    tag_id = cursor.lastrowid
    assert tag_id is not None  # just inserted
    row = await get_tag(conn, tag_id)
    assert row is not None
    return row


async def list_tags(
    conn: aiosqlite.Connection,
    *,
    scope_tag_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """List every tag with its session counts.

    `scope_tag_ids` narrows the severity-group counts to match the
    sidebar's v0.7.4 semantics — each severity's count reflects how
    many sessions would show up if that severity were added to the
    current general-tag filter (which is OR across the scope). The
    contract:

    - `None` (default / legacy): both severity and general counts are
      absolute over the full session set. Preserves behavior for
      callers that just want a tag inventory.
    - `[]` (scoped, no general tags picked): severity counts are all
      0 — the sidebar is about to show zero sessions anyway, so the
      numbers should reflect that. General counts stay absolute so
      the user still sees how full each tag is and can pick one.
    - `[a, b, ...]` (scoped, general tags picked): severity counts =
      sessions matching (any of the scope ids) AND carrying that
      severity. General counts stay absolute.

    The CASE-WHEN lets us keep a single query — the general-tag
    branch always falls through to the absolute count so creating /
    deleting a scope doesn't ripple through the general list's
    numbers.
    """
    if scope_tag_ids is None:
        async with conn.execute(
            f"SELECT {TAG_COLS_WITH_COUNT} FROM tags t ORDER BY {TAG_ORDER}"
        ) as cursor:
            return [dict(row) async for row in cursor]

    # Build the scoped SELECT. Empty scope → severity counts collapse
    # to literal 0 (no valid `IN ()` syntax in SQLite); non-empty scope
    # narrows via an IN-subquery against session_tags. General counts
    # are always absolute — the scope only affects severity tags.
    if not scope_tag_ids:
        severity_total = "0"
        severity_open = "0"
        scope_params: list[Any] = []
    else:
        scope_ph = ",".join("?" for _ in scope_tag_ids)
        severity_total = (
            f"(SELECT COUNT(*) FROM session_tags st "
            f"WHERE st.tag_id = t.id "
            f"AND st.session_id IN ("
            f"SELECT session_id FROM session_tags WHERE tag_id IN ({scope_ph})))"
        )
        severity_open = (
            f"(SELECT COUNT(*) FROM session_tags st "
            f"JOIN sessions s ON s.id = st.session_id "
            f"WHERE st.tag_id = t.id AND s.closed_at IS NULL "
            f"AND st.session_id IN ("
            f"SELECT session_id FROM session_tags WHERE tag_id IN ({scope_ph})))"
        )
        # Two appearances of `scope_tag_ids` in the assembled SQL
        # (one per severity count column) — pass the ids twice.
        scope_params = list(scope_tag_ids) * 2

    general_total = "(SELECT COUNT(*) FROM session_tags st WHERE st.tag_id = t.id)"
    general_open = (
        "(SELECT COUNT(*) FROM session_tags st "
        "JOIN sessions s ON s.id = st.session_id "
        "WHERE st.tag_id = t.id AND s.closed_at IS NULL)"
    )
    sql = (
        "SELECT t.id, t.name, t.color, t.pinned, t.sort_order, t.created_at, "
        "t.default_working_dir, t.default_model, t.tag_group, "
        f"CASE WHEN t.tag_group = 'severity' THEN {severity_total} "
        f"ELSE {general_total} END AS session_count, "
        f"CASE WHEN t.tag_group = 'severity' THEN {severity_open} "
        f"ELSE {general_open} END AS open_session_count "
        f"FROM tags t ORDER BY {TAG_ORDER}"
    )
    async with conn.execute(sql, scope_params) as cursor:
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
    `default_model`, and `tag_group` are accepted. Returns the refreshed
    row, or None if the tag doesn't exist. `tag_group` is CHECK-
    constrained at the DB layer, so an invalid value (e.g. 'urgent')
    raises IntegrityError rather than landing silently."""
    allowed = {
        "name",
        "color",
        "pinned",
        "sort_order",
        "default_working_dir",
        "default_model",
        "tag_group",
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
    semantically valid), False if either is missing.

    Severity-group invariant (migration 0021): a session carries at
    most one severity tag. Attaching a tag whose `tag_group='severity'`
    first detaches every other severity tag from the session inside
    the same commit, so "switch from Critical to Blocker" is one round
    trip and never transiently exposes two severities. Attaching the
    same severity tag twice is an idempotent no-op (the INSERT OR
    IGNORE preserves the existing row)."""
    session_row = await conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
    if await session_row.fetchone() is None:
        return False
    tag_row = await conn.execute("SELECT tag_group FROM tags WHERE id = ?", (tag_id,))
    tag_hit = await tag_row.fetchone()
    if tag_hit is None:
        return False
    now = _now()
    if tag_hit["tag_group"] == "severity":
        # Swap semantics: detach any other severity tag this session
        # already has before attaching the new one. The self-detach
        # (when tag_id is the currently-attached severity) is a no-op
        # thanks to the `tag_id != ?` clause, which also means a
        # re-attach of the same severity tag skips the delete entirely
        # and falls through to the idempotent INSERT OR IGNORE below.
        await conn.execute(
            "DELETE FROM session_tags WHERE session_id = ? "
            "AND tag_id != ? "
            "AND tag_id IN (SELECT id FROM tags WHERE tag_group = 'severity')",
            (session_id, tag_id),
        )
    await conn.execute(
        "INSERT OR IGNORE INTO session_tags (session_id, tag_id, created_at) VALUES (?, ?, ?)",
        (session_id, tag_id, now),
    )
    # Touch the session so it floats to the top of the sidebar when
    # tags change — mirrors insert_message's behavior.
    await conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
    await conn.commit()
    return True


async def get_default_severity_tag_id(conn: aiosqlite.Connection) -> int | None:
    """Return the id of the default severity tag ('Low'), or None if
    the user has deleted or renamed it. Used by the session-create
    route to auto-attach a severity when the caller didn't request
    one. Returning None silently is intentional: per the design, a
    missing default doesn't block session creation — the session
    simply lands without a severity and the user assigns one later."""
    async with conn.execute(
        "SELECT id FROM tags WHERE name = ? AND tag_group = 'severity'",
        (_DEFAULT_SEVERITY_NAME,),
    ) as cursor:
        row = await cursor.fetchone()
    return int(row["id"]) if row is not None else None


async def session_has_severity_tag(conn: aiosqlite.Connection, session_id: str) -> bool:
    """True when the session already carries at least one severity-
    group tag. Called by the create-session path to decide whether to
    auto-attach the default — a caller that passed an explicit
    severity tag skips the backfill."""
    async with conn.execute(
        "SELECT 1 FROM session_tags st "
        "JOIN tags t ON t.id = st.tag_id "
        "WHERE st.session_id = ? AND t.tag_group = 'severity' "
        "LIMIT 1",
        (session_id,),
    ) as cursor:
        return await cursor.fetchone() is not None


async def ensure_default_severity(conn: aiosqlite.Connection, session_id: str) -> bool:
    """Idempotent backfill: attach the default severity ('Low') to
    `session_id` iff the session currently carries no severity tag
    AND the default tag itself still exists. Returns True when the
    attach actually happened.

    Called from every session-create path (POST /sessions, paired
    chat spawn, reorg split, import) AFTER the caller's explicit tag
    attaches land, so a caller that passed an explicit severity wins
    and this becomes a no-op. Silently skips when the user has
    renamed / deleted the 'Low' tag — per the design, that's not an
    error, just a session that lands without a visible severity."""
    if await session_has_severity_tag(conn, session_id):
        return False
    default_id = await get_default_severity_tag_id(conn)
    if default_id is None:
        return False
    return await attach_tag(conn, session_id, default_id)


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
