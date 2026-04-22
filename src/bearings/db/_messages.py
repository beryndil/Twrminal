"""Messages + tool_calls table operations, plus the history aggregate
queries for both (`list_all_messages`, `list_all_tool_calls`,
`search_messages`). The two tables cohabitate here because they're
tightly coupled: tool_calls FK to messages, and the backfill helper
links the two after an assistant-turn persist."""

from __future__ import annotations

from typing import Any

import aiosqlite

from bearings.db._common import _date_filter, _new_id, _now


async def insert_message(
    conn: aiosqlite.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
    id: str | None = None,
    thinking: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_creation_tokens: int | None = None,
) -> dict[str, Any]:
    message_id = id or _new_id()
    now = _now()
    await conn.execute(
        "INSERT INTO messages (id, session_id, role, content, thinking, created_at, "
        "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            message_id,
            session_id,
            role,
            content,
            thinking,
            now,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
        ),
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
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
    }


async def get_session_token_totals(
    conn: aiosqlite.Connection,
    session_id: str,
) -> dict[str, int]:
    """Aggregate per-turn token counts into session-level totals.

    Returns the four columns summed over all messages for the session;
    rows whose columns are NULL (pre-0011 assistant turns, user rows)
    contribute 0 via COALESCE. Callers get a dict with every key set to
    a non-negative int so the frontend never has to handle None.
    """
    async with conn.execute(
        "SELECT "
        "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
        "COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens, "
        "COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens "
        "FROM messages WHERE session_id = ?",
        (session_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }
    return {
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "cache_read_tokens": int(row["cache_read_tokens"]),
        "cache_creation_tokens": int(row["cache_creation_tokens"]),
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
    cols = (
        "id, session_id, role, content, thinking, created_at, "
        "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens"
    )
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


async def find_replayable_prompt(
    conn: aiosqlite.Connection,
    session_id: str,
) -> dict[str, Any] | None:
    """Return the orphaned user message that should be re-queued on
    runner boot, or None.

    A message is "replayable" iff:
    - the owning session is not closed,
    - it is the newest row in the session,
    - its role is "user",
    - `replay_attempted_at` is still NULL.

    That combination uniquely identifies the failure mode this helper
    exists for: the server was killed mid-turn after persisting the
    user's prompt but before the SDK emitted an assistant reply. A
    closed session is excluded because the user has explicitly retired
    it; re-running a turn in a closed session would contradict that
    intent. A non-NULL `replay_attempted_at` means a previous boot
    already handled this orphan — whatever happened to that replay, we
    don't try again.

    Returns a dict with `id`, `content`, `created_at` on match; callers
    mark the row via `mark_replay_attempted` BEFORE queueing the prompt
    so a crash during replay can't trigger an infinite loop.
    """
    sql = (
        "SELECT m.id, m.content, m.created_at, m.role, m.replay_attempted_at "
        "FROM messages m "
        "JOIN sessions s ON s.id = m.session_id "
        "WHERE m.session_id = ? AND s.closed_at IS NULL "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT 1"
    )
    async with conn.execute(sql, (session_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    if row["role"] != "user":
        return None
    if row["replay_attempted_at"] is not None:
        return None
    return {
        "id": row["id"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


async def mark_replay_attempted(
    conn: aiosqlite.Connection,
    message_id: str,
) -> bool:
    """Stamp `replay_attempted_at = now()` on a single message row.

    Used as the fail-closed guard for runner-boot replay: write the
    mark first, then enqueue the prompt. If the process dies between
    those two steps we lose the replay for this boot but avoid an
    infinite-restart loop. Returns True when the row existed and was
    updated, False otherwise — callers treat False as "nothing to
    replay, skip."
    """
    cursor = await conn.execute(
        "UPDATE messages SET replay_attempted_at = ? WHERE id = ? AND replay_attempted_at IS NULL",
        (_now(), message_id),
    )
    await conn.commit()
    return cursor.rowcount > 0


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


async def append_tool_output(
    conn: aiosqlite.Connection,
    *,
    tool_call_id: str,
    chunk: str,
) -> bool:
    """Append a streamed chunk to a tool call's output column.

    Single-writer semantics: the runner is the only producer of deltas
    for any given `tool_call_id`, so SQLite's default serialization is
    enough — no explicit lock needed. The `COALESCE(output, '')` handles
    the first chunk (where `output` is still NULL from the initial
    `start_tool_call` insert). `finished_at` is intentionally left
    untouched; only `finish_tool_call` sets it, and that call writes
    the canonical final output in a single statement.

    Returns True if the tool_call row exists (chunk landed), False if
    no row matched — callers may log the latter as a dropped chunk.
    """
    cursor = await conn.execute(
        "UPDATE tool_calls SET output = COALESCE(output, '') || ? WHERE id = ?",
        (chunk, tool_call_id),
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


async def list_all_messages(
    conn: aiosqlite.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    where, params = _date_filter("created_at", date_from, date_to)
    sql = (
        "SELECT id, session_id, role, content, thinking, created_at, "
        "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        "FROM messages" + where + " ORDER BY created_at ASC, id ASC"
    )
    async with conn.execute(sql, params) as cursor:
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


async def search_messages(
    conn: aiosqlite.Connection, query: str, *, limit: int = 50
) -> list[dict[str, Any]]:
    """Case-insensitive LIKE match across message content and thinking,
    joined with sessions for the title. Newest matches first."""
    pattern = f"%{query}%"
    sql = (
        "SELECT m.id AS message_id, m.session_id, m.role, m.content, "
        "m.thinking, m.created_at, "
        "m.input_tokens, m.output_tokens, "
        "m.cache_read_tokens, m.cache_creation_tokens, "
        "s.title AS session_title, s.model "
        "FROM messages m JOIN sessions s ON s.id = m.session_id "
        "WHERE m.content LIKE ? OR m.thinking LIKE ? "
        "ORDER BY m.created_at DESC, m.id DESC LIMIT ?"
    )
    async with conn.execute(sql, (pattern, pattern, limit)) as cursor:
        return [dict(row) async for row in cursor]
