"""``tag_memories`` table queries — system-prompt fragments per tag.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``tag_memories``. Per arch §1.1.3 the boundary
between "tags as labels" and "tag memories as system-prompt fragments"
is visible by file split: the prompt assembler (item 1.5+) reads tag
memories per turn so edits take effect on the next turn without runner
respawn (per arch §6.3 "Layered system-prompt assembler with per-turn
re-read").

Lifecycle / ordering
--------------------

The schema does not declare an explicit ``sort_order`` column; memories
list ordered by ``id ASC`` (insertion order). The ``enabled`` flag is
the soft-delete carrier — a memory toggled off is excluded from the
prompt assembler's input but kept in storage so a user can re-enable
without retyping. The ``ON DELETE CASCADE`` on ``tag_id`` means
deleting a tag sweeps its memories.

Public surface:

* :class:`TagMemory` — frozen dataclass row mirror.
* :class:`AllMemoriesRow` — join of ``tags`` + ``tag_memories`` for
  the global-index list endpoint (``GET /api/memories``).
* :func:`create`, :func:`get`, :func:`list_for_tag`, :func:`list_all`,
  :func:`update`, :func:`delete` — CRUD; same return-shape conventions
  as :mod:`bearings.db.tags`.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    MEMORY_BODY_PREVIEW_MAX_LENGTH,
    TAG_MEMORY_BODY_MAX_LENGTH,
    TAG_MEMORY_TITLE_MAX_LENGTH,
)
from bearings.db._id import now_iso


@dataclass(frozen=True)
class TagMemory:
    """Row mirror for the ``tag_memories`` table.

    Field semantics follow ``schema.sql``:

    * ``id`` — INTEGER PRIMARY KEY AUTOINCREMENT.
    * ``tag_id`` — INTEGER FK to ``tags(id)`` ON DELETE CASCADE.
    * ``title`` — non-empty,
      ≤ :data:`bearings.config.constants.TAG_MEMORY_TITLE_MAX_LENGTH`
      chars; the user-visible header in the memory editor.
    * ``body`` — non-empty,
      ≤ :data:`bearings.config.constants.TAG_MEMORY_BODY_MAX_LENGTH`
      chars; the prompt-fragment text the assembler injects.
    * ``enabled`` — soft-disable flag; ``False`` excludes the memory
      from the assembler's input without deleting it.
    * ``created_at`` / ``updated_at`` — ISO-8601 UTC strings.
    """

    id: int
    tag_id: int
    title: str
    body: str
    enabled: bool
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError("TagMemory.title must be non-empty")
        if len(self.title) > TAG_MEMORY_TITLE_MAX_LENGTH:
            raise ValueError(
                f"TagMemory.title must be ≤ {TAG_MEMORY_TITLE_MAX_LENGTH} chars "
                f"(got {len(self.title)})"
            )
        if not self.body:
            raise ValueError("TagMemory.body must be non-empty")
        if len(self.body) > TAG_MEMORY_BODY_MAX_LENGTH:
            raise ValueError(
                f"TagMemory.body must be ≤ {TAG_MEMORY_BODY_MAX_LENGTH} chars "
                f"(got {len(self.body)})"
            )
        if self.tag_id <= 0:
            raise ValueError(f"TagMemory.tag_id must be > 0 (got {self.tag_id})")


@dataclass(frozen=True)
class AllMemoriesRow:
    """Denormalised row for the global memories index (``GET /api/memories``).

    Joins ``tag_memories`` with ``tags`` so the flat-list view can
    render tag context without a second round-trip. ``memory_body_preview``
    is the body truncated to
    :data:`bearings.config.constants.MEMORY_BODY_PREVIEW_MAX_LENGTH`
    chars — the full body is still reachable via ``GET /api/memories/{id}``.

    Sorted by ``(tag_name ASC, memory_title ASC)`` so the list groups
    by tag naturally and memories within each tag are alphabetical.
    """

    tag_id: int
    tag_name: str
    tag_color: str | None
    memory_id: int
    memory_title: str
    memory_body_preview: str
    enabled: bool
    updated_at: str


async def list_all(
    connection: aiosqlite.Connection,
    *,
    only_enabled: bool = False,
) -> list[AllMemoriesRow]:
    """All memories across every tag, sorted by tag name then memory title.

    ``only_enabled=True`` restricts to memories with ``enabled = 1``;
    useful for the same "prompt-assembler consumer" path that
    :func:`list_for_tag` supports, and exercised by the acceptance
    criteria's ``?only_enabled`` query variant.
    """
    where = " WHERE m.enabled = 1" if only_enabled else ""
    cursor = await connection.execute(
        "SELECT t.id, t.name, t.color, m.id, m.title, m.body, m.enabled, m.updated_at "
        "FROM tag_memories m "
        "JOIN tags t ON t.id = m.tag_id" + where + " ORDER BY t.name ASC, m.title ASC",
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_all_memories_row(row) for row in rows]


async def create(
    connection: aiosqlite.Connection,
    *,
    tag_id: int,
    title: str,
    body: str,
    enabled: bool = True,
) -> TagMemory:
    """Insert a new tag-memory row and return the populated dataclass.

    Validation runs in :class:`TagMemory.__post_init__` (built before
    the INSERT) so a bad shape never touches the DB. FK violation on
    ``tag_id`` raises :class:`aiosqlite.IntegrityError` unchanged.
    """
    timestamp = now_iso()
    cursor = await connection.execute(
        "INSERT INTO tag_memories (tag_id, title, body, enabled, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tag_id, title, body, 1 if enabled else 0, timestamp, timestamp),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover — sqlite always returns a rowid on INSERT
        raise RuntimeError("memories.create: aiosqlite returned a None lastrowid")
    return TagMemory(
        id=int(new_id),
        tag_id=tag_id,
        title=title,
        body=body,
        enabled=enabled,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def get(connection: aiosqlite.Connection, memory_id: int) -> TagMemory | None:
    """Fetch a single tag-memory by id; ``None`` if no such row."""
    cursor = await connection.execute(
        _SELECT_MEMORY_COLUMNS + " WHERE id = ?",
        (memory_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_memory(row)


async def list_for_tag(
    connection: aiosqlite.Connection,
    tag_id: int,
    *,
    only_enabled: bool = False,
) -> list[TagMemory]:
    """Every memory attached to ``tag_id``, ordered by ``id ASC``.

    ``only_enabled=True`` filters to memories with ``enabled = 1``;
    the prompt assembler (item 1.5+) reads with that filter so toggled-
    off memories don't reach the model. The API layer's "list memories
    for editing" path passes ``only_enabled=False`` so the editor sees
    every row including disabled ones.
    """
    if only_enabled:
        cursor = await connection.execute(
            _SELECT_MEMORY_COLUMNS + " WHERE tag_id = ? AND enabled = 1 ORDER BY id ASC",
            (tag_id,),
        )
    else:
        cursor = await connection.execute(
            _SELECT_MEMORY_COLUMNS + " WHERE tag_id = ? ORDER BY id ASC",
            (tag_id,),
        )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_memory(row) for row in rows]


async def update(
    connection: aiosqlite.Connection,
    memory_id: int,
    *,
    title: str,
    body: str,
    enabled: bool,
) -> TagMemory | None:
    """Replace a memory's mutable fields; returns the new value (or ``None``).

    ``None`` is returned when no row matches ``memory_id`` (404-friendly
    contract). ``tag_id``, ``created_at`` are preserved; ``updated_at``
    is bumped. The full mutable field set is required (not partial)
    matching the templates / tags update contract — partial updates
    would force a SELECT-then-merge dance whose semantics differ from
    a clean replace.
    """
    existing = await get(connection, memory_id)
    if existing is None:
        return None
    timestamp = now_iso()
    cursor = await connection.execute(
        "UPDATE tag_memories SET title = ?, body = ?, enabled = ?, updated_at = ? WHERE id = ?",
        (title, body, 1 if enabled else 0, timestamp, memory_id),
    )
    await cursor.close()
    await connection.commit()
    return TagMemory(
        id=memory_id,
        tag_id=existing.tag_id,
        title=title,
        body=body,
        enabled=enabled,
        created_at=existing.created_at,
        updated_at=timestamp,
    )


async def delete(connection: aiosqlite.Connection, memory_id: int) -> bool:
    """Delete one memory by id; returns ``True`` if a row was removed."""
    cursor = await connection.execute(
        "DELETE FROM tag_memories WHERE id = ?",
        (memory_id,),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


_SELECT_MEMORY_COLUMNS = (
    "SELECT id, tag_id, title, body, enabled, created_at, updated_at FROM tag_memories"
)


def _row_to_all_memories_row(row: aiosqlite.Row | tuple[object, ...]) -> AllMemoriesRow:
    """Translate a raw join SELECT tuple to :class:`AllMemoriesRow`.

    Column order: tag.id, tag.name, tag.color, m.id, m.title, m.body,
    m.enabled, m.updated_at — matches the SELECT in :func:`list_all`.
    """
    # Column order from list_all SELECT:
    # 0:t.id  1:t.name  2:t.color  3:m.id  4:m.title  5:m.body  6:m.enabled  7:m.updated_at
    preview = str(row[5])[:MEMORY_BODY_PREVIEW_MAX_LENGTH]
    return AllMemoriesRow(
        tag_id=int(str(row[0])),
        tag_name=str(row[1]),
        tag_color=str(row[2]) if row[2] is not None else None,
        memory_id=int(str(row[3])),
        memory_title=str(row[4]),
        memory_body_preview=preview,
        enabled=bool(int(str(row[6]))),
        updated_at=str(row[7]),
    )


def _row_to_memory(row: aiosqlite.Row | tuple[object, ...]) -> TagMemory:
    """Translate a raw SELECT tuple to a validated :class:`TagMemory`."""
    return TagMemory(
        id=int(str(row[0])),
        tag_id=int(str(row[1])),
        title=str(row[2]),
        body=str(row[3]),
        enabled=bool(int(str(row[4]))),
        created_at=str(row[5]),
        updated_at=str(row[6]),
    )


__all__ = [
    "AllMemoriesRow",
    "TagMemory",
    "create",
    "delete",
    "get",
    "list_all",
    "list_for_tag",
    "update",
]
