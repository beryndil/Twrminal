"""Session table operations: CRUD, import, cost accumulation, and the
aggregate `list_all_sessions` used by the history export route. Owns
the `_SESSION_*` column constants that other modules may reference."""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _date_filter, _new_id, _now

SESSION_BASE_COLS = (
    "id, created_at, updated_at, working_dir, model, title, description, "
    "max_budget_usd, total_cost_usd, session_instructions, sdk_session_id"
)
SESSION_COUNT = "(SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count"
SESSION_COLS_WITH_COUNT = f"s.{SESSION_BASE_COLS.replace(', ', ', s.')}, {SESSION_COUNT}"


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

    - `tag_ids=None`/empty: no filter.
    - `mode="any"`: sessions carrying any listed tag.
    - `mode="all"`: sessions carrying every listed tag.

    Ordering stays `updated_at DESC, id DESC`.
    """
    if not tag_ids:
        sql = (
            f"SELECT {SESSION_COLS_WITH_COUNT} FROM sessions s "
            "ORDER BY s.updated_at DESC, s.id DESC"
        )
        async with conn.execute(sql) as cursor:
            return [dict(row) async for row in cursor]

    placeholders = ",".join("?" for _ in tag_ids)
    if mode == "all":
        # HAVING COUNT(DISTINCT tag_id) == len(tag_ids) ensures every
        # required tag is present on the session.
        sql = (
            f"SELECT {SESSION_COLS_WITH_COUNT} FROM sessions s "
            f"JOIN session_tags st ON st.session_id = s.id "
            f"WHERE st.tag_id IN ({placeholders}) "
            f"GROUP BY s.id HAVING COUNT(DISTINCT st.tag_id) = ? "
            "ORDER BY s.updated_at DESC, s.id DESC"
        )
        params: tuple[Any, ...] = (*tag_ids, len(tag_ids))
    else:
        # mode == "any" — DISTINCT + IN (...).
        sql = (
            f"SELECT DISTINCT {SESSION_COLS_WITH_COUNT} FROM sessions s "
            f"JOIN session_tags st ON st.session_id = s.id "
            f"WHERE st.tag_id IN ({placeholders}) "
            "ORDER BY s.updated_at DESC, s.id DESC"
        )
        params = tuple(tag_ids)
    async with conn.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]


async def get_session(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        f"SELECT {SESSION_COLS_WITH_COUNT} FROM sessions s WHERE s.id = ?",
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
    only `title`, `description`, `max_budget_usd`, and
    `session_instructions` are accepted. Bumps updated_at. Returns
    the refreshed row, or None if the session doesn't exist."""
    allowed = {
        "title",
        "description",
        "max_budget_usd",
        "session_instructions",
    }
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
            str(src_session.get("model") or "claude-opus-4-7"),
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


async def set_sdk_session_id(
    conn: aiosqlite.Connection,
    session_id: str,
    sdk_session_id: str,
) -> None:
    """Cache the claude-agent-sdk session id on the Bearings session so
    later turns can `resume=` it and inherit the SDK's conversation
    history. No-op if the row is gone."""
    await conn.execute(
        "UPDATE sessions SET sdk_session_id = ? WHERE id = ?",
        (sdk_session_id, session_id),
    )
    await conn.commit()


async def apply_session_cost_turn(
    conn: aiosqlite.Connection,
    session_id: str,
    reported_cumulative_usd: float,
) -> float:
    """Turn a cumulative SDK cost report into a per-turn delta and
    accumulate it on the session row.

    `claude-agent-sdk`'s `ResultMessage.total_cost_usd` is cumulative
    for the resumed CLI session — i.e. on turn N it's the sum of spend
    across turns 1..N, not just turn N. Adding that raw on every turn
    inflates totals quadratically. We store the last cumulative we've
    seen in `sdk_reported_cost_usd` so we can subtract it to get the
    actual per-turn delta; then we bump `total_cost_usd` by that delta
    and update the baseline. Returns the delta (>= 0).

    If the reported cumulative is *less* than our baseline, the SDK
    started a fresh CLI session (e.g. resume=ing a purged id), so we
    treat the reported value itself as the delta and reset the
    baseline to match — no retroactive adjustment.

    Returns 0.0 if the session row is gone (e.g. deleted mid-stream).
    """
    async with conn.execute(
        "SELECT sdk_reported_cost_usd FROM sessions WHERE id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return 0.0
    baseline = float(row[0] or 0.0)
    if reported_cumulative_usd >= baseline:
        delta = reported_cumulative_usd - baseline
    else:
        delta = max(0.0, reported_cumulative_usd)
    await conn.execute(
        "UPDATE sessions "
        "SET total_cost_usd = total_cost_usd + ?, sdk_reported_cost_usd = ? "
        "WHERE id = ?",
        (delta, reported_cumulative_usd, session_id),
    )
    await conn.commit()
    return delta


async def list_all_sessions(
    conn: aiosqlite.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _date_filter("s.created_at", date_from, date_to)
    sql = (
        f"SELECT {SESSION_COLS_WITH_COUNT} FROM sessions s{where} "
        "ORDER BY s.created_at ASC, s.id ASC"
    )
    async with conn.execute(sql, params) as cursor:
        return [dict(row) async for row in cursor]
