"""``tool_calls`` table queries — per-turn tool-call records (gap-cycle-03-012).

Each row represents one tool invocation that completed during an assistant
turn. The batch is written atomically at end-of-turn after the assistant
message row is persisted, so ``message_id`` always references a valid
:mod:`bearings.db.messages` row.

Public surface:

* :func:`insert_batch` — write a batch of tool-call records for one turn.
* :func:`list_for_messages` — fetch tool-call rows for a set of message ids.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.db._id import now_iso


@dataclass(frozen=True)
class ToolCall:
    """Row mirror for the ``tool_calls`` table.

    Per gap-cycle-03-012 schema:

    * ``id`` — SDK tool_call_id (``toolu_01…``); primary key.
    * ``session_id`` / ``message_id`` — join keys for cascade and REST.
    * ``tool_name`` / ``input_json`` — from :class:`bearings.agent.events.ToolCallStart`.
    * ``output`` — full content of the tool result
      (:attr:`bearings.agent.events.ToolCallEnd.output_summary`).
    * ``ok`` — ``True`` on success, ``False`` on error, ``None`` if the
      turn was interrupted before :class:`bearings.agent.events.ToolCallEnd`
      arrived (should be rare for persisted rows).
    * ``duration_ms`` / ``error_message`` — from ``ToolCallEnd``.
    """

    id: str
    session_id: str
    message_id: str
    tool_name: str
    input_json: str
    output: str
    ok: bool | None
    duration_ms: int | None
    error_message: str | None
    created_at: str


@dataclass(frozen=True)
class ToolCallRecord:
    """Transient carrier for one tool-call's start+end data, used by
    :func:`insert_batch`."""

    tool_call_id: str
    tool_name: str
    input_json: str
    output: str
    ok: bool | None
    duration_ms: int | None
    error_message: str | None


async def insert_batch(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    message_id: str,
    records: list[ToolCallRecord],
) -> None:
    """INSERT a batch of tool-call records for one assistant turn.

    Called by :mod:`bearings.agent.sdk_loop` after
    :func:`bearings.agent.persistence.persist_assistant_turn` returns
    the Bearings message id, so ``message_id`` is guaranteed valid.

    All records share the same ``created_at`` timestamp (the turn's
    wall-clock completion instant). An empty ``records`` list is a no-op.

    Args:
        connection: Open aiosqlite connection with FK enforcement on.
        session_id: Bearings session id (``ses_<32hex>``).
        message_id: Bearings message id of the owning assistant turn
            (``msg_<32hex>``), as returned by ``insert_assistant``.
        records: One :class:`ToolCallRecord` per tool invocation in
            the turn, in invocation order.
    """
    if not records:
        return
    timestamp = now_iso()
    rows = [
        (
            r.tool_call_id,
            session_id,
            message_id,
            r.tool_name,
            r.input_json,
            r.output,
            (1 if r.ok else 0) if r.ok is not None else None,
            r.duration_ms,
            r.error_message,
            timestamp,
        )
        for r in records
    ]
    await connection.executemany(
        "INSERT OR IGNORE INTO tool_calls "
        "(id, session_id, message_id, tool_name, input_json, "
        " output, ok, duration_ms, error_message, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    await connection.commit()


async def latest_todo_write_json(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
) -> str | None:
    """Return the ``input_json`` of the most-recent ``TodoWrite`` call for a session.

    Used by the ``GET /api/sessions/{id}/todos`` endpoint to seed the
    ``LiveTodos`` panel on session open.  The input shape is
    ``{"todos": [{id, content, status, priority, ...}, ...]}``.

    Returns ``None`` if the session has never emitted a ``TodoWrite``
    call (no row with ``tool_name = 'TodoWrite'`` for this session).
    """
    cursor = await connection.execute(
        "SELECT input_json FROM tool_calls "
        "WHERE session_id = ? AND tool_name = 'TodoWrite' "
        "ORDER BY rowid DESC LIMIT 1",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return str(row[0]) if row is not None else None


async def list_for_messages(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    message_ids: list[str],
) -> list[ToolCall]:
    """Return all tool-call rows whose ``message_id`` is in ``message_ids``.

    Returns rows in insertion order (rowid ASC) so tool calls appear in
    the same order they executed within each turn.

    Args:
        connection: Open aiosqlite connection.
        session_id: Bearings session id — used as a secondary filter to
            prevent cross-session id collisions on ``message_ids``.
        message_ids: List of Bearings message ids to query. Empty list
            returns an empty result without hitting the DB.

    Returns:
        List of :class:`ToolCall` rows, possibly empty.
    """
    if not message_ids:
        return []
    placeholders = ",".join("?" * len(message_ids))
    cursor = await connection.execute(
        f"SELECT id, session_id, message_id, tool_name, input_json, "
        f"       output, ok, duration_ms, error_message, created_at "
        f"FROM tool_calls "
        f"WHERE session_id = ? AND message_id IN ({placeholders}) "
        f"ORDER BY rowid ASC",
        (session_id, *message_ids),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    result: list[ToolCall] = []
    for row in rows:
        ok_raw = row[6]
        ok: bool | None = None if ok_raw is None else bool(int(ok_raw))
        result.append(
            ToolCall(
                id=str(row[0]),
                session_id=str(row[1]),
                message_id=str(row[2]),
                tool_name=str(row[3]),
                input_json=str(row[4]),
                output=str(row[5]),
                ok=ok,
                duration_ms=int(row[7]) if row[7] is not None else None,
                error_message=str(row[8]) if row[8] is not None else None,
                created_at=str(row[9]),
            )
        )
    return result


__all__ = [
    "ToolCall",
    "ToolCallRecord",
    "insert_batch",
    "latest_todo_write_json",
    "list_for_messages",
]
