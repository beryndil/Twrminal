"""``tags`` + ``session_tags`` table queries — sidebar categorisation surface.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``tags`` and the per-session join table
``session_tags``. Per ``docs/behavior/chat.md`` §"When the user creates
a chat" every chat may carry any number of tags, with cardinality
constraints on the ``project`` / ``severity`` classes enforced at the
API boundary. Per ``docs/behavior/checklists.md`` "the chat inherits
the checklist's working directory, model, and tags" — the inheritance
fields landed on ``tags`` are :attr:`Tag.default_model` and
:attr:`Tag.working_dir`. Per ``docs/behavior/context-menus.md`` §"Tag
(sidebar tag chip in the filter panel)" the user pins / unpins / edits
/ deletes tags from a right-click menu; the API surface for those
actions lives in :mod:`bearings.web.routes.tags` (item 1.4) on top of
this layer.

Tag classes
-----------

The tag set is partitioned by :attr:`Tag.class_` into three buckets the
UI renders as separate filter sections:

* ``project``  — ≤1 per session; drives sidebar grouping.
* ``severity`` — ≤1 per session; drives the header shield colour;
  carries no ``default_model`` / ``working_dir`` (rejected in
  :meth:`Tag.__post_init__`).
* ``general``  — many per session; catch-all for legacy
  slash-namespaced tags and free-form labels.

The schema CHECK constraint pins the alphabet
(:data:`bearings.config.constants.KNOWN_TAG_CLASSES`); new classes
amend the CHECK. Cardinality is enforced at the API boundary, not the
schema, so partial create-and-validate flows roll back cleanly.

Within a class, tags render in ``(pinned DESC, sort_order ASC, name
ASC)`` order. :func:`update_sort_orders` is the atomic per-class
re-sequencing path used by the drag-to-reorder UI on the ``/tags``
page.

Tag groups (deprecated)
-----------------------

Pre-class versions used slash-namespacing on the tag name
(``<group>/<name>``) — the separator is
:data:`bearings.config.constants.TAG_GROUP_SEPARATOR`. The convention
is retained for one release: legacy tags like ``bearings/architect``
keep working, classified as ``general``. The :attr:`Tag.group`
property and :func:`list_groups` helper still parse the prefix, marked
deprecated. New code should use ``class_`` instead.

Public surface:

* :class:`Tag` — frozen dataclass row mirror with
  ``__post_init__`` validation.
* :func:`create`, :func:`get`, :func:`get_by_name`, :func:`list_all`,
  :func:`list_for_session`, :func:`list_groups`, :func:`update`,
  :func:`delete` — tag CRUD; same return-shape conventions as
  :mod:`bearings.db.templates`.
* :func:`update_sort_orders` — atomic per-class re-sequencing.
* :func:`attach`, :func:`detach`, :func:`set_for_session` — the
  per-session join surface; :func:`set_for_session` is the
  single-call replace path the API layer uses when the user edits a
  session's tag set in one batch.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    KNOWN_EXECUTOR_MODELS,
    KNOWN_TAG_CLASSES,
    TAG_CLASS_GENERAL,
    TAG_CLASS_SEVERITY,
    TAG_COLOR_MAX_LENGTH,
    TAG_DEFAULT_SORT_ORDER,
    TAG_GROUP_SEPARATOR,
    TAG_NAME_MAX_LENGTH,
)
from bearings.db._id import now_iso
from bearings.db._validators import _is_known_model


@dataclass(frozen=True)
class Tag:
    """Row mirror for the ``tags`` table.

    Field semantics follow ``schema.sql``:

    * ``id`` — INTEGER PRIMARY KEY AUTOINCREMENT.
    * ``name`` — non-empty, ≤
      :data:`bearings.config.constants.TAG_NAME_MAX_LENGTH` chars,
      UNIQUE across the table. The slash-namespace convention is
      retained for back-compat — a legacy name like
      ``bearings/architect`` parses via :attr:`group` but the
      authoritative categorisation is :attr:`class_`.
    * ``color`` — optional cosmetic CSS string;
      ≤ :data:`bearings.config.constants.TAG_COLOR_MAX_LENGTH` chars.
    * ``default_model`` — optional executor short name from
      :data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS` or full
      SDK ID prefixed with
      :data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX`
      (mirrors :class:`bearings.db.templates.Template`'s validator and
      :class:`bearings.agent.routing.RoutingDecision`'s alphabet).
      Severity-class tags must leave this ``None``.
    * ``working_dir`` — optional absolute path the chat inherits when
      this tag is applied (per ``docs/behavior/checklists.md`` "the
      chat inherits the checklist's working directory…").
      Severity-class tags must leave this ``None``.
    * ``class_`` — partitions the tag set into ``'project'`` /
      ``'severity'`` / ``'general'`` (see
      :data:`bearings.config.constants.KNOWN_TAG_CLASSES`). The Python
      attribute is suffixed to dodge the keyword; the schema column
      and JSON wire shape use the bare ``class``.
    * ``sort_order`` — per-class display order. Lower renders first
      within its class; ties break on ``name ASC``.
    * ``created_at`` / ``updated_at`` — ISO-8601 UTC strings.
    """

    id: int
    name: str
    color: str | None
    default_model: str | None
    working_dir: str | None
    created_at: str
    updated_at: str
    pinned: bool = False
    class_: str = TAG_CLASS_GENERAL
    sort_order: int = TAG_DEFAULT_SORT_ORDER

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Tag.name must be non-empty")
        if len(self.name) > TAG_NAME_MAX_LENGTH:
            raise ValueError(
                f"Tag.name must be ≤ {TAG_NAME_MAX_LENGTH} chars (got {len(self.name)})"
            )
        if self.color is not None and len(self.color) > TAG_COLOR_MAX_LENGTH:
            raise ValueError(
                f"Tag.color must be ≤ {TAG_COLOR_MAX_LENGTH} chars (got {len(self.color)})"
            )
        if self.default_model is not None and not _is_known_model(self.default_model):
            raise ValueError(
                f"Tag.default_model {self.default_model!r} is neither a known short name "
                f"{sorted(KNOWN_EXECUTOR_MODELS)} nor a full SDK ID prefixed with "
                f"{EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
            )
        if self.working_dir is not None and not self.working_dir:
            raise ValueError("Tag.working_dir must be non-empty if provided")
        if self.class_ not in KNOWN_TAG_CLASSES:
            raise ValueError(f"Tag.class_ {self.class_!r} is not in {sorted(KNOWN_TAG_CLASSES)}")
        if self.class_ == TAG_CLASS_SEVERITY:
            if self.default_model is not None:
                raise ValueError(
                    "Tag.default_model must be None for severity-class tags "
                    "(severity is signalling, not configuration)"
                )
            if self.working_dir is not None:
                raise ValueError(
                    "Tag.working_dir must be None for severity-class tags "
                    "(severity is signalling, not configuration)"
                )
        if self.sort_order < 0:
            raise ValueError(f"Tag.sort_order must be non-negative (got {self.sort_order})")

    @property
    def group(self) -> str | None:
        """The slash-prefix group, or ``None`` for the default group.

        ``"bearings/architect"`` → ``"bearings"``;
        ``"general"`` → ``None``. **Deprecated** — use :attr:`class_`
        instead. Retained one release for legacy slash-namespaced
        names that pre-date the class column.
        """
        sep_index = self.name.find(TAG_GROUP_SEPARATOR)
        if sep_index <= 0:
            return None
        return self.name[:sep_index]


async def create(
    connection: aiosqlite.Connection,
    *,
    name: str,
    color: str | None = None,
    default_model: str | None = None,
    working_dir: str | None = None,
    class_: str = TAG_CLASS_GENERAL,
    sort_order: int = TAG_DEFAULT_SORT_ORDER,
) -> Tag:
    """Insert a new tag and return the populated dataclass.

    Validation runs in :class:`Tag.__post_init__` against a phantom
    pre-INSERT instance so a bad shape never touches the DB. Name
    uniqueness is enforced by the schema's ``UNIQUE`` constraint;
    :class:`aiosqlite.IntegrityError` surfaces unchanged so the API
    layer can translate to a 409.

    ``class_`` defaults to ``'general'`` so existing callers that
    pre-date the class column keep working without explicit threading.
    """
    timestamp = now_iso()
    # Build-and-discard a phantom Tag whose only purpose is to fire
    # the ``__post_init__`` validators before the INSERT. The id is a
    # placeholder; Tag does not validate id, so any non-zero integer
    # would do — ``0`` chosen so a future "id must be > 0" check would
    # fail loudly here rather than silently passing.
    Tag(
        id=0,
        name=name,
        color=color,
        default_model=default_model,
        working_dir=working_dir,
        pinned=False,
        class_=class_,
        sort_order=sort_order,
        created_at=timestamp,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "INSERT INTO tags "
        "(name, color, default_model, working_dir, pinned, class, sort_order, "
        " created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            color,
            default_model,
            working_dir,
            0,
            class_,
            sort_order,
            timestamp,
            timestamp,
        ),
    )
    new_id = cursor.lastrowid
    await cursor.close()
    await connection.commit()
    if new_id is None:  # pragma: no cover — sqlite always returns a rowid on INSERT
        raise RuntimeError("tags.create: aiosqlite returned a None lastrowid")
    return Tag(
        id=int(new_id),
        name=name,
        color=color,
        default_model=default_model,
        working_dir=working_dir,
        pinned=False,
        class_=class_,
        sort_order=sort_order,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def get(connection: aiosqlite.Connection, tag_id: int) -> Tag | None:
    """Fetch a single tag by id; ``None`` if no such row."""
    cursor = await connection.execute(
        _SELECT_TAG_COLUMNS + " WHERE id = ?",
        (tag_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_tag(row)


async def get_by_name(connection: aiosqlite.Connection, name: str) -> Tag | None:
    """Fetch a single tag by its UNIQUE ``name``; ``None`` if absent."""
    cursor = await connection.execute(
        _SELECT_TAG_COLUMNS + " WHERE name = ?",
        (name,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_tag(row)


async def list_all(
    connection: aiosqlite.Connection,
    *,
    class_: str | None = None,
    group: str | None = None,
) -> list[Tag]:
    """Every tag, ordered for filter-panel rendering; optionally filtered.

    Default ordering is ``(class ASC, sort_order ASC, name ASC)`` so the
    filter panel can iterate the result and emit one section per class
    in row order. Pinned-first ordering is layered by the caller —
    pinning is a render-time concern, not a query-time one (the
    sidebar floats pinned chips to the top of their section).

    ``class_`` filters to one of
    :data:`bearings.config.constants.KNOWN_TAG_CLASSES`; passing
    ``None`` returns every class.

    ``group`` is the deprecated slash-namespace prefix filter retained
    for legacy callers; it composes with ``class_`` via AND. Prefer
    ``class_`` for new code.
    """
    clauses: list[str] = []
    params: list[object] = []
    if class_ is not None:
        if class_ not in KNOWN_TAG_CLASSES:
            raise ValueError(f"list_all: class_ {class_!r} not in {sorted(KNOWN_TAG_CLASSES)}")
        clauses.append("class = ?")
        params.append(class_)
    if group:
        clauses.append("name LIKE ?")
        params.append(f"{group}{TAG_GROUP_SEPARATOR}%")
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    order_sql = " ORDER BY class ASC, sort_order ASC, name ASC"
    cursor = await connection.execute(
        _SELECT_TAG_COLUMNS + where_sql + order_sql,
        tuple(params),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_tag(row) for row in rows]


async def list_all_with_counts(
    connection: aiosqlite.Connection,
    *,
    class_: str | None = None,
    group: str | None = None,
) -> list[tuple[Tag, int, int]]:
    """Every tag with session-count aggregates, ordered for filter-panel rendering.

    Returns ``(tag, open_session_count, session_count)`` tuples where
    ``open_session_count`` is the count of attached sessions with
    ``sessions.closed_at IS NULL`` and ``session_count`` is all
    attached sessions regardless of close state. One round-trip via a
    single LEFT JOIN + GROUP BY over ``session_tags`` and ``sessions``;
    no per-tag fetch.

    ``open_session_count == 0`` for tags with no sessions; ``session_count
    == 0`` likewise. Empty tags return ``(tag, 0, 0)``.

    ``class_`` / ``group`` semantics match :func:`list_all`.

    Used by :func:`bearings.web.routes.tags.list_tags` to populate the
    ``open_session_count`` + ``session_count`` fields on the
    :class:`bearings.web.models.tags.TagOut` wire shape for the sidebar
    tag-filter panel.
    """
    clauses: list[str] = []
    params: list[object] = []
    if class_ is not None:
        if class_ not in KNOWN_TAG_CLASSES:
            raise ValueError(
                f"list_all_with_counts: class_ {class_!r} not in {sorted(KNOWN_TAG_CLASSES)}"
            )
        clauses.append("tags.class = ?")
        params.append(class_)
    if group:
        clauses.append("tags.name LIKE ?")
        params.append(f"{group}{TAG_GROUP_SEPARATOR}%")
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    # COUNT(st.session_id) counts non-NULL values — naturally 0 for
    # tags with no session attachments (LEFT JOIN yields NULL for the
    # tag-side row). SUM returns 0 (not NULL) for no-session tags
    # because the LEFT JOIN always produces at least one row per tag
    # and the CASE expression evaluates to 0 for that NULL-padded row.
    query = (
        "SELECT tags.id, tags.name, tags.color, tags.default_model, tags.working_dir, "
        "tags.pinned, tags.class, tags.sort_order, tags.created_at, tags.updated_at, "
        "COUNT(st.session_id) AS session_count, "
        "SUM(CASE WHEN s.closed_at IS NULL AND st.session_id IS NOT NULL THEN 1 ELSE 0 END) "
        "AS open_session_count "
        "FROM tags "
        "LEFT JOIN session_tags st ON st.tag_id = tags.id "
        "LEFT JOIN sessions s ON s.id = st.session_id" + where_sql + " GROUP BY tags.id"
        " ORDER BY tags.class ASC, tags.sort_order ASC, tags.name ASC"
    )
    cursor = await connection.execute(query, tuple(params))
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    result: list[tuple[Tag, int, int]] = []
    for row in rows:
        tag = Tag(
            id=int(str(row[0])),
            name=str(row[1]),
            color=None if row[2] is None else str(row[2]),
            default_model=None if row[3] is None else str(row[3]),
            working_dir=None if row[4] is None else str(row[4]),
            pinned=bool(row[5]),
            class_=str(row[6]),
            sort_order=int(str(row[7])),
            created_at=str(row[8]),
            updated_at=str(row[9]),
        )
        session_count = int(str(row[10])) if row[10] is not None else 0
        open_session_count = int(str(row[11])) if row[11] is not None else 0
        result.append((tag, open_session_count, session_count))
    return result


async def list_for_session(
    connection: aiosqlite.Connection,
    session_id: str,
) -> list[Tag]:
    """Every tag attached to ``session_id``, alphabetically by ``name``.

    Used by the API layer for the per-session tag-chip surface (per
    ``docs/behavior/chat.md`` §"the conversation pane renders … attached
    tag chips") and by :mod:`bearings.agent.tags` to apply tag defaults
    to a freshly-built :class:`bearings.agent.session.SessionConfig`.
    """
    cursor = await connection.execute(
        _SELECT_TAG_COLUMNS
        + " INNER JOIN session_tags ON session_tags.tag_id = tags.id "
        + "WHERE session_tags.session_id = ? ORDER BY tags.name ASC",
        (session_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_tag(row) for row in rows]


async def list_for_session_ordered(
    connection: aiosqlite.Connection,
    session_id: str,
) -> list[Tag]:
    """Every tag attached to ``session_id``, ordered for inheritance precedence.

    Used by :mod:`bearings.agent.tags` when resolving CLAUDE.md blocks,
    ``default_model``, and ``working_dir``. Higher-precedence tags come
    first; the agent layer iterates and the first non-null inheritance
    field wins.

    Precedence is derived from the tag itself, not from the attachment
    row — class first, then per-class ``sort_order``, then ``name`` for
    a stable tiebreak:

    * ``project``  — highest precedence (drives session inheritance per
      ``docs/behavior/chat.md`` §"When the user creates a chat").
    * ``general``  — middle precedence (free-form labels and legacy
      slash-namespaced tags).
    * ``severity`` — last (carries no inheritance fields per
      :class:`Tag.__post_init__`, so it is effectively a no-op for
      inheritance consumers; ordered last for determinism only).

    The pre-class implementation used a per-attachment
    ``session_tags.priority`` column populated by user pick-order at
    session-create time. That column was retired with the tag-class
    refactor — ordering now lives on the ``tags`` row, so the same
    project tag carries the same precedence on every session it is
    attached to.
    """
    cursor = await connection.execute(
        _SELECT_TAG_COLUMNS
        + " INNER JOIN session_tags ON session_tags.tag_id = tags.id "
        + "WHERE session_tags.session_id = ? "
        + "ORDER BY "
        + "  CASE tags.class "
        + "    WHEN 'project' THEN 0 "
        + "    WHEN 'general' THEN 1 "
        + "    ELSE 2 "
        + "  END ASC, "
        + "  tags.sort_order ASC, "
        + "  tags.name ASC",
        (session_id,),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_tag(row) for row in rows]


async def list_groups(connection: aiosqlite.Connection) -> list[str]:
    """Every distinct slash-prefix group across the tag set, sorted.

    Tags without a separator (default group) are excluded — the
    sidebar-filter UI surfaces them in an "(ungrouped)" pseudo-bucket
    rendered separately. The query is a single SELECT DISTINCT against
    the substring before the separator; the helper materialises eagerly
    because the count is small (typically ≤20 groups).
    """
    cursor = await connection.execute(
        "SELECT DISTINCT substr(name, 1, instr(name, ?) - 1) AS grp "
        "FROM tags WHERE instr(name, ?) > 1 ORDER BY grp ASC",
        (TAG_GROUP_SEPARATOR, TAG_GROUP_SEPARATOR),
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [str(row[0]) for row in rows]


async def update(
    connection: aiosqlite.Connection,
    tag_id: int,
    *,
    name: str,
    color: str | None,
    default_model: str | None,
    working_dir: str | None,
    class_: str | None = None,
    sort_order: int | None = None,
) -> Tag | None:
    """Replace a tag's mutable fields; returns the new value (or ``None``).

    ``None`` is returned when no row matches ``tag_id`` (404-friendly
    contract). ``created_at`` is preserved; ``updated_at`` is bumped to
    the current UTC instant. Tag-rename cascade: per the schema's
    ``ON DELETE CASCADE`` on ``session_tags`` the join row keys on
    ``tag_id`` (not name), so renaming a tag transparently updates
    every session's display label without touching the join table —
    decided-and-documented (the behavior docs are silent on
    rename-cascade; the schema's id-based join means a rename just
    works).

    ``class_`` and ``sort_order`` are optional for back-compat with
    callers that pre-date the class column; passing ``None`` keeps the
    existing value. Pre-INSERT validation runs in
    :class:`Tag.__post_init__` against a phantom row so a severity tag
    can never land with a non-null ``default_model`` / ``working_dir``.
    """
    existing = await get(connection, tag_id)
    if existing is None:
        return None
    new_class = existing.class_ if class_ is None else class_
    new_sort_order = existing.sort_order if sort_order is None else sort_order
    timestamp = now_iso()
    # Phantom validate before touching the DB.
    Tag(
        id=tag_id,
        name=name,
        color=color,
        default_model=default_model,
        working_dir=working_dir,
        pinned=existing.pinned,
        class_=new_class,
        sort_order=new_sort_order,
        created_at=existing.created_at,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "UPDATE tags SET name = ?, color = ?, default_model = ?, working_dir = ?, "
        "class = ?, sort_order = ?, updated_at = ? WHERE id = ?",
        (
            name,
            color,
            default_model,
            working_dir,
            new_class,
            new_sort_order,
            timestamp,
            tag_id,
        ),
    )
    await cursor.close()
    await connection.commit()
    return Tag(
        id=tag_id,
        name=name,
        color=color,
        default_model=default_model,
        working_dir=working_dir,
        pinned=existing.pinned,
        class_=new_class,
        sort_order=new_sort_order,
        created_at=existing.created_at,
        updated_at=timestamp,
    )


async def delete(connection: aiosqlite.Connection, tag_id: int) -> bool:
    """Delete one tag by id; returns ``True`` if a row was removed.

    Per ``schema.sql``'s ``ON DELETE CASCADE`` on ``session_tags`` and
    ``tag_memories``, deleting a tag sweeps its session-attachments
    and memories. Per the same on ``tag_routing_rules`` (item 1.8
    territory), tag-routing rules go too.
    """
    cursor = await connection.execute(
        "DELETE FROM tags WHERE id = ?",
        (tag_id,),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


async def attach(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    tag_id: int,
) -> bool:
    """Attach ``tag_id`` to ``session_id``; returns ``True`` if newly attached.

    Idempotent — a duplicate (session_id, tag_id) is silently no-op'd
    via ``INSERT OR IGNORE``; the boolean reflects whether a row was
    actually inserted (so the API layer can return 201 vs 200). FK
    failure on either side raises :class:`aiosqlite.IntegrityError`
    unchanged so the API layer can translate to a 404.
    """
    timestamp = now_iso()
    cursor = await connection.execute(
        "INSERT OR IGNORE INTO session_tags (session_id, tag_id, created_at) VALUES (?, ?, ?)",
        (session_id, tag_id, timestamp),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


async def detach(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    tag_id: int,
) -> bool:
    """Detach ``tag_id`` from ``session_id``; returns ``True`` if a row was removed."""
    cursor = await connection.execute(
        "DELETE FROM session_tags WHERE session_id = ? AND tag_id = ?",
        (session_id, tag_id),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


async def set_for_session(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    tag_ids: tuple[int, ...],
) -> None:
    """Replace ``session_id``'s tag set with exactly ``tag_ids``.

    Atomic at the SQLite-transaction level: the DELETE + the INSERTs
    share one ``BEGIN ... COMMIT`` so a concurrent reader either sees
    the prior set or the new set, never a partial mid-replace state.
    Empty ``tag_ids`` clears the session's tag set.

    Order of ``tag_ids`` does **not** affect inheritance precedence.
    Precedence comes from the tag's own ``class`` + ``sort_order``
    columns — see :func:`list_for_session_ordered`.
    """
    timestamp = now_iso()
    await connection.execute("DELETE FROM session_tags WHERE session_id = ?", (session_id,))
    for tag_id in tag_ids:
        await connection.execute(
            "INSERT INTO session_tags (session_id, tag_id, created_at) VALUES (?, ?, ?)",
            (session_id, tag_id, timestamp),
        )
    await connection.commit()


async def update_pinned(
    connection: aiosqlite.Connection,
    tag_id: int,
    *,
    pinned: bool,
) -> Tag | None:
    """Pin or unpin a tag; returns the updated row (or ``None`` if absent).

    Mirrors the per-session :func:`bearings.db.sessions.update_pinned`
    contract: only the ``pinned`` column is touched; other fields and
    ``updated_at`` are unchanged (pinning is not a content mutation).
    Returns ``None`` when no row matches ``tag_id`` (404-friendly).
    """
    existing = await get(connection, tag_id)
    if existing is None:
        return None
    cursor = await connection.execute(
        "UPDATE tags SET pinned = ? WHERE id = ?",
        (1 if pinned else 0, tag_id),
    )
    await cursor.close()
    await connection.commit()
    return Tag(
        id=existing.id,
        name=existing.name,
        color=existing.color,
        default_model=existing.default_model,
        working_dir=existing.working_dir,
        pinned=pinned,
        class_=existing.class_,
        sort_order=existing.sort_order,
        created_at=existing.created_at,
        updated_at=existing.updated_at,
    )


async def update_sort_orders(
    connection: aiosqlite.Connection,
    *,
    class_: str,
    ordered_ids: tuple[int, ...],
) -> None:
    """Re-sequence ``sort_order`` within ``class_`` to match ``ordered_ids``.

    Atomic at the SQLite-transaction level: every UPDATE shares one
    ``BEGIN ... COMMIT`` so a concurrent reader either sees the prior
    sequencing or the new sequencing, never a partial mid-replace
    state. Each id at index ``i`` in ``ordered_ids`` is assigned
    ``sort_order = i``; ``updated_at`` is **not** bumped (sort_order
    is a UI-state column, not a content mutation, so it shouldn't
    invalidate caches keyed on ``updated_at``).

    Validates that ``class_`` is in :data:`KNOWN_TAG_CLASSES` and that
    every id in ``ordered_ids`` belongs to a tag of that class — a
    cross-class id is a 422-class API error and the helper raises
    :class:`ValueError` so the route layer can translate it. The check
    is done in a single ``SELECT id, class FROM tags WHERE id IN
    (...)`` rather than per-id round-trip.

    Empty ``ordered_ids`` is a no-op (callers can use the helper as a
    "validate and apply" path even when the user dragged nothing).
    """
    if class_ not in KNOWN_TAG_CLASSES:
        raise ValueError(
            f"update_sort_orders: class_ {class_!r} not in {sorted(KNOWN_TAG_CLASSES)}"
        )
    if not ordered_ids:
        return
    placeholders = ",".join("?" * len(ordered_ids))
    cursor = await connection.execute(
        f"SELECT id, class FROM tags WHERE id IN ({placeholders})",
        ordered_ids,
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    found_classes = {int(str(row[0])): str(row[1]) for row in rows}
    missing = [tag_id for tag_id in ordered_ids if tag_id not in found_classes]
    if missing:
        raise ValueError(f"update_sort_orders: tag ids {missing} not found")
    cross_class = [tag_id for tag_id in ordered_ids if found_classes[tag_id] != class_]
    if cross_class:
        raise ValueError(f"update_sort_orders: tag ids {cross_class} are not in class {class_!r}")
    for index, tag_id in enumerate(ordered_ids):
        await connection.execute(
            "UPDATE tags SET sort_order = ? WHERE id = ?",
            (index, tag_id),
        )
    await connection.commit()


# Single source of truth for the column list — keeps the SELECT in
# the helpers above synchronised. Adding a column means editing this
# string and :func:`_row_to_tag` together.
_SELECT_TAG_COLUMNS = (
    "SELECT tags.id, tags.name, tags.color, tags.default_model, tags.working_dir, "
    "tags.pinned, tags.class, tags.sort_order, tags.created_at, tags.updated_at "
    "FROM tags"
)


def _row_to_tag(row: aiosqlite.Row | tuple[object, ...]) -> Tag:
    """Translate a raw SELECT tuple to a validated :class:`Tag`."""
    return Tag(
        id=int(str(row[0])),
        name=str(row[1]),
        color=None if row[2] is None else str(row[2]),
        default_model=None if row[3] is None else str(row[3]),
        working_dir=None if row[4] is None else str(row[4]),
        pinned=bool(row[5]),
        class_=str(row[6]),
        sort_order=int(str(row[7])),
        created_at=str(row[8]),
        updated_at=str(row[9]),
    )


__all__ = [
    "Tag",
    "attach",
    "create",
    "delete",
    "detach",
    "get",
    "get_by_name",
    "list_all",
    "list_all_with_counts",
    "list_for_session",
    "list_for_session_ordered",
    "list_groups",
    "set_for_session",
    "update",
    "update_pinned",
    "update_sort_orders",
]
