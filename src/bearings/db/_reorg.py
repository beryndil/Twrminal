"""Cross-session reorg helpers — move rows between `sessions` and
record the corresponding audit entries.

Slice 1 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`) added `move_messages_tx`;
Slice 5 layered on the `reorg_audits` persistence so every move/split/
merge leaves a permanent divider on the source conversation. The
audit write lives outside `move_messages_tx` so callers can record
the exact op name (`move` / `split` / `merge`) and the target title
snapshot without the primitive having to know about routing concerns.

`sessions.message_count` is derived via `SELECT COUNT(*)` in
`_sessions.SESSION_COUNT`, so nothing in here has to recompute it —
touching `messages.session_id` is enough for the next read to see the
new counts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

import aiosqlite

from bearings.db._common import _now

ReorgOp = Literal["move", "split", "merge"]


@dataclass(frozen=True)
class MoveResult:
    """Counts returned by `move_messages_tx`.

    `moved` counts messages whose `session_id` actually changed; rows
    already on the target (from a prior call) are excluded because the
    primitive is idempotent. `tool_calls_followed` counts `tool_calls`
    rows updated because they were anchored (via `message_id`) to a
    moved message. Orphan tool calls (null `message_id`) stay with the
    source session.
    """

    moved: int
    tool_calls_followed: int


async def move_messages_tx(
    conn: aiosqlite.Connection,
    *,
    source_id: str,
    target_id: str,
    message_ids: Sequence[str],
) -> MoveResult:
    """Atomically move `message_ids` from source to target session.

    Behavior:
    - Idempotent. The `session_id = source_id` guard means a second
      call on the same ids returns `moved=0` without error.
    - Partial input is tolerated. Ids absent from the source are
      silently skipped; they don't count toward `moved`.
    - Tool calls anchored to moved messages follow their message to
      the target. Orphan tool calls stay behind.
    - Both sessions' `updated_at` bump iff at least one message moved,
      so the sidebar re-sorts on next `list_sessions`.
    - `sessions.message_count` is a derived SELECT, so no recompute.

    Raises:
        ValueError: if `source_id == target_id` or the target session
            does not exist. A missing source is tolerated and yields a
            no-op result (nothing matches the guard).

    Rolls back on any mid-operation exception; `conn.commit()` runs
    exactly once on the happy path.
    """
    if source_id == target_id:
        raise ValueError("source and target sessions must differ")
    if not message_ids:
        return MoveResult(moved=0, tool_calls_followed=0)

    async with conn.execute("SELECT 1 FROM sessions WHERE id = ?", (target_id,)) as cursor:
        if await cursor.fetchone() is None:
            raise ValueError(f"target session {target_id!r} does not exist")

    placeholders = ",".join("?" for _ in message_ids)
    now = _now()

    try:
        msg_cursor = await conn.execute(
            f"UPDATE messages SET session_id = ? WHERE session_id = ? AND id IN ({placeholders})",
            (target_id, source_id, *message_ids),
        )
        moved = msg_cursor.rowcount

        tc_cursor = await conn.execute(
            f"UPDATE tool_calls SET session_id = ? "
            f"WHERE session_id = ? AND message_id IN ({placeholders})",
            (target_id, source_id, *message_ids),
        )
        tool_calls_followed = tc_cursor.rowcount

        if moved > 0:
            await conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id IN (?, ?)",
                (now, source_id, target_id),
            )

        await conn.commit()
    except BaseException:
        await conn.rollback()
        raise

    return MoveResult(moved=moved, tool_calls_followed=tool_calls_followed)


async def record_reorg_audit(
    conn: aiosqlite.Connection,
    *,
    source_session_id: str,
    target_session_id: str | None,
    target_title_snapshot: str | None,
    message_count: int,
    op: ReorgOp,
) -> int:
    """Insert a row into `reorg_audits` and return its autoincrement id.

    Caller is responsible for committing; this mirrors the primitive's
    transactional contract. `target_session_id` may be null when the
    caller wants to record a merge-with-delete whose target was
    subsequently deleted (the FK is `ON DELETE SET NULL`); normal move
    / split / merge always pass a live target id.
    """
    cursor = await conn.execute(
        """
        INSERT INTO reorg_audits (
            source_session_id, target_session_id, target_title_snapshot,
            message_count, op, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source_session_id,
            target_session_id,
            target_title_snapshot,
            message_count,
            op,
            _now(),
        ),
    )
    audit_id = cursor.lastrowid
    assert audit_id is not None  # AUTOINCREMENT guarantees a row id
    return audit_id


async def list_reorg_audits(
    conn: aiosqlite.Connection,
    source_session_id: str,
) -> list[dict[str, Any]]:
    """Return every audit row for `source_session_id`, oldest first.

    Callers render these inline with the session's messages, sorted by
    `created_at` against the message timestamps, so an old divider
    stays at its original chronological spot even after newer ops
    push it down the list.
    """
    rows: list[dict[str, Any]] = []
    async with conn.execute(
        """
        SELECT id, source_session_id, target_session_id,
               target_title_snapshot, message_count, op, created_at
        FROM reorg_audits
        WHERE source_session_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (source_session_id,),
    ) as cursor:
        async for row in cursor:
            rows.append(dict(row))
    return rows


async def delete_reorg_audit(conn: aiosqlite.Connection, audit_id: int) -> bool:
    """Remove an audit row — used by the undo path. Returns True when
    a row was deleted, False when the id was already gone (racing undo
    clicks, dev-tools meddling, etc.).
    """
    cursor = await conn.execute("DELETE FROM reorg_audits WHERE id = ?", (audit_id,))
    deleted = cursor.rowcount > 0
    await conn.commit()
    return deleted
