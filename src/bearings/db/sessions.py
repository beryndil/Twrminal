"""``sessions`` table queries — chat-kind + checklist-kind row CRUD.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches the ``sessions`` table. Per
``docs/behavior/chat.md`` the user observes a chat-kind session
(composer + transcript); per ``docs/behavior/checklists.md`` a
checklist-kind session (structured-list pane). The schema's
:data:`bearings.config.constants.KNOWN_SESSION_KINDS` discriminator is
the partition.

Public surface:

* :class:`Session` — frozen dataclass row mirror with
  ``__post_init__`` validation (kind alphabet, title bounds,
  description bounds).
* CRUD: :func:`create`, :func:`get`, :func:`exists`, :func:`update`,
  :func:`delete`, :func:`list_all`.
* Lifecycle: :func:`close`, :func:`reopen`, :func:`mark_viewed`.

Per ``docs/behavior/paired-chats.md`` the chat-side back-pointer to a
checklist item is :attr:`Session.checklist_item_id` — read-only on this
module's surface; the live link is set/cleared via
:func:`bearings.db.checklists.set_paired_chat` /
:func:`bearings.db.checklists.clear_paired_chat`. The two columns
(``sessions.checklist_item_id`` and ``checklist_items.chat_session_id``)
are the inverse-pointer pair the schema header documents; this module
intentionally does not expose a setter for the chat-side column to
prevent drift between the two sides — :func:`create` accepts an
optional ``checklist_item_id`` at insert time, and :func:`delete`'s
ON DELETE SET NULL on the FK clears it on item deletion.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

from bearings.config.constants import (
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    KNOWN_EXECUTOR_MODELS,
    KNOWN_SDK_PERMISSION_MODES,
    KNOWN_SESSION_KINDS,
    SESSION_CLOSING_SUMMARY_MAX_LENGTH,
    SESSION_CLOSING_SUMMARY_MIN_LENGTH,
    SESSION_DESCRIPTION_MAX_LENGTH,
    SESSION_ID_PREFIX,
    SESSION_TITLE_MAX_LENGTH,
)
from bearings.db._id import new_id, now_iso


@dataclass(frozen=True)
class Session:
    """Row mirror for the ``sessions`` table.

    Schema fields (see ``schema.sql``): ``id``, ``kind``, ``title``,
    ``description``, ``session_instructions``, ``working_dir``,
    ``model``, ``permission_mode``, ``max_budget_usd``,
    ``total_cost_usd``, ``message_count``, plus the
    ``last_context_*`` triple, ``pinned``, ``error_pending``,
    ``checklist_item_id`` (chat-side paired pointer),
    ``created_at`` / ``updated_at`` / ``last_viewed_at`` /
    ``last_completed_at`` / ``closed_at``.

    Validation (``__post_init__``) catches:

    * Empty ``id`` / ``title`` / ``working_dir`` / ``model``.
    * ``kind`` outside :data:`KNOWN_SESSION_KINDS`.
    * ``title`` over the cap.
    * ``description`` / ``session_instructions`` over the cap.
    * ``permission_mode`` outside :data:`KNOWN_SDK_PERMISSION_MODES`
      when set.
    * ``model`` outside :data:`KNOWN_EXECUTOR_MODELS` when not a full
      SDK ID.
    * Negative ``max_budget_usd`` / ``total_cost_usd`` /
      ``message_count``.
    """

    id: str
    kind: str
    title: str
    description: str | None
    session_instructions: str | None
    working_dir: str
    model: str
    permission_mode: str | None
    max_budget_usd: float | None
    total_cost_usd: float
    message_count: int
    last_context_pct: float | None
    last_context_tokens: int | None
    last_context_max: int | None
    pinned: bool
    error_pending: bool
    checklist_item_id: int | None
    created_at: str
    updated_at: str
    last_viewed_at: str | None
    last_completed_at: str | None
    closed_at: str | None
    closing_summary: str | None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Session.id must be non-empty")
        if not self.title:
            raise ValueError("Session.title must be non-empty")
        if len(self.title) > SESSION_TITLE_MAX_LENGTH:
            raise ValueError(
                f"Session.title must be ≤ {SESSION_TITLE_MAX_LENGTH} chars (got {len(self.title)})"
            )
        if not self.working_dir:
            raise ValueError("Session.working_dir must be non-empty")
        if not self.model:
            raise ValueError("Session.model must be non-empty")
        if self.kind not in KNOWN_SESSION_KINDS:
            raise ValueError(f"Session.kind {self.kind!r} not in {sorted(KNOWN_SESSION_KINDS)}")
        if self.description is not None and len(self.description) > SESSION_DESCRIPTION_MAX_LENGTH:
            raise ValueError(
                f"Session.description must be ≤ {SESSION_DESCRIPTION_MAX_LENGTH} chars "
                f"(got {len(self.description)})"
            )
        if (
            self.session_instructions is not None
            and len(self.session_instructions) > SESSION_DESCRIPTION_MAX_LENGTH
        ):
            raise ValueError(
                f"Session.session_instructions must be ≤ "
                f"{SESSION_DESCRIPTION_MAX_LENGTH} chars (got {len(self.session_instructions)})"
            )
        if (
            self.permission_mode is not None
            and self.permission_mode not in KNOWN_SDK_PERMISSION_MODES
        ):
            raise ValueError(
                f"Session.permission_mode {self.permission_mode!r} not in "
                f"{sorted(KNOWN_SDK_PERMISSION_MODES)}"
            )
        if not _is_known_model(self.model):
            raise ValueError(
                f"Session.model {self.model!r} is neither a known short name "
                f"{sorted(KNOWN_EXECUTOR_MODELS)} nor a full SDK ID prefixed with "
                f"{EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
            )
        if self.max_budget_usd is not None and self.max_budget_usd < 0:
            raise ValueError(
                f"Session.max_budget_usd must be ≥ 0 if set (got {self.max_budget_usd})"
            )
        if self.total_cost_usd < 0:
            raise ValueError(f"Session.total_cost_usd must be ≥ 0 (got {self.total_cost_usd})")
        if self.message_count < 0:
            raise ValueError(f"Session.message_count must be ≥ 0 (got {self.message_count})")
        if self.closing_summary is not None:
            length = len(self.closing_summary)
            if length < SESSION_CLOSING_SUMMARY_MIN_LENGTH:
                raise ValueError(
                    f"Session.closing_summary must be ≥ "
                    f"{SESSION_CLOSING_SUMMARY_MIN_LENGTH} chars when set (got {length})"
                )
            if length > SESSION_CLOSING_SUMMARY_MAX_LENGTH:
                raise ValueError(
                    f"Session.closing_summary must be ≤ "
                    f"{SESSION_CLOSING_SUMMARY_MAX_LENGTH} chars (got {length})"
                )


def _is_known_model(name: str) -> bool:
    """Match short-name or full-SDK-id model names (mirrors agent/routing.py)."""
    return name in KNOWN_EXECUTOR_MODELS or name.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX)


async def create(
    connection: aiosqlite.Connection,
    *,
    kind: str,
    title: str,
    working_dir: str,
    model: str,
    description: str | None = None,
    session_instructions: str | None = None,
    permission_mode: str | None = None,
    max_budget_usd: float | None = None,
    checklist_item_id: int | None = None,
) -> Session:
    """Insert a fresh session row.

    The id is generated as ``ses_<32-hex>`` per the ``new_id`` prefix
    convention. Validation runs in :class:`Session.__post_init__` against
    a pre-INSERT phantom instance so a bad shape never touches the DB.
    """
    timestamp = now_iso()
    session_id = new_id(SESSION_ID_PREFIX)
    # Phantom-construct for validation (validator catches every mistake
    # the schema CHECK constraints don't surface as friendly errors).
    Session(
        id=session_id,
        kind=kind,
        title=title,
        description=description,
        session_instructions=session_instructions,
        working_dir=working_dir,
        model=model,
        permission_mode=permission_mode,
        max_budget_usd=max_budget_usd,
        total_cost_usd=0.0,
        message_count=0,
        last_context_pct=None,
        last_context_tokens=None,
        last_context_max=None,
        pinned=False,
        error_pending=False,
        checklist_item_id=checklist_item_id,
        created_at=timestamp,
        updated_at=timestamp,
        last_viewed_at=None,
        last_completed_at=None,
        closed_at=None,
        closing_summary=None,
    )
    await connection.execute(
        "INSERT INTO sessions "
        "(id, kind, title, description, session_instructions, working_dir, model, "
        "permission_mode, max_budget_usd, checklist_item_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            kind,
            title,
            description,
            session_instructions,
            working_dir,
            model,
            permission_mode,
            max_budget_usd,
            checklist_item_id,
            timestamp,
            timestamp,
        ),
    )
    await connection.commit()
    fetched = await get(connection, session_id)
    if fetched is None:  # pragma: no cover — INSERT just succeeded
        raise RuntimeError(f"sessions.create: row {session_id!r} vanished after INSERT")
    return fetched


async def get(
    connection: aiosqlite.Connection,
    session_id: str,
) -> Session | None:
    """Fetch one session by id; ``None`` if absent."""
    cursor = await connection.execute(
        _SELECT_SESSION_COLUMNS + " WHERE id = ?",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_session(row)


async def exists(
    connection: aiosqlite.Connection,
    session_id: str,
) -> bool:
    """``True`` if the row exists; ``False`` otherwise."""
    cursor = await connection.execute(
        "SELECT 1 FROM sessions WHERE id = ? LIMIT 1",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return row is not None


async def list_all(
    connection: aiosqlite.Connection,
    *,
    kind: str | None = None,
    include_closed: bool = True,
    tag_ids: tuple[int, ...] | None = None,
) -> list[Session]:
    """Every session row matching the filters; newest-first.

    ``tag_ids`` is the sidebar tag-filter surface from
    ``docs/behavior/chat.md`` §"When the user creates a chat" + the
    item 2.2 done-when criterion ("OR semantics across tags"). Passing
    ``None`` (default) applies no tag filter; passing a non-empty tuple
    returns sessions attached to **at least one** of the listed tags
    (OR semantics, implemented via ``WHERE session_tags.tag_id IN
    (...)``). ``DISTINCT`` collapses the multi-row product the join
    produces when a single session matches more than one of the
    requested tags. Passing the empty tuple raises ``ValueError`` —
    the API layer maps "no filter" to ``None``, so an empty tuple is a
    caller bug rather than an "exclude everything" intent.
    """
    if kind is not None and kind not in KNOWN_SESSION_KINDS:
        raise ValueError(f"list_all: kind {kind!r} not in {sorted(KNOWN_SESSION_KINDS)}")
    if tag_ids is not None and len(tag_ids) == 0:
        raise ValueError(
            "list_all: tag_ids must be non-empty when provided (use None for no filter)"
        )
    clauses: list[str] = []
    args: list[object] = []
    if kind is not None:
        clauses.append("sessions.kind = ?")
        args.append(kind)
    if not include_closed:
        clauses.append("sessions.closed_at IS NULL")
    if tag_ids is not None:
        placeholders = ",".join(["?"] * len(tag_ids))
        clauses.append(f"session_tags.tag_id IN ({placeholders})")
        args.extend(tag_ids)
    join = (
        " INNER JOIN session_tags ON session_tags.session_id = sessions.id"
        if tag_ids is not None
        else ""
    )
    where = "" if not clauses else " WHERE " + " AND ".join(clauses)
    # ``SELECT DISTINCT`` is only required on the join path; the
    # plain-select path returns each row once already, so we keep the
    # cheaper non-distinct query when no tag filter is in play.
    select = _SELECT_SESSION_COLUMNS_DISTINCT if tag_ids is not None else _SELECT_SESSION_COLUMNS
    cursor = await connection.execute(
        select + join + where + " ORDER BY sessions.updated_at DESC, sessions.id ASC",
        args,
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    return [_row_to_session(row) for row in rows]


async def update_title(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    title: str,
) -> Session | None:
    """Replace ``title``; returns the new row or ``None`` if absent."""
    if not title:
        raise ValueError("update_title: title must be non-empty")
    if len(title) > SESSION_TITLE_MAX_LENGTH:
        raise ValueError(
            f"update_title: title must be ≤ {SESSION_TITLE_MAX_LENGTH} chars (got {len(title)})"
        )
    existing = await get(connection, session_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, timestamp, session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def update_model(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    model: str,
) -> Session | None:
    """Replace ``model``; returns the new row or ``None`` if absent.

    Backs ``PATCH /api/sessions/{id}/model`` (arch §1.1.5 — landed in
    the v1.1 closing-sweep). Validation mirrors :class:`Session`'s
    own model invariant via :func:`_is_known_model`; an unknown
    model name raises ``ValueError`` so the route layer can surface
    a 422.

    **Live-runner semantics** — this helper updates the DB row only.
    Spec §7 calls for an in-flight ``runner.set_model()`` forward
    so the swap takes effect mid-turn; v1.1 ships the DB-only swap
    (next session boot picks up the new model) and defers the live
    forward to a follow-up. See TODO.md "PATCH model: live runner
    forward (deferred)".
    """
    if not _is_known_model(model):
        raise ValueError(f"update_model: model {model!r} not recognised")
    existing = await get(connection, session_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET model = ?, updated_at = ? WHERE id = ?",
        (model, timestamp, session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def update_permission_mode(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    permission_mode: str | None,
) -> Session | None:
    """Replace ``permission_mode``; returns the new row or ``None`` if absent.

    Backs ``PATCH /api/sessions/{id}/permission_mode`` (item 3.3).
    ``None`` clears the column — the runner falls back to the profile
    default on the next boot. Any non-``None`` value is validated against
    :data:`KNOWN_SDK_PERMISSION_MODES`; an unknown value raises
    ``ValueError`` so the route layer surfaces a 422.
    """
    if permission_mode is not None and permission_mode not in KNOWN_SDK_PERMISSION_MODES:
        raise ValueError(
            f"update_permission_mode: permission_mode {permission_mode!r} not in "
            f"{sorted(KNOWN_SDK_PERMISSION_MODES)}"
        )
    existing = await get(connection, session_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET permission_mode = ?, updated_at = ? WHERE id = ?",
        (permission_mode, timestamp, session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def close(
    connection: aiosqlite.Connection,
    session_id: str,
) -> Session | None:
    """Stamp ``closed_at`` to now (idempotent — re-stamps with new value)."""
    existing = await get(connection, session_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET closed_at = ?, updated_at = ? WHERE id = ?",
        (timestamp, timestamp, session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def close_with_summary(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    summary: str,
) -> Session | None:
    """Stamp ``closed_at`` AND persist the agent-authored ``closing_summary``.

    Backs the ``close_session`` MCP tool: the agent calls the tool when
    it judges the user's task complete and supplies a 1-3 sentence
    summary. Different from :func:`close` in two ways:

    * Writes ``closing_summary`` in the same transaction as
      ``closed_at`` so a crash mid-write can never leave the row in a
      "closed without summary" state.
    * Idempotent no-op when the row is already closed: returns
      ``None`` instead of overwriting an earlier summary. A confused
      agent re-calling ``close_session`` on a row another caller (the
      sidebar reaper, a manual close) already finalized never erases
      the canonical close.

    Returns the updated row on the first successful close; ``None``
    when the row is missing OR already closed.

    The summary is validated client-side (Pydantic ``Field`` bounds on
    the MCP tool's parameter shape) and again here via
    :class:`Session`'s ``__post_init__`` — defence in depth so a direct
    DB-side caller cannot insert an out-of-bounds summary.
    """
    length = len(summary)
    if length < SESSION_CLOSING_SUMMARY_MIN_LENGTH:
        raise ValueError(
            f"close_with_summary: summary must be ≥ "
            f"{SESSION_CLOSING_SUMMARY_MIN_LENGTH} chars (got {length})"
        )
    if length > SESSION_CLOSING_SUMMARY_MAX_LENGTH:
        raise ValueError(
            f"close_with_summary: summary must be ≤ "
            f"{SESSION_CLOSING_SUMMARY_MAX_LENGTH} chars (got {length})"
        )
    existing = await get(connection, session_id)
    if existing is None:
        return None
    if existing.closed_at is not None:
        # Already closed — preserve the prior summary + timestamp.
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET closed_at = ?, closing_summary = ?, updated_at = ? WHERE id = ?",
        (timestamp, summary, timestamp, session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def reopen(
    connection: aiosqlite.Connection,
    session_id: str,
) -> Session | None:
    """Clear ``closed_at`` (the inverse of :func:`close`).

    Per ``docs/behavior/paired-chats.md`` §"Reopen semantics" reopening
    a closed paired chat re-attaches its sidebar row to the open group;
    the prompt-endpoint accepts POSTs again.
    """
    existing = await get(connection, session_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET closed_at = NULL, updated_at = ? WHERE id = ?",
        (timestamp, session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def delete(
    connection: aiosqlite.Connection,
    session_id: str,
) -> bool:
    """Delete one session row; cascades to messages + checkpoints + tags.

    ``checklist_items.chat_session_id`` carries ON DELETE SET NULL so
    deleting a paired chat clears the item-side pointer without orphaning
    the item — per ``docs/behavior/paired-chats.md`` §"Behavior under
    one-side-closed" "Chat deleted: the pair pointer is cleared from the
    item side; the leaf reverts to unpaired".
    """
    cursor = await connection.execute(
        "DELETE FROM sessions WHERE id = ?",
        (session_id,),
    )
    rowcount = cursor.rowcount
    await cursor.close()
    await connection.commit()
    return rowcount > 0


async def is_closed(
    connection: aiosqlite.Connection,
    session_id: str,
) -> bool | None:
    """``True`` / ``False`` per ``closed_at`` state; ``None`` if absent.

    The tri-state return is load-bearing for the prompt-endpoint, which
    must distinguish 404 (session does not exist) from 409 (session
    closed) per behavior doc §"Failure responses".
    """
    cursor = await connection.execute(
        "SELECT closed_at FROM sessions WHERE id = ?",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    return row[0] is not None


async def get_kind(
    connection: aiosqlite.Connection,
    session_id: str,
) -> str | None:
    """Return ``sessions.kind`` for ``session_id``; ``None`` if absent."""
    cursor = await connection.execute(
        "SELECT kind FROM sessions WHERE id = ?",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else str(row[0])


_SELECT_SESSION_COLUMNS = (
    "SELECT id, kind, title, description, session_instructions, working_dir, model, "
    "permission_mode, max_budget_usd, total_cost_usd, message_count, "
    "last_context_pct, last_context_tokens, last_context_max, pinned, error_pending, "
    "checklist_item_id, created_at, updated_at, last_viewed_at, last_completed_at, "
    "closed_at, closing_summary FROM sessions"
)


# Variant used by the join path in :func:`list_all` when ``tag_ids`` is
# set: the ``INNER JOIN session_tags`` produces one row per matching
# (session, tag) pair, so a session attached to multiple selected tags
# would appear multiple times without ``DISTINCT``. The ``sessions.``
# qualifier is required because the join introduces another table; the
# unqualified variant above is left alone so the no-filter path keeps
# the cheaper plan.
_SELECT_SESSION_COLUMNS_DISTINCT = (
    "SELECT DISTINCT sessions.id, sessions.kind, sessions.title, sessions.description, "
    "sessions.session_instructions, sessions.working_dir, sessions.model, "
    "sessions.permission_mode, sessions.max_budget_usd, sessions.total_cost_usd, "
    "sessions.message_count, sessions.last_context_pct, sessions.last_context_tokens, "
    "sessions.last_context_max, sessions.pinned, sessions.error_pending, "
    "sessions.checklist_item_id, sessions.created_at, sessions.updated_at, "
    "sessions.last_viewed_at, sessions.last_completed_at, sessions.closed_at, "
    "sessions.closing_summary FROM sessions"
)


def _row_to_session(row: aiosqlite.Row | tuple[object, ...]) -> Session:
    """Translate a raw SELECT tuple into a validated :class:`Session`."""
    return Session(
        id=str(row[0]),
        kind=str(row[1]),
        title=str(row[2]),
        description=None if row[3] is None else str(row[3]),
        session_instructions=None if row[4] is None else str(row[4]),
        working_dir=str(row[5]),
        model=str(row[6]),
        permission_mode=None if row[7] is None else str(row[7]),
        max_budget_usd=None if row[8] is None else float(str(row[8])),
        total_cost_usd=float(str(row[9])),
        message_count=int(str(row[10])),
        last_context_pct=None if row[11] is None else float(str(row[11])),
        last_context_tokens=None if row[12] is None else int(str(row[12])),
        last_context_max=None if row[13] is None else int(str(row[13])),
        pinned=bool(int(str(row[14]))),
        error_pending=bool(int(str(row[15]))),
        checklist_item_id=None if row[16] is None else int(str(row[16])),
        created_at=str(row[17]),
        updated_at=str(row[18]),
        last_viewed_at=None if row[19] is None else str(row[19]),
        last_completed_at=None if row[20] is None else str(row[20]),
        closed_at=None if row[21] is None else str(row[21]),
        closing_summary=None if row[22] is None else str(row[22]),
    )


__all__ = [
    "Session",
    "close",
    "close_with_summary",
    "create",
    "delete",
    "exists",
    "get",
    "get_kind",
    "is_closed",
    "list_all",
    "reopen",
    "update_title",
]
