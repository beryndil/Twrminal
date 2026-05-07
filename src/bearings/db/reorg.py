"""``reorg_audit`` table queries — session reorganisation audit log.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``reorg_audit``.

Public surface:

* :class:`ReorgAudit` — frozen dataclass row mirror for one reorg record.
* :class:`SplitResult` — return type for :func:`split_session` carrying
  the audit row and the list of moved message ids.
* :class:`StaleAuditError` — raised by :func:`undo_merge_audit` when the
  relevant session has been mutated since the recorded operation timestamp.
* :func:`merge_sessions` — atomic merge of ``src`` into ``dst``:
  re-parents all messages, deletes the source session, writes an audit
  row of ``kind='merge'``. Raises :class:`ValueError` on self-merge;
  returns ``None`` when either session is absent.
* :func:`split_session` — atomic split of ``src`` at ``from_seq``:
  re-parents all messages with rowid >= ``from_seq`` from ``src`` to
  ``dst``, writes an audit row of ``kind='split'``. Returns
  :class:`SplitResult` or ``None`` when either session is absent or
  ``src_id == dst_id``.
* :func:`move_message_reorg` — atomic single-message move from ``src``
  to ``dst``; writes an audit row of ``kind='move'``. Returns the
  :class:`ReorgAudit` row or ``None`` when any referenced object is
  absent or the message does not belong to ``src``.
* :func:`list_audit_for_session` — fetch all audit rows for a session
  (oldest-first); used by the frontend to render dividers on load.
* :func:`get_audit` — fetch one audit row by id; returns ``None`` when
  absent or when the row does not belong to the given session.
* :func:`undo_merge_audit` — atomically reverse any reorg operation
  recorded by the audit table. Raises :class:`StaleAuditError` when the
  session has been mutated after the recorded timestamp.

Column semantics for ``dst_session_id`` across kinds
------------------------------------------------------
For all three kinds ``dst_session_id`` is the session that *hosts the
divider* — the conversation the user is currently viewing when the
boundary line renders.

* ``kind='merge'``: messages flowed INTO ``dst_session_id``; the
  divider marks where the imported content begins.  ``src_session_id``
  is the (deleted) source session.
* ``kind='split'``: messages flowed OUT OF ``dst_session_id``; the
  divider marks where the session was truncated.  ``src_session_id`` is
  the still-live session that received the content.
* ``kind='move'``: single message moved OUT OF ``dst_session_id``; the
  divider marks the vacated boundary.  ``src_session_id`` is the
  still-live target session.

This convention keeps ``list_audit_for_session`` queryable by the session
the user is looking at (``WHERE dst_session_id = ?``) for all three
kinds, and keeps ``dst_session_id``'s ON DELETE CASCADE correct (deleting
the host session cleans its own audit rows automatically).
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

_SELECT_AUDIT_COLS = (
    "SELECT id, dst_session_id, src_session_id, merged_at, src_title,"
    " boundary_msg_id, kind"
    " FROM reorg_audit"
)


class StaleAuditError(Exception):
    """Raised by :func:`undo_merge_audit` when the relevant session has
    been mutated after the recorded operation timestamp.  The caller
    should surface this as a 409 Conflict response.
    """


@dataclass(frozen=True)
class ReorgAudit:
    """One reorg-operation audit record.

    ``kind`` is one of ``'merge'``, ``'split'``, or ``'move'``.

    See module docstring for the ``dst_session_id`` / ``src_session_id``
    semantics across each kind.
    """

    id: str
    dst_session_id: str
    src_session_id: str
    merged_at: str
    src_title: str
    boundary_msg_id: str | None
    kind: str


@dataclass(frozen=True)
class SplitResult:
    """Return type for :func:`split_session`.

    ``audit`` is the committed audit row.  ``moved_message_ids`` is the
    ordered list of message ids that were re-parented to the target
    session (empty when no messages matched ``from_seq``).
    """

    audit: ReorgAudit
    moved_message_ids: list[str]


def _row_to_audit(row: object) -> ReorgAudit:
    r: tuple[object, ...] = tuple(row)  # type: ignore[arg-type]
    return ReorgAudit(
        id=str(r[0]),
        dst_session_id=str(r[1]),
        src_session_id=str(r[2]),
        merged_at=str(r[3]),
        src_title=str(r[4]),
        boundary_msg_id=str(r[5]) if r[5] is not None else None,
        kind=str(r[6]),
    )


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
    4. Writes a :class:`ReorgAudit` row (``kind='merge'``) with the id
       of the first re-parented message as ``boundary_msg_id`` (``NULL``
       when src had no messages).
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
               (id, dst_session_id, src_session_id, merged_at, src_title,
                boundary_msg_id, kind)
        VALUES (?, ?, ?, ?, ?, ?, 'merge')
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
        kind="merge",
    )


async def split_session(
    connection: aiosqlite.Connection,
    src_id: str,
    dst_id: str,
    from_seq: int,
) -> SplitResult | None:
    """Atomically split ``src_id`` at ``from_seq`` into ``dst_id``.

    All messages in ``src_id`` with ``rowid >= from_seq`` are re-parented
    to ``dst_id`` in a single transaction.  An audit row of ``kind='split'``
    is written with ``dst_session_id = src_id`` (the session that hosts
    the divider) and ``src_session_id = dst_id`` (where content went).

    Returns ``None`` when either session is absent or ``src_id == dst_id``.
    Returns a :class:`SplitResult` with an empty ``moved_message_ids``
    list when no messages in ``src_id`` have ``rowid >= from_seq`` (the
    audit row is still written in that case to record the intent).
    """
    if src_id == dst_id:
        return None

    # Verify both sessions exist; capture dst title for the audit src_title.
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

    # Title of the "other" session — used for divider label.
    dst_title: str = str(found_ids[dst_id])

    # Collect affected message ids (ordered by rowid = seq).
    cursor = await connection.execute(
        "SELECT id FROM messages WHERE session_id = ? AND rowid >= ? ORDER BY rowid ASC",
        (src_id, from_seq),
    )
    try:
        msg_rows = await cursor.fetchall()
    finally:
        await cursor.close()

    moved_message_ids: list[str] = [str(r[0]) for r in msg_rows]
    boundary_msg_id: str | None = moved_message_ids[0] if moved_message_ids else None
    move_count = len(moved_message_ids)

    # Re-parent in one UPDATE.
    if move_count > 0:
        await connection.execute(
            "UPDATE messages SET session_id = ? WHERE session_id = ? AND rowid >= ?",
            (dst_id, src_id, from_seq),
        )
        await connection.execute(
            "UPDATE sessions SET message_count = MAX(0, message_count - ?) WHERE id = ?",
            (move_count, src_id),
        )
        await connection.execute(
            "UPDATE sessions SET message_count = message_count + ? WHERE id = ?",
            (move_count, dst_id),
        )

    # Write audit row.  dst_session_id = src_id (divider host); src_session_id = dst_id (target).
    audit_id = new_id(_REORG_AUDIT_PREFIX)
    merged_at = now_iso()
    await connection.execute(
        """
        INSERT INTO reorg_audit
               (id, dst_session_id, src_session_id, merged_at, src_title,
                boundary_msg_id, kind)
        VALUES (?, ?, ?, ?, ?, ?, 'split')
        """,
        (audit_id, src_id, dst_id, merged_at, dst_title, boundary_msg_id),
    )

    await connection.commit()

    audit = ReorgAudit(
        id=audit_id,
        dst_session_id=src_id,
        src_session_id=dst_id,
        merged_at=merged_at,
        src_title=dst_title,
        boundary_msg_id=boundary_msg_id,
        kind="split",
    )
    return SplitResult(audit=audit, moved_message_ids=moved_message_ids)


async def move_message_reorg(
    connection: aiosqlite.Connection,
    src_id: str,
    dst_id: str,
    message_id: str,
) -> ReorgAudit | None:
    """Atomically move a single message from ``src_id`` to ``dst_id``.

    Re-parents ``message_id`` in a single transaction and writes an audit
    row of ``kind='move'`` with ``dst_session_id = src_id`` (divider host)
    and ``src_session_id = dst_id`` (target).

    Returns ``None`` when either session is absent, ``src_id == dst_id``,
    or ``message_id`` does not exist in ``src_id``.
    """
    if src_id == dst_id:
        return None

    # Verify both sessions exist; capture dst title for the audit src_title.
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

    dst_title: str = str(found_ids[dst_id])

    # Verify the message exists and belongs to src_id.
    cursor = await connection.execute(
        "SELECT id FROM messages WHERE id = ? AND session_id = ?",
        (message_id, src_id),
    )
    try:
        msg_row = await cursor.fetchone()
    finally:
        await cursor.close()

    if msg_row is None:
        return None

    # Re-parent the message.
    await connection.execute(
        "UPDATE messages SET session_id = ? WHERE id = ?",
        (dst_id, message_id),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - 1) WHERE id = ?",
        (src_id,),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
        (dst_id,),
    )

    # Write audit row.  dst_session_id = src_id (divider host); src_session_id = dst_id (target).
    audit_id = new_id(_REORG_AUDIT_PREFIX)
    merged_at = now_iso()
    await connection.execute(
        """
        INSERT INTO reorg_audit
               (id, dst_session_id, src_session_id, merged_at, src_title,
                boundary_msg_id, kind)
        VALUES (?, ?, ?, ?, ?, ?, 'move')
        """,
        (audit_id, src_id, dst_id, merged_at, dst_title, message_id),
    )

    await connection.commit()

    return ReorgAudit(
        id=audit_id,
        dst_session_id=src_id,
        src_session_id=dst_id,
        merged_at=merged_at,
        src_title=dst_title,
        boundary_msg_id=message_id,
        kind="move",
    )


async def list_audit_for_session(
    connection: aiosqlite.Connection,
    dst_session_id: str,
) -> list[ReorgAudit]:
    """Return all audit rows for ``dst_session_id``, oldest-first.

    Covers all three kinds (merge, split, move).  ``dst_session_id`` is
    always the session that hosts the divider — see module docstring for
    the per-kind semantics.
    """
    cursor = await connection.execute(
        f"{_SELECT_AUDIT_COLS} WHERE dst_session_id = ? ORDER BY merged_at ASC",
        (dst_session_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_audit(row) for row in rows]


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
        f"{_SELECT_AUDIT_COLS} WHERE id = ? AND dst_session_id = ?",
        (audit_id, dst_session_id),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    return _row_to_audit(row)


async def undo_merge_audit(
    connection: aiosqlite.Connection,
    audit_id: str,
    dst_session_id: str,
) -> str | None:
    """Atomically reverse any reorg operation and delete the audit row.

    Dispatches to kind-specific logic:

    * ``kind='merge'``: Re-creates the source session, moves the merged
      messages back, deletes the audit row.  Returns the id of the newly
      created session.
    * ``kind='split'``: Moves the split messages from the target back to
      ``dst_session_id``, deletes the audit row.  Returns
      ``dst_session_id`` (the original source that was split).
    * ``kind='move'``: Moves the single message from the target back to
      ``dst_session_id``, deletes the audit row.  Returns
      ``dst_session_id``.

    Returns ``None`` when the audit row is not found.
    Raises :class:`StaleAuditError` when the relevant session has been
    mutated after the recorded timestamp.
    """
    audit = await get_audit(connection, audit_id, dst_session_id)
    if audit is None:
        return None

    if audit.kind == "merge":
        return await _undo_merge(connection, audit)
    if audit.kind == "split":
        return await _undo_split(connection, audit)
    # kind == "move"
    return await _undo_move(connection, audit)


async def _undo_merge(
    connection: aiosqlite.Connection,
    audit: ReorgAudit,
) -> str:
    """Reverse a merge audit row.

    Re-creates the source session with its original title, moves the
    merged messages back, updates message counts on both sessions, and
    removes the audit row — all inside a single transaction.

    Returns the id of the newly created source session.

    Raises :class:`StaleAuditError` when messages have been added to
    ``dst_session_id`` after the merge, or when the boundary message has
    been moved away.
    """
    # --- Stale check: new messages added to dst after the merge. ---
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND created_at > ?",
        (audit.dst_session_id, audit.merged_at),
    )
    try:
        count_row = await cursor.fetchone()
    finally:
        await cursor.close()
    if count_row is not None and int(count_row[0]) > 0:
        raise StaleAuditError(
            f"destination session {audit.dst_session_id!r} has messages added after merge at "
            f"{audit.merged_at!r}; undo is not safe"
        )

    # --- Stale check: boundary message removed from dst. ---
    boundary_created_at: str | None = None
    if audit.boundary_msg_id is not None:
        cursor = await connection.execute(
            "SELECT created_at FROM messages WHERE id = ? AND session_id = ?",
            (audit.boundary_msg_id, audit.dst_session_id),
        )
        try:
            brow = await cursor.fetchone()
        finally:
            await cursor.close()
        if brow is None:
            raise StaleAuditError(
                f"boundary message {audit.boundary_msg_id!r} no longer exists in "
                f"destination session {audit.dst_session_id!r}; undo is not safe"
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
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND created_at >= ?",
            (audit.dst_session_id, boundary_created_at),
        )
        try:
            mc_row = await cursor.fetchone()
        finally:
            await cursor.close()
        moved_count = int(mc_row[0]) if mc_row is not None else 0

        await connection.execute(
            "UPDATE messages SET session_id = ? WHERE session_id = ? AND created_at >= ?",
            (new_src_id, audit.dst_session_id, boundary_created_at),
        )

    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - ?) WHERE id = ?",
        (moved_count, audit.dst_session_id),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = ? WHERE id = ?",
        (moved_count, new_src_id),
    )

    # --- Delete the audit row. ---
    await connection.execute("DELETE FROM reorg_audit WHERE id = ?", (audit.id,))

    await connection.commit()

    return new_src_id


async def _undo_split(
    connection: aiosqlite.Connection,
    audit: ReorgAudit,
) -> str:
    """Reverse a split audit row.

    Moves the split messages from ``src_session_id`` (the target that
    received them) back to ``dst_session_id`` (the original source that
    was split), then deletes the audit row.

    Raises :class:`StaleAuditError` when new messages have been added to
    the target session after the split, or when the boundary message is no
    longer in the target session.

    Returns ``dst_session_id`` — the restored source session.
    """
    # For split: src_session_id = actual target (where content went).
    target_id = audit.src_session_id
    host_id = audit.dst_session_id  # original source (hosts the divider)

    # --- Stale check: new messages added to target after split. ---
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND created_at > ?",
        (target_id, audit.merged_at),
    )
    try:
        count_row = await cursor.fetchone()
    finally:
        await cursor.close()
    if count_row is not None and int(count_row[0]) > 0:
        raise StaleAuditError(
            f"target session {target_id!r} has messages added after split at "
            f"{audit.merged_at!r}; undo is not safe"
        )

    # --- Stale check: boundary message removed from target. ---
    boundary_created_at: str | None = None
    if audit.boundary_msg_id is not None:
        cursor = await connection.execute(
            "SELECT created_at FROM messages WHERE id = ? AND session_id = ?",
            (audit.boundary_msg_id, target_id),
        )
        try:
            brow = await cursor.fetchone()
        finally:
            await cursor.close()
        if brow is None:
            raise StaleAuditError(
                f"boundary message {audit.boundary_msg_id!r} no longer exists in "
                f"target session {target_id!r}; undo is not safe"
            )
        boundary_created_at = str(brow[0])

    # --- Move messages back from target to host. ---
    moved_count = 0
    if boundary_created_at is not None:
        cursor = await connection.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND created_at >= ?",
            (target_id, boundary_created_at),
        )
        try:
            mc_row = await cursor.fetchone()
        finally:
            await cursor.close()
        moved_count = int(mc_row[0]) if mc_row is not None else 0

        await connection.execute(
            "UPDATE messages SET session_id = ? WHERE session_id = ? AND created_at >= ?",
            (host_id, target_id, boundary_created_at),
        )

    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - ?) WHERE id = ?",
        (moved_count, target_id),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = message_count + ? WHERE id = ?",
        (moved_count, host_id),
    )

    # --- Delete the audit row. ---
    await connection.execute("DELETE FROM reorg_audit WHERE id = ?", (audit.id,))

    await connection.commit()

    return host_id


async def _undo_move(
    connection: aiosqlite.Connection,
    audit: ReorgAudit,
) -> str:
    """Reverse a single-message move audit row.

    Moves the message identified by ``boundary_msg_id`` from
    ``src_session_id`` (the target that received it) back to
    ``dst_session_id`` (the original session), then deletes the audit row.

    Raises :class:`StaleAuditError` when the message is no longer in the
    target session.

    Returns ``dst_session_id`` — the restored host session.
    """
    target_id = audit.src_session_id
    host_id = audit.dst_session_id

    if audit.boundary_msg_id is None:
        # No message to reverse — just delete the audit row (degenerate case).
        await connection.execute("DELETE FROM reorg_audit WHERE id = ?", (audit.id,))
        await connection.commit()
        return host_id

    # --- Stale check: message no longer in target. ---
    cursor = await connection.execute(
        "SELECT id FROM messages WHERE id = ? AND session_id = ?",
        (audit.boundary_msg_id, target_id),
    )
    try:
        msg_row = await cursor.fetchone()
    finally:
        await cursor.close()
    if msg_row is None:
        raise StaleAuditError(
            f"moved message {audit.boundary_msg_id!r} no longer exists in "
            f"target session {target_id!r}; undo is not safe"
        )

    # --- Move message back. ---
    await connection.execute(
        "UPDATE messages SET session_id = ? WHERE id = ?",
        (host_id, audit.boundary_msg_id),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - 1) WHERE id = ?",
        (target_id,),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
        (host_id,),
    )

    # --- Delete the audit row. ---
    await connection.execute("DELETE FROM reorg_audit WHERE id = ?", (audit.id,))

    await connection.commit()

    return host_id


__all__ = [
    "ReorgAudit",
    "SplitResult",
    "StaleAuditError",
    "get_audit",
    "list_audit_for_session",
    "merge_sessions",
    "move_message_reorg",
    "split_session",
    "undo_merge_audit",
]
