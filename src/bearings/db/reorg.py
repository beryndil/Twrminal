"""``reorg_audit`` table queries — session-merge audit log.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``reorg_audit``.

Public surface:

* :class:`ReorgAudit` — frozen dataclass row mirror for one merge record.
* :func:`merge_sessions` — atomic merge of ``src`` into ``dst``:
  re-parents all messages, deletes the source session, writes an audit
  row. Raises :class:`ValueError` on self-merge; returns ``None`` when
  either session is absent.
* :func:`list_audit_for_session` — fetch all audit rows for a
  destination session (oldest-first); used by the frontend to render
  merge dividers.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.db._id import new_id, now_iso

# Prefix for reorg_audit primary keys — ``rga_<32-hex>``.
_REORG_AUDIT_PREFIX = "rga"


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


__all__ = ["ReorgAudit", "list_audit_for_session", "merge_sessions"]
