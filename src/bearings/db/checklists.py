"""``checklist_items`` + ``paired_chats`` table queries.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``checklist_items`` and ``paired_chats``. Per
``docs/behavior/checklists.md`` the user observes a tree of items under
a checklist-kind session: pick / check / nest (Tab/Shift-Tab) / drag-
reorder / link to a paired chat / unlink / spawn legs. Per
``docs/behavior/paired-chats.md`` the leaf↔chat link is 1:1 and per-leg
audit rows live in ``paired_chats``.

Schema-vs-behavior notes
------------------------

* ``parent_item_id`` is a self-FK; per-parent ``sort_order`` orders
  siblings within their parent. Root items use ``parent_item_id IS
  NULL`` and share one sort scope.
* ``checked_at`` set ⇒ green pip; ``blocked_at`` set ⇒ amber/red/grey
  pip (color from :data:`bearings.config.constants.KNOWN_ITEM_OUTCOMES`
  category). The schema's ``blocked_*`` triple carries every
  non-completion category; rationale is documented inline at the
  constants module.
* ``chat_session_id`` is the live pair pointer; per
  ``docs/behavior/paired-chats.md`` "leaves only — schema-level
  enforcement of 'leaves only' lives in the API layer". This module
  enforces it at :func:`set_paired_chat` (rejects pairing a parent
  item).
* ``paired_chats`` is the per-leg audit log; the live link is on the
  item row. UNIQUE on ``(checklist_item_id, leg_number)``.

Public surface:

* :class:`ChecklistItem` — frozen row mirror with ``__post_init__``
  validation.
* :class:`PairedChatLeg` — frozen row mirror for ``paired_chats``.
* CRUD: :func:`create`, :func:`get`, :func:`list_for_checklist`,
  :func:`list_children`, :func:`update_label`, :func:`update_notes`,
  :func:`delete`.
* Picking / outcome state: :func:`mark_checked`, :func:`mark_unchecked`,
  :func:`mark_outcome` (blocked / failed / skipped), :func:`clear_outcome`.
* Linking: :func:`set_paired_chat`, :func:`clear_paired_chat`,
  :func:`record_leg`, :func:`close_leg`, :func:`list_legs`,
  :func:`count_legs`.
* Reordering / nesting: :func:`move_to_parent`, :func:`renumber_siblings`,
  :func:`indent`, :func:`outdent`.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH,
    CHECKLIST_ITEM_LABEL_MAX_LENGTH,
    CHECKLIST_ITEM_NOTES_MAX_LENGTH,
    CHECKLIST_SORT_ORDER_STEP,
    KNOWN_ITEM_OUTCOMES,
    KNOWN_PAIRED_CHAT_SPAWNED_BY,
)
from bearings.db._id import now_iso

# ---------------------------------------------------------------------------
# ChecklistItem.__post_init__ validators
# ---------------------------------------------------------------------------


def _validate_checklist_item_core(checklist_id: str, label: str, notes: str | None) -> None:
    """Raise if required strings are empty or optional fields exceed length caps."""
    if not checklist_id:
        raise ValueError("ChecklistItem.checklist_id must be non-empty")
    if not label:
        raise ValueError("ChecklistItem.label must be non-empty")
    if len(label) > CHECKLIST_ITEM_LABEL_MAX_LENGTH:
        raise ValueError(
            f"ChecklistItem.label must be ≤ {CHECKLIST_ITEM_LABEL_MAX_LENGTH} chars "
            f"(got {len(label)})"
        )
    if notes is not None and len(notes) > CHECKLIST_ITEM_NOTES_MAX_LENGTH:
        raise ValueError(
            f"ChecklistItem.notes must be ≤ {CHECKLIST_ITEM_NOTES_MAX_LENGTH} chars "
            f"(got {len(notes)})"
        )


def _validate_checklist_item_blocked(
    blocked_reason_category: str | None,
    blocked_reason_text: str | None,
) -> None:
    """Raise if blocked_reason fields violate their alphabet or length cap."""
    if blocked_reason_category is not None and blocked_reason_category not in KNOWN_ITEM_OUTCOMES:
        raise ValueError(
            f"ChecklistItem.blocked_reason_category {blocked_reason_category!r} "
            f"not in {sorted(KNOWN_ITEM_OUTCOMES)}"
        )
    if blocked_reason_text is not None and (
        len(blocked_reason_text) > CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH
    ):
        raise ValueError(
            f"ChecklistItem.blocked_reason_text must be ≤ "
            f"{CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH} chars "
            f"(got {len(blocked_reason_text)})"
        )


@dataclass(frozen=True)
class ChecklistItem:
    """Row mirror for the ``checklist_items`` table.

    Field semantics follow ``schema.sql``. A leaf item is one with no
    children (caller asks via :func:`list_children`); the dataclass
    itself does not track leaf-ness — the tree shape is materialised at
    query time. ``checked_at``/``blocked_at`` are mutually exclusive
    in practice (an item is either green or non-completed-with-reason),
    but the schema permits both NULL together (the not-yet-attempted
    state); the API layer enforces the exclusivity at write time.
    """

    id: int
    checklist_id: str
    parent_item_id: int | None
    label: str
    notes: str | None
    sort_order: int
    checked_at: str | None
    chat_session_id: str | None
    blocked_at: str | None
    blocked_reason_category: str | None
    blocked_reason_text: str | None
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        _validate_checklist_item_core(self.checklist_id, self.label, self.notes)
        _validate_checklist_item_blocked(self.blocked_reason_category, self.blocked_reason_text)
        # Schema permits parent_item_id == 0 by FK alone; reject it
        # explicitly so a buggy caller cannot create a self-referencing
        # cycle by handing back the row's own id.
        if self.parent_item_id is not None and self.parent_item_id == self.id:
            raise ValueError(
                f"ChecklistItem.parent_item_id == id ({self.id}); cycles are forbidden"
            )


@dataclass(frozen=True)
class PairedChatLeg:
    """Row mirror for the ``paired_chats`` table — one row per leg."""

    id: int
    checklist_item_id: int
    chat_session_id: str
    leg_number: int
    spawned_by: str
    created_at: str
    closed_at: str | None

    def __post_init__(self) -> None:
        if not self.chat_session_id:
            raise ValueError("PairedChatLeg.chat_session_id must be non-empty")
        if self.leg_number < 1:
            raise ValueError(f"PairedChatLeg.leg_number must be ≥ 1 (got {self.leg_number})")
        if self.spawned_by not in KNOWN_PAIRED_CHAT_SPAWNED_BY:
            raise ValueError(
                f"PairedChatLeg.spawned_by {self.spawned_by!r} "
                f"not in {sorted(KNOWN_PAIRED_CHAT_SPAWNED_BY)}"
            )


async def create(
    connection: aiosqlite.Connection,
    *,
    checklist_id: str,
    label: str,
    parent_item_id: int | None = None,
    notes: str | None = None,
    sort_order: int | None = None,
) -> ChecklistItem:
    """Insert a new item; auto-assigns ``sort_order`` after the last sibling.

    Validation runs in :class:`ChecklistItem.__post_init__` against a
    pre-INSERT phantom instance so a bad shape never touches the DB.
    """
    timestamp = now_iso()
    if sort_order is None:
        sort_order = await _next_sort_order(connection, checklist_id, parent_item_id)
    # Validate by constructing a phantom — id=0 is a placeholder.
    ChecklistItem(
        id=0,
        checklist_id=checklist_id,
        parent_item_id=parent_item_id,
        label=label,
        notes=notes,
        sort_order=sort_order,
        checked_at=None,
        chat_session_id=None,
        blocked_at=None,
        blocked_reason_category=None,
        blocked_reason_text=None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "INSERT INTO checklist_items "
        "(checklist_id, parent_item_id, label, notes, sort_order, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (checklist_id, parent_item_id, label, notes, sort_order, timestamp, timestamp),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover — sqlite always returns lastrowid
        raise RuntimeError("checklists.create: aiosqlite returned a None lastrowid")
    return ChecklistItem(
        id=int(new_id),
        checklist_id=checklist_id,
        parent_item_id=parent_item_id,
        label=label,
        notes=notes,
        sort_order=sort_order,
        checked_at=None,
        chat_session_id=None,
        blocked_at=None,
        blocked_reason_category=None,
        blocked_reason_text=None,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def _next_sort_order(
    connection: aiosqlite.Connection,
    checklist_id: str,
    parent_item_id: int | None,
) -> int:
    """Return the next available ``sort_order`` after the last sibling.

    Step is :data:`CHECKLIST_SORT_ORDER_STEP` so a future
    "insert between A and B" can pick a mid-point without a renumber.
    """
    if parent_item_id is None:
        cursor = await connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM checklist_items "
            "WHERE checklist_id = ? AND parent_item_id IS NULL",
            (checklist_id,),
        )
    else:
        cursor = await connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM checklist_items "
            "WHERE checklist_id = ? AND parent_item_id = ?",
            (checklist_id, parent_item_id),
        )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    last = 0 if row is None else int(row[0])
    return last + CHECKLIST_SORT_ORDER_STEP


async def get(connection: aiosqlite.Connection, item_id: int) -> ChecklistItem | None:
    """Fetch a single item by id; ``None`` if no such row."""
    cursor = await connection.execute(
        _SELECT_ITEM_COLUMNS + " WHERE id = ?",
        (item_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_item(row)


async def list_for_checklist(
    connection: aiosqlite.Connection,
    checklist_id: str,
) -> list[ChecklistItem]:
    """Every item under ``checklist_id``, parent-major then sort_order.

    Ordering: ``parent_item_id ASC NULLS FIRST, sort_order ASC``. Roots
    surface first (NULL parent first), then each parent's children block
    follows. Callers that want a tree structure assemble it client-side
    using :attr:`ChecklistItem.parent_item_id`.
    """
    cursor = await connection.execute(
        _SELECT_ITEM_COLUMNS + " WHERE checklist_id = ? "
        "ORDER BY (parent_item_id IS NOT NULL) ASC, parent_item_id ASC, sort_order ASC, id ASC",
        (checklist_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_item(row) for row in rows]


async def list_children(
    connection: aiosqlite.Connection,
    *,
    checklist_id: str,
    parent_item_id: int | None,
) -> list[ChecklistItem]:
    """Direct children of ``parent_item_id`` (or root when ``None``).

    Used by the leaf-detection helper :func:`is_leaf` and by the API
    layer to walk one level of the tree.
    """
    if parent_item_id is None:
        cursor = await connection.execute(
            _SELECT_ITEM_COLUMNS + " WHERE checklist_id = ? AND parent_item_id IS NULL "
            "ORDER BY sort_order ASC, id ASC",
            (checklist_id,),
        )
    else:
        cursor = await connection.execute(
            _SELECT_ITEM_COLUMNS + " WHERE checklist_id = ? AND parent_item_id = ? "
            "ORDER BY sort_order ASC, id ASC",
            (checklist_id, parent_item_id),
        )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_item(row) for row in rows]


async def is_leaf(connection: aiosqlite.Connection, item_id: int) -> bool:
    """``True`` when no row has ``parent_item_id == item_id``."""
    cursor = await connection.execute(
        "SELECT 1 FROM checklist_items WHERE parent_item_id = ? LIMIT 1",
        (item_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return row is None


async def update_label(
    connection: aiosqlite.Connection,
    item_id: int,
    *,
    label: str,
) -> ChecklistItem | None:
    """Replace ``label``; returns the new value or ``None`` if absent."""
    existing = await get(connection, item_id)
    if existing is None:
        return None
    if not label:
        raise ValueError("update_label: label must be non-empty")
    if len(label) > CHECKLIST_ITEM_LABEL_MAX_LENGTH:
        raise ValueError(
            f"update_label: label must be ≤ {CHECKLIST_ITEM_LABEL_MAX_LENGTH} chars "
            f"(got {len(label)})"
        )
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET label = ?, updated_at = ? WHERE id = ?",
        (label, timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def update_notes(
    connection: aiosqlite.Connection,
    item_id: int,
    *,
    notes: str | None,
) -> ChecklistItem | None:
    """Replace ``notes`` (``None`` clears); returns the new value or ``None``."""
    existing = await get(connection, item_id)
    if existing is None:
        return None
    if notes is not None and len(notes) > CHECKLIST_ITEM_NOTES_MAX_LENGTH:
        raise ValueError(
            f"update_notes: notes must be ≤ {CHECKLIST_ITEM_NOTES_MAX_LENGTH} chars "
            f"(got {len(notes)})"
        )
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET notes = ?, updated_at = ? WHERE id = ?",
        (notes, timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def delete(connection: aiosqlite.Connection, item_id: int) -> bool:
    """Delete one item; cascades to children + paired_chats per FK.

    Returns ``True`` if a row was removed. Per
    ``docs/behavior/checklists.md`` §"Item edit / add / delete /
    reorder" — "Delete cascades to children (a parent's deletion
    removes its subtree) and to any paired chat session that exists for
    the item — the chat row is removed from the sidebar." The
    chat-session deletion side is the API layer's responsibility (this
    module owns only the items + paired_chats rows).
    """
    cursor = await connection.execute(
        "DELETE FROM checklist_items WHERE id = ?",
        (item_id,),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


async def mark_checked(
    connection: aiosqlite.Connection,
    item_id: int,
) -> ChecklistItem | None:
    """Set ``checked_at`` to now; clears any non-completion outcome.

    Per behavior/checklists.md the user clicking a leaf's checkbox
    transitions the item to green and clears any prior amber/red/grey
    state. Schema-level: writes ``checked_at = now`` and NULLs the
    ``blocked_*`` triple in one UPDATE so the row is in a consistent
    "completed" shape (not "completed-AND-blocked").
    """
    existing = await get(connection, item_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET checked_at = ?, blocked_at = NULL, "
        "blocked_reason_category = NULL, blocked_reason_text = NULL, updated_at = ? "
        "WHERE id = ?",
        (timestamp, timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def mark_unchecked(
    connection: aiosqlite.Connection,
    item_id: int,
) -> ChecklistItem | None:
    """Clear ``checked_at`` (revert to not-yet-completed)."""
    existing = await get(connection, item_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET checked_at = NULL, updated_at = ? WHERE id = ?",
        (timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def mark_outcome(
    connection: aiosqlite.Connection,
    item_id: int,
    *,
    category: str,
    reason: str | None = None,
) -> ChecklistItem | None:
    """Set a non-completion outcome (blocked / failed / skipped).

    ``category`` must be in
    :data:`bearings.config.constants.KNOWN_ITEM_OUTCOMES`.  Any prior
    ``checked_at`` is cleared (an item cannot be both green AND
    non-completed). The reason text is optional but capped per
    :data:`CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH`.
    """
    if category not in KNOWN_ITEM_OUTCOMES:
        raise ValueError(
            f"mark_outcome: category {category!r} not in {sorted(KNOWN_ITEM_OUTCOMES)}"
        )
    if reason is not None and len(reason) > CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH:
        raise ValueError(
            f"mark_outcome: reason must be ≤ {CHECKLIST_ITEM_BLOCKED_REASON_MAX_LENGTH} chars "
            f"(got {len(reason)})"
        )
    existing = await get(connection, item_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET blocked_at = ?, blocked_reason_category = ?, "
        "blocked_reason_text = ?, checked_at = NULL, updated_at = ? WHERE id = ?",
        (timestamp, category, reason, timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def clear_outcome(
    connection: aiosqlite.Connection,
    item_id: int,
) -> ChecklistItem | None:
    """Clear any non-completion outcome (back to not-yet-attempted)."""
    existing = await get(connection, item_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET blocked_at = NULL, blocked_reason_category = NULL, "
        "blocked_reason_text = NULL, updated_at = ? WHERE id = ?",
        (timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def set_paired_chat(
    connection: aiosqlite.Connection,
    item_id: int,
    *,
    chat_session_id: str,
) -> ChecklistItem | None:
    """Set ``chat_session_id`` on the item (live pair pointer).

    Per ``docs/behavior/paired-chats.md`` "leaves only — schema-level
    enforcement of 'leaves only' lives in the API layer". Enforce it
    here as a defensive gate: rejecting a pair on a parent matches the
    user-observable rule "Paired-chat affordances … only render on
    leaves, since parents are not work units" (checklists.md).
    """
    existing = await get(connection, item_id)
    if existing is None:
        return None
    if not chat_session_id:
        raise ValueError("set_paired_chat: chat_session_id must be non-empty")
    if not await is_leaf(connection, item_id):
        raise ValueError(
            f"set_paired_chat: item {item_id} is a parent — pair affordances are leaves-only "
            "per docs/behavior/paired-chats.md"
        )
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET chat_session_id = ?, updated_at = ? WHERE id = ?",
        (chat_session_id, timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def clear_paired_chat(
    connection: aiosqlite.Connection,
    item_id: int,
) -> ChecklistItem | None:
    """Clear the live pair pointer (the chat keeps its history)."""
    existing = await get(connection, item_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET chat_session_id = NULL, updated_at = ? WHERE id = ?",
        (timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def record_leg(
    connection: aiosqlite.Connection,
    *,
    checklist_item_id: int,
    chat_session_id: str,
    spawned_by: str,
    leg_number: int | None = None,
) -> PairedChatLeg:
    """Insert a new ``paired_chats`` row.

    ``leg_number`` defaults to the next leg in sequence (last + 1).
    UNIQUE on ``(checklist_item_id, leg_number)`` rejects re-runs at the
    boundary; :class:`aiosqlite.IntegrityError` surfaces unchanged.
    """
    if spawned_by not in KNOWN_PAIRED_CHAT_SPAWNED_BY:
        raise ValueError(
            f"record_leg: spawned_by {spawned_by!r} not in {sorted(KNOWN_PAIRED_CHAT_SPAWNED_BY)}"
        )
    if leg_number is None:
        leg_number = await count_legs(connection, checklist_item_id) + 1
    timestamp = now_iso()
    cursor = await connection.execute(
        "INSERT INTO paired_chats "
        "(checklist_item_id, chat_session_id, leg_number, spawned_by, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (checklist_item_id, chat_session_id, leg_number, spawned_by, timestamp),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover
        raise RuntimeError("checklists.record_leg: aiosqlite returned a None lastrowid")
    return PairedChatLeg(
        id=int(new_id),
        checklist_item_id=checklist_item_id,
        chat_session_id=chat_session_id,
        leg_number=leg_number,
        spawned_by=spawned_by,
        created_at=timestamp,
        closed_at=None,
    )


async def close_leg(
    connection: aiosqlite.Connection,
    leg_id: int,
) -> bool:
    """Stamp ``closed_at`` on a leg row; returns ``True`` if updated.

    Idempotent — closing an already-closed leg is a no-op (the
    ``closed_at`` value is overwritten with the new timestamp). The
    boolean reflects whether a row matched.
    """
    timestamp = now_iso()
    cursor = await connection.execute(
        "UPDATE paired_chats SET closed_at = ? WHERE id = ?",
        (timestamp, leg_id),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


async def list_legs(
    connection: aiosqlite.Connection,
    checklist_item_id: int,
) -> list[PairedChatLeg]:
    """Every leg for ``checklist_item_id`` in leg-number order (oldest-first)."""
    cursor = await connection.execute(
        "SELECT id, checklist_item_id, chat_session_id, leg_number, spawned_by, "
        "created_at, closed_at FROM paired_chats WHERE checklist_item_id = ? "
        "ORDER BY leg_number ASC",
        (checklist_item_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_leg(row) for row in rows]


async def count_legs(
    connection: aiosqlite.Connection,
    checklist_item_id: int,
) -> int:
    """Number of legs for ``checklist_item_id``."""
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM paired_chats WHERE checklist_item_id = ?",
        (checklist_item_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return 0
    return int(row[0])


async def move_to_parent(
    connection: aiosqlite.Connection,
    item_id: int,
    *,
    parent_item_id: int | None,
    sort_order: int | None = None,
) -> ChecklistItem | None:
    """Reparent ``item_id``; auto-assigns ``sort_order`` after last sibling.

    Per behavior/checklists.md §"Reorder (drag)" — "Drag is constrained
    to legal positions only — an item cannot be dropped inside its own
    subtree". Enforce: walking up from ``parent_item_id`` must not reach
    ``item_id``. Self-parent is rejected directly.
    """
    existing = await get(connection, item_id)
    if existing is None:
        return None
    if parent_item_id == item_id:
        raise ValueError(f"move_to_parent: cannot parent {item_id} to itself")
    if parent_item_id is not None and await _is_descendant(connection, item_id, parent_item_id):
        raise ValueError(
            f"move_to_parent: cannot move {item_id} into its own subtree "
            f"(parent_item_id={parent_item_id})"
        )
    if sort_order is None:
        sort_order = await _next_sort_order(connection, existing.checklist_id, parent_item_id)
    timestamp = now_iso()
    await connection.execute(
        "UPDATE checklist_items SET parent_item_id = ?, sort_order = ?, updated_at = ? "
        "WHERE id = ?",
        (parent_item_id, sort_order, timestamp, item_id),
    )
    await connection.commit()
    return await get(connection, item_id)


async def _is_descendant(
    connection: aiosqlite.Connection,
    ancestor_id: int,
    candidate_id: int,
) -> bool:
    """True if ``candidate_id`` is in the subtree rooted at ``ancestor_id``.

    Walk up from ``candidate_id`` via ``parent_item_id`` and stop on
    NULL or a self-reference. The walk is bounded by the checklist's
    nesting depth (in practice ≪ 100); a defensive iteration cap stops
    a malformed cycle from looping forever.
    """
    cursor_id: int | None = candidate_id
    seen: set[int] = set()
    while cursor_id is not None:
        if cursor_id == ancestor_id:
            return True
        if cursor_id in seen:  # pragma: no cover — schema FK prevents cycles
            return False
        seen.add(cursor_id)
        cursor = await connection.execute(
            "SELECT parent_item_id FROM checklist_items WHERE id = ?",
            (cursor_id,),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        if row is None:
            return False
        cursor_id = None if row[0] is None else int(row[0])
    return False


async def renumber_siblings(
    connection: aiosqlite.Connection,
    *,
    checklist_id: str,
    parent_item_id: int | None,
) -> None:
    """Compactly renumber a sibling group at :data:`CHECKLIST_SORT_ORDER_STEP`.

    Used after a reorder operation that collapsed the gap between two
    siblings below the step (rare; bulk drag-reorder). Renumbering
    preserves the visible order and re-spreads sort_order values so the
    next mid-point insert has room.
    """
    siblings = await list_children(
        connection, checklist_id=checklist_id, parent_item_id=parent_item_id
    )
    timestamp = now_iso()
    for index, sibling in enumerate(siblings, start=1):
        new_order = index * CHECKLIST_SORT_ORDER_STEP
        if new_order != sibling.sort_order:
            await connection.execute(
                "UPDATE checklist_items SET sort_order = ?, updated_at = ? WHERE id = ?",
                (new_order, timestamp, sibling.id),
            )
    await connection.commit()


async def indent(
    connection: aiosqlite.Connection,
    item_id: int,
) -> ChecklistItem | None:
    """Tab — nest under the previous sibling (no-op at boundary).

    Per behavior/checklists.md §"Reorder (keyboard)" — "Tab nests the
    item under its previous sibling at the same indent level". No-op
    when the item has no previous sibling.
    """
    existing = await get(connection, item_id)
    if existing is None:
        return None
    siblings = await list_children(
        connection,
        checklist_id=existing.checklist_id,
        parent_item_id=existing.parent_item_id,
    )
    prev: int | None = None
    for sibling in siblings:
        if sibling.id == item_id:
            break
        prev = sibling.id
    if prev is None:
        return existing
    return await move_to_parent(connection, item_id, parent_item_id=prev)


async def outdent(
    connection: aiosqlite.Connection,
    item_id: int,
) -> ChecklistItem | None:
    """Shift+Tab — pop out one nesting level (no-op at root).

    Per behavior/checklists.md — "Shift+Tab pops it back out one nesting
    level (parent → grandparent)". No-op when the item is at root
    (``parent_item_id IS NULL``). The new sort_order places the item
    immediately after its former parent in the grandparent's scope.
    """
    existing = await get(connection, item_id)
    if existing is None:
        return None
    if existing.parent_item_id is None:
        return existing
    parent = await get(connection, existing.parent_item_id)
    if parent is None:  # pragma: no cover — FK on checklist_items.parent_item_id
        return existing
    grandparent_id = parent.parent_item_id
    new_sort_order = parent.sort_order + 1  # immediately after parent in grandparent's scope
    return await move_to_parent(
        connection,
        item_id,
        parent_item_id=grandparent_id,
        sort_order=new_sort_order,
    )


_SELECT_ITEM_COLUMNS = (
    "SELECT id, checklist_id, parent_item_id, label, notes, sort_order, "
    "checked_at, chat_session_id, blocked_at, blocked_reason_category, "
    "blocked_reason_text, created_at, updated_at FROM checklist_items"
)


def _row_to_item(row: aiosqlite.Row | tuple[object, ...]) -> ChecklistItem:
    """Translate a raw SELECT tuple to a validated :class:`ChecklistItem`."""
    return ChecklistItem(
        id=int(str(row[0])),
        checklist_id=str(row[1]),
        parent_item_id=None if row[2] is None else int(str(row[2])),
        label=str(row[3]),
        notes=None if row[4] is None else str(row[4]),
        sort_order=int(str(row[5])),
        checked_at=None if row[6] is None else str(row[6]),
        chat_session_id=None if row[7] is None else str(row[7]),
        blocked_at=None if row[8] is None else str(row[8]),
        blocked_reason_category=None if row[9] is None else str(row[9]),
        blocked_reason_text=None if row[10] is None else str(row[10]),
        created_at=str(row[11]),
        updated_at=str(row[12]),
    )


def _row_to_leg(row: aiosqlite.Row | tuple[object, ...]) -> PairedChatLeg:
    """Translate a raw SELECT tuple to a validated :class:`PairedChatLeg`."""
    return PairedChatLeg(
        id=int(str(row[0])),
        checklist_item_id=int(str(row[1])),
        chat_session_id=str(row[2]),
        leg_number=int(str(row[3])),
        spawned_by=str(row[4]),
        created_at=str(row[5]),
        closed_at=None if row[6] is None else str(row[6]),
    )


__all__ = [
    "ChecklistItem",
    "PairedChatLeg",
    "clear_outcome",
    "clear_paired_chat",
    "close_leg",
    "count_legs",
    "create",
    "delete",
    "get",
    "indent",
    "is_leaf",
    "list_children",
    "list_for_checklist",
    "list_legs",
    "mark_checked",
    "mark_outcome",
    "mark_unchecked",
    "move_to_parent",
    "outdent",
    "record_leg",
    "renumber_siblings",
    "set_paired_chat",
    "update_label",
    "update_notes",
]
