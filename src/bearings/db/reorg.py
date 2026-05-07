"""``reorg_audit`` table queries — session-merge audit log.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``reorg_audit``.

Public surface:

* :class:`ReorgAudit` — frozen dataclass row mirror for one merge record.
* :class:`StaleAuditError` — raised by :func:`undo_merge_audit` when
  messages have been mutated since the merge.
* :func:`merge_sessions` — atomic merge of ``src`` into ``dst``:
  re-parents all messages, deletes the source session, writes an audit
  row. Raises :class:`ValueError` on self-merge; returns ``None`` when
  either session is absent.
* :func:`list_audit_for_session` — fetch all audit rows for a
  destination session (oldest-first); used by the frontend to render
  merge dividers.
* :func:`get_audit` — fetch one audit row by id; returns ``None`` when
  absent or when the row does not belong to the given destination
  session.
* :func:`undo_merge_audit` — atomically reverse a merge: re-create the
  source session, move its messages back, and delete the audit row.
  Raises :class:`StaleAuditError` when any message has been added to
  the destination session after the merge timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db._id import new_id, now_iso

# Prefix for reorg_audit primary keys — ``rga_<32-hex>``.
_REORG_AUDIT_PREFIX = "rga"
# Prefix for session primary keys (mirrors sessions.py convention).
_SESSION_ID_PREFIX = "ses"


class StaleAuditError(Exception):
    """Raised by :func:`undo_merge_audit` when the destination session has
    received new messages since the recorded merge timestamp.  The caller
    should surface this as a 409 Conflict response.
    """


@dataclass(frozen=True)
class ReorgAudit:
    """One merge-operation audit record."""

    id: str
    dst_session_id: str
    src_session_id: str
    merged_at: str
    src_title: str
    boundary_msg_id: str | None


async def merge_sessions(
    connection: aiosqlite.Connection,
    src_id: str,
    dst_id: str,
) -> ReorgAudit | None:
    """Atomically merge ``src_id`` into ``dst_id``.

    Within a single transaction:

    1. Validates both sessions exist; returns ``None`` if either is absent.
    2. Re-parents every message from ``src`` to ``dst`` (ordered by
       ``created_at ASC``) — ``session_id`` is updated in-place so
       ``created_at`` timestamps are preserved and the dst transcript
       is still ordered by ``created_at ASC, id ASC`` after the merge.
    3. Resets ``message_count`` on ``dst`` from the live row count.
    4. Writes a :class:`ReorgAudit` row with the id of the first
       re-parented message as ``boundary_msg_id`` (``NULL`` when src had
       no messages).
    5. Deletes the source session row (cascades to any remaining
       attachments, checkpoints, tags, sdk_session_entries).

    Raises :class:`ValueError` when ``src_id == dst_id`` (caller must
    return 409 before reaching this function — the guard here is a
    belt-and-braces safety net).

    Returns the committed :class:`ReorgAudit` row on success, or
    ``None`` when either session was not found.
    """
    if src_id == dst_id:
        raise ValueError("merge_sessions: src_id and dst_id must differ")

    # Verify both sessions exist and capture the src title for the audit row.
    cursor = await connection.execute(
        "SELECT id, title FROM sessions WHERE id IN (?, ?)",
        (src_id, dst_id),
    )
    try:
        found_rows = await cursor.fetchall()
    finally:
        await cursor.close()

    found_ids = {row[0]: row[1] for row in found_rows}
    if src_id not in found_ids or dst_id not in found_ids:
        return None

    src_title: str = str(found_ids[src_id])

    # Fetch the first message from src (by created_at) to record as the
    # merge boundary — this is what the frontend uses to position the
    # divider in the merged transcript.
    cursor = await connection.execute(
        "SELECT id FROM messages WHERE session_id = ? ORDER BY created_at ASC, id ASC LIMIT 1",
        (src_id,),
    )
    try:
        boundary_row = await cursor.fetchone()
    finally:
        await cursor.close()
    boundary_msg_id: str | None = str(boundary_row[0]) if boundary_row is not None else None

    # Count src messages for the dst message_count update.
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?",
        (src_id,),
    )
    try:
        count_row = await cursor.fetchone()
    finally:
        await cursor.close()
    src_message_count: int = int(count_row[0]) if count_row is not None else 0

    # Re-parent messages from src to dst in one UPDATE.
    await connection.execute(
        "UPDATE messages SET session_id = ? WHERE session_id = ?",
        (dst_id, src_id),
    )

    # Recompute dst message_count directly from the table rather than
    # relying on incremental arithmetic — guards against any prior
    # drift in the counter.
    await connection.execute(
        """
        UPDATE sessions
           SET message_count = message_count + ?
         WHERE id = ?
        """,
        (src_message_count, dst_id),
    )

    # Write audit row.
    audit_id = new_id(_REORG_AUDIT_PREFIX)
    merged_at = now_iso()
    await connection.execute(
        """
        INSERT INTO reorg_audit
               (id, dst_session_id, src_session_id, merged_at, src_title, boundary_msg_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (audit_id, dst_id, src_id, merged_at, src_title, boundary_msg_id),
    )

    # Delete the source session — cascades to its remaining FK-linked rows
    # (checkpoints, session_tags, sdk_session_entries, paired_chats, etc.).
    # Messages were already re-parented so they survive the cascade.
    await connection.execute("DELETE FROM sessions WHERE id = ?", (src_id,))

    await connection.commit()

    return ReorgAudit(
        id=audit_id,
        dst_session_id=dst_id,
        src_session_id=src_id,
        merged_at=merged_at,
        src_title=src_title,
        boundary_msg_id=boundary_msg_id,
    )


async def list_audit_for_session(
    connection: aiosqlite.Connection,
    dst_session_id: str,
) -> list[ReorgAudit]:
    """Return all merge audit rows for ``dst_session_id``, oldest-first."""
    cursor = await connection.execute(
        """
        SELECT id, dst_session_id, src_session_id, merged_at, src_title, boundary_msg_id
          FROM reorg_audit
         WHERE dst_session_id = ?
         ORDER BY merged_at ASC
        """,
        (dst_session_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [
        ReorgAudit(
            id=str(row[0]),
            dst_session_id=str(row[1]),
            src_session_id=str(row[2]),
            merged_at=str(row[3]),
            src_title=str(row[4]),
            boundary_msg_id=str(row[5]) if row[5] is not None else None,
        )
        for row in rows
    ]


async def get_audit(
    connection: aiosqlite.Connection,
    audit_id: str,
    dst_session_id: str,
) -> ReorgAudit | None:
    """Fetch one audit row by ``audit_id``.

    Returns ``None`` when no row matches or when the row belongs to a
    different destination session (prevents cross-session access).
    """
    cursor = await connection.execute(
        """
        SELECT id, dst_session_id, src_session_id, merged_at, src_title, boundary_msg_id
          FROM reorg_audit
         WHERE id = ?
           AND dst_session_id = ?
        """,
        (audit_id, dst_session_id),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    return ReorgAudit(
        id=str(row[0]),
        dst_session_id=str(row[1]),
        src_session_id=str(row[2]),
        merged_at=str(row[3]),
        src_title=str(row[4]),
        boundary_msg_id=str(row[5]) if row[5] is not None else None,
    )


async def undo_merge_audit(
    connection: aiosqlite.Connection,
    audit_id: str,
    dst_session_id: str,
) -> str | None:
    """Atomically reverse a merge operation and delete the audit row.

    Steps:

    1. Fetch the audit row; return ``None`` if absent.
    2. Stale check — raise :class:`StaleAuditError` if any message in
       ``dst_session_id`` has ``created_at > merged_at`` (messages were
       added after the merge) or if ``boundary_msg_id`` is not ``None``
       but no longer exists in ``dst_session_id`` (messages were moved
       away).
    3. Create a new session row for the re-surfaced source, using the
       recorded ``src_title``.
    4. Move all messages in ``dst_session_id`` whose ``created_at`` is
       at or after the boundary message's ``created_at`` back to the new
       session.  (When ``boundary_msg_id`` is ``None`` the source had no
       messages; skip step 4.)
    5. Update ``message_count`` on both sessions.
    6. Delete the ``reorg_audit`` row.
    7. Commit.

    Returns the id of the newly created source session on success, or
    ``None`` when the audit row was not found.

    Raises :class:`StaleAuditError` when the destination has been
    mutated after the merge.
    """
    audit = await get_audit(connection, audit_id, dst_session_id)
    if audit is None:
        return None

    # --- Stale check: new messages added to dst after the merge. ---
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND created_at > ?",
        (dst_session_id, audit.merged_at),
    )
    try:
        count_row = await cursor.fetchone()
    finally:
        await cursor.close()
    if count_row is not None and int(count_row[0]) > 0:
        raise StaleAuditError(
            f"destination session {dst_session_id!r} has messages added after merge at "
            f"{audit.merged_at!r}; undo is not safe"
        )

    # --- Stale check: boundary message removed from dst. ---
    boundary_created_at: str | None = None
    if audit.boundary_msg_id is not None:
        cursor = await connection.execute(
            "SELECT created_at FROM messages WHERE id = ? AND session_id = ?",
            (audit.boundary_msg_id, dst_session_id),
        )
        try:
            brow = await cursor.fetchone()
        finally:
            await cursor.close()
        if brow is None:
            raise StaleAuditError(
                f"boundary message {audit.boundary_msg_id!r} no longer exists in "
                f"destination session {dst_session_id!r}; undo is not safe"
            )
        boundary_created_at = str(brow[0])

    # --- Create the resurrected source session. ---
    new_src_id = new_id(_SESSION_ID_PREFIX)
    now = now_iso()
    await connection.execute(
        """
        INSERT INTO sessions
               (id, kind, title, working_dir, model,
                message_count, pinned, error_pending, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?)
        """,
        (new_src_id, SESSION_KIND_CHAT, audit.src_title, "", "sonnet", now, now),
    )

    # --- Move messages and update counts. ---
    moved_count = 0
    if boundary_created_at is not None:
        # Count messages to be moved before re-parenting.
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND created_at >= ?",
            (dst_session_id, boundary_created_at),
        )
        try:
            mc_row = await cursor.fetchone()
        finally:
            await cursor.close()
        moved_count = int(mc_row[0]) if mc_row is not None else 0

        await connection.execute(
            "UPDATE messages SET session_id = ? WHERE session_id = ? AND created_at >= ?",
            (new_src_id, dst_session_id, boundary_created_at),
        )

    # Update message_count on dst (subtract moved) and new src (add moved).
    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - ?) WHERE id = ?",
        (moved_count, dst_session_id),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = ? WHERE id = ?",
        (moved_count, new_src_id),
    )

    # --- Delete the audit row. ---
    await connection.execute("DELETE FROM reorg_audit WHERE id = ?", (audit_id,))

    await connection.commit()

    return new_src_id


__all__ = [
    "ReorgAudit",
    "StaleAuditError",
    "get_audit",
    "list_audit_for_session",
    "merge_sessions",
    "undo_merge_audit",
]
