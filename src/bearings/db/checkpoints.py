"""``checkpoints`` table queries — Bearings' user-facing named snapshots.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``checkpoints``. Per arch §5 #12 the rebuild keeps
Bearings' own checkpoint table rather than the SDK's
``enable_file_checkpointing`` automatic-write primitive — the user
creates checkpoints intentionally per ``docs/behavior/chat.md`` §"Slash
commands in the composer" (``/checkpoint`` slash command), and the
primary action on a checkpoint is ``checkpoint.fork`` (per
``docs/behavior/context-menus.md`` §"Checkpoint (gutter chip)") which
spawns a sibling session sharing history up to the checkpoint
message. There is intentionally no "restore overwrite current session"
action in v1 behavior — the docs name only ``fork`` /
``copy_label`` / ``copy_id`` / ``delete``.

Public surface:

* :class:`Checkpoint` — frozen dataclass row mirror.
* :func:`create` — insert a new checkpoint row; returns the populated
  :class:`Checkpoint`.
* :func:`get` — single-row lookup by id; returns ``None`` if absent.
* :func:`list_for_session` — every checkpoint for one session,
  newest-first per the index on ``(session_id, created_at DESC)``.
* :func:`count_for_session` — number of checkpoints for one session
  (used by the API layer to enforce
  :data:`bearings.config.constants.MAX_CHECKPOINTS_PER_SESSION` per
  arch §1.1.3).
* :func:`delete` — single-row delete; returns ``True`` if a row was
  removed.

Validation discipline lives in :class:`Checkpoint.__post_init__` so a
shape violation surfaces at construction time rather than at INSERT
time. Label length is capped at
:data:`bearings.config.constants.CHECKPOINT_LABEL_MAX_LENGTH` per the
"no inline literals" gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import CHECKPOINT_LABEL_MAX_LENGTH
from bearings.db._id import new_id, now_iso

# Per-row id prefix (per :mod:`bearings.db._id` convention; ``cpt_`` for
# checkpoints so a leaked id in a log is self-describing).
_CHECKPOINT_ID_PREFIX = "cpt"


@dataclass(frozen=True)
class Checkpoint:
    """Row mirror for the ``checkpoints`` table.

    Field semantics follow ``schema.sql``:

    * ``id`` — TEXT primary key (``cpt_<32-hex>``).
    * ``session_id`` — TEXT FK to ``sessions(id)`` ON DELETE CASCADE.
    * ``message_id`` — TEXT FK to ``messages(id)`` ON DELETE CASCADE;
      identifies the assistant message at which the gutter chip renders.
    * ``label`` — non-empty, ≤
      :data:`bearings.config.constants.CHECKPOINT_LABEL_MAX_LENGTH`
      chars; the user-visible chip text (``docs/behavior/chat.md``
      §"Slash commands in the composer").
    * ``created_at`` — ISO-8601 UTC string (matches the
      ``sessions``/``messages`` convention per ``schema.sql`` header
      comment).
    """

    id: str
    session_id: str
    message_id: str
    label: str
    created_at: str

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Checkpoint.id must be non-empty")
        if not self.session_id:
            raise ValueError("Checkpoint.session_id must be non-empty")
        if not self.message_id:
            raise ValueError("Checkpoint.message_id must be non-empty")
        if not self.label:
            raise ValueError("Checkpoint.label must be non-empty")
        if len(self.label) > CHECKPOINT_LABEL_MAX_LENGTH:
            raise ValueError(
                f"Checkpoint.label must be ≤ {CHECKPOINT_LABEL_MAX_LENGTH} chars "
                f"(got {len(self.label)})"
            )
        if not self.created_at:
            raise ValueError("Checkpoint.created_at must be non-empty")


async def create(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    message_id: str,
    label: str,
) -> Checkpoint:
    """Insert a new checkpoint row and return the populated dataclass.

    Caller is responsible for committing; this matches the convention
    other ``bearings.db`` query modules will adopt (single-statement
    helpers, transaction control belongs to the API handler one layer
    up). The returned :class:`Checkpoint` is constructed *before* the
    INSERT so dataclass validation fires before any DB write — a label
    that violates :data:`CHECKPOINT_LABEL_MAX_LENGTH` raises and the
    DB stays untouched.
    """
    checkpoint = Checkpoint(
        id=new_id(_CHECKPOINT_ID_PREFIX),
        session_id=session_id,
        message_id=message_id,
        label=label,
        created_at=now_iso(),
    )
    await connection.execute(
        "INSERT INTO checkpoints (id, session_id, message_id, label, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            checkpoint.id,
            checkpoint.session_id,
            checkpoint.message_id,
            checkpoint.label,
            checkpoint.created_at,
        ),
    )
    await connection.commit()
    return checkpoint


async def get(connection: aiosqlite.Connection, checkpoint_id: str) -> Checkpoint | None:
    """Fetch a single checkpoint by id; ``None`` if no such row.

    Returning ``None`` (rather than raising) mirrors the pattern the API
    layer (item 1.10) needs to surface a 404 cleanly without translating
    an exception. Caller decides what an absent row means.
    """
    cursor = await connection.execute(
        "SELECT id, session_id, message_id, label, created_at FROM checkpoints WHERE id = ?",
        (checkpoint_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    return _row_to_checkpoint(row)


async def list_for_session(
    connection: aiosqlite.Connection,
    session_id: str,
) -> list[Checkpoint]:
    """Every checkpoint for ``session_id``, newest-first.

    Order matches the partial index ``idx_checkpoints_session_id_created_at``
    so this query is index-scan only. The list comprehension below
    materialises eagerly because aiosqlite cursors must close before
    the connection is reused; for sessions with hundreds of checkpoints
    a paging interface lives in the API layer, not here.
    """
    cursor = await connection.execute(
        "SELECT id, session_id, message_id, label, created_at "
        "FROM checkpoints WHERE session_id = ? ORDER BY created_at DESC, id DESC",
        (session_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_checkpoint(row) for row in rows]


async def count_for_session(
    connection: aiosqlite.Connection,
    session_id: str,
) -> int:
    """Number of checkpoints for ``session_id``.

    Used by the API layer (item 1.10) to enforce
    :data:`bearings.config.constants.MAX_CHECKPOINTS_PER_SESSION`
    before inserting a new checkpoint row.
    """
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM checkpoints WHERE session_id = ?",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return 0
    return int(row[0])


async def delete(connection: aiosqlite.Connection, checkpoint_id: str) -> bool:
    """Delete one checkpoint by id; returns ``True`` if a row was removed.

    The boolean return is the API layer's signal for 404 vs 204:
    ``False`` → the row never existed (or was already deleted) →
    surface a 404 to the caller; ``True`` → the row existed and was
    removed → 204.
    """
    cursor = await connection.execute(
        "DELETE FROM checkpoints WHERE id = ?",
        (checkpoint_id,),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


async def import_checkpoint(
    connection: aiosqlite.Connection,
    *,
    checkpoint_id: str,
    session_id: str,
    message_id: str,
    label: str,
    created_at: str,
) -> Checkpoint:
    """Insert a checkpoint row preserving the original id and timestamps.

    Used exclusively by ``POST /api/sessions/import`` to restore a
    checkpoint from an export blob.  Unlike :func:`create`, which
    generates a new id and timestamp, this function preserves the
    original values so a round-trip export→import produces identical
    checkpoint ids and ordering.  Validation fires via
    :class:`Checkpoint.__post_init__` before the INSERT so a bad shape
    surfaces as a ``ValueError`` rather than a DB constraint failure.
    """
    cp = Checkpoint(
        id=checkpoint_id,
        session_id=session_id,
        message_id=message_id,
        label=label,
        created_at=created_at,
    )
    await connection.execute(
        "INSERT INTO checkpoints (id, session_id, message_id, label, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (cp.id, cp.session_id, cp.message_id, cp.label, cp.created_at),
    )
    await connection.commit()
    return cp


def _row_to_checkpoint(row: aiosqlite.Row | tuple[object, ...]) -> Checkpoint:
    """Translate a raw SELECT tuple to a validated :class:`Checkpoint`."""
    return Checkpoint(
        id=str(row[0]),
        session_id=str(row[1]),
        message_id=str(row[2]),
        label=str(row[3]),
        created_at=str(row[4]),
    )


__all__ = [
    "Checkpoint",
    "count_for_session",
    "create",
    "delete",
    "get",
    "import_checkpoint",
    "list_for_session",
]
