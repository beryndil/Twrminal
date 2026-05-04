"""``tags`` + ``session_tags`` table queries — sidebar categorisation surface.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``tags`` and the per-session join table
``session_tags``. Per ``docs/behavior/chat.md`` §"When the user creates
a chat" every chat must carry ≥1 general tag; per
``docs/behavior/checklists.md`` "the chat inherits the checklist's
working directory, model, and tags" — the inheritance fields landed on
``tags`` are :attr:`Tag.default_model` and :attr:`Tag.working_dir`. Per
``docs/behavior/context-menus.md`` §"Tag (sidebar tag chip in the
filter panel)" the user pins / unpins / edits / deletes tags from a
right-click menu; the API surface for those actions lives in
:mod:`bearings.web.routes.tags` (item 1.4) on top of this layer.

Tag groups
----------

The 0.4 schema landed without a ``tag_groups`` table or a ``group``
column on ``tags``. Item 1.4 adopts slash-namespacing on the tag name
(``<group>/<name>``) as the group carrier — already the convention in
test fixtures (``bearings/architect``, ``bearings/exec``) and in
``docs/behavior/checklists.md`` cross-references. The separator is the
single character :data:`bearings.config.constants.TAG_GROUP_SEPARATOR`;
a bare name (no separator) is treated as the unnamed/default group.
:func:`list_groups` enumerates the distinct prefixes; :func:`list_all`
accepts an optional ``group`` filter that matches via ``LIKE
"<group>/%"``. This is decided-and-documented; if a future arch
amendment promotes ``group`` to a first-class column the dataclass
gains a field and the helpers below stay backward-compatible (the
slash-namespace convention is additive).

Public surface:

* :class:`Tag` — frozen dataclass row mirror with
  ``__post_init__`` validation.
* :func:`create`, :func:`get`, :func:`get_by_name`, :func:`list_all`,
  :func:`list_for_session`, :func:`list_groups`, :func:`update`,
  :func:`delete` — tag CRUD; same return-shape conventions as
  :mod:`bearings.db.templates`.
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
    TAG_COLOR_MAX_LENGTH,
    TAG_GROUP_SEPARATOR,
    TAG_NAME_MAX_LENGTH,
)
from bearings.db._id import now_iso


@dataclass(frozen=True)
class Tag:
    """Row mirror for the ``tags`` table.

    Field semantics follow ``schema.sql``:

    * ``id`` — INTEGER PRIMARY KEY AUTOINCREMENT.
    * ``name`` — non-empty, ≤
      :data:`bearings.config.constants.TAG_NAME_MAX_LENGTH` chars,
      UNIQUE across the table. The slash-namespace convention is
      enforced softly — a name with no
      :data:`bearings.config.constants.TAG_GROUP_SEPARATOR` is the
      unnamed/default group.
    * ``color`` — optional cosmetic CSS string;
      ≤ :data:`bearings.config.constants.TAG_COLOR_MAX_LENGTH` chars.
    * ``default_model`` — optional executor short name from
      :data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS` or full
      SDK ID prefixed with
      :data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX`
      (mirrors :class:`bearings.db.templates.Template`'s validator and
      :class:`bearings.agent.routing.RoutingDecision`'s alphabet).
    * ``working_dir`` — optional absolute path the chat inherits when
      this tag is applied (per ``docs/behavior/checklists.md`` "the
      chat inherits the checklist's working directory…").
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

    @property
    def group(self) -> str | None:
        """The slash-prefix group, or ``None`` for the default group.

        ``"bearings/architect"`` → ``"bearings"``;
        ``"general"`` → ``None``. Consumers (filter panel, group
        listing) read this property rather than re-parsing the name at
        each call site.
        """
        sep_index = self.name.find(TAG_GROUP_SEPARATOR)
        if sep_index <= 0:
            return None
        return self.name[:sep_index]


def _is_known_model(name: str) -> bool:
    """Mirror :func:`bearings.db.templates._is_known_model`.

    Duplicated rather than imported because ``db.tags`` and
    ``db.templates`` are sibling concern modules; cross-import would
    couple two independent tables on the validator alphabet, and arch
    §3.1 forbids sibling cycles within a layer. Any drift between the
    two helpers would be a behavioural bug catchable by either
    module's unit-test suite.
    """
    return name in KNOWN_EXECUTOR_MODELS or name.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX)


async def create(
    connection: aiosqlite.Connection,
    *,
    name: str,
    color: str | None = None,
    default_model: str | None = None,
    working_dir: str | None = None,
) -> Tag:
    """Insert a new tag and return the populated dataclass.

    Validation runs in :class:`Tag.__post_init__` against a phantom
    pre-INSERT instance so a bad shape never touches the DB. Name
    uniqueness is enforced by the schema's ``UNIQUE`` constraint;
    :class:`aiosqlite.IntegrityError` surfaces unchanged so the API
    layer can translate to a 409.
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
        created_at=timestamp,
        updated_at=timestamp,
    )
    cursor = await connection.execute(
        "INSERT INTO tags "
        "(name, color, default_model, working_dir, pinned, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, color, default_model, working_dir, 0, timestamp, timestamp),
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
    group: str | None = None,
) -> list[Tag]:
    """Every tag, alphabetically by ``name``; optionally filtered by group prefix.

    Group filtering uses ``LIKE "<group>/%"`` against the tag name
    (slash-namespace convention; see the module docstring). Passing
    ``group=""`` is equivalent to ``group=None`` (no filter).
    """
    if group:
        cursor = await connection.execute(
            _SELECT_TAG_COLUMNS + " WHERE name LIKE ? ORDER BY name ASC",
            (f"{group}{TAG_GROUP_SEPARATOR}%",),
        )
    else:
        cursor = await connection.execute(_SELECT_TAG_COLUMNS + " ORDER BY name ASC")
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_tag(row) for row in rows]


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
    """
    existing = await get(connection, tag_id)
    if existing is None:
        return None
    timestamp = now_iso()
    cursor = await connection.execute(
        "UPDATE tags SET name = ?, color = ?, default_model = ?, working_dir = ?, "
        "updated_at = ? WHERE id = ?",
        (name, color, default_model, working_dir, timestamp, tag_id),
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
        created_at=existing.created_at,
        updated_at=existing.updated_at,
    )


# Single source of truth for the column list — keeps the SELECT in
# the helpers above synchronised. Adding a column means editing this
# string and :func:`_row_to_tag` together.
_SELECT_TAG_COLUMNS = (
    "SELECT tags.id, tags.name, tags.color, tags.default_model, tags.working_dir, "
    "tags.pinned, tags.created_at, tags.updated_at FROM tags"
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
        created_at=str(row[6]),
        updated_at=str(row[7]),
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
    "list_for_session",
    "list_groups",
    "set_for_session",
    "update",
    "update_pinned",
]
