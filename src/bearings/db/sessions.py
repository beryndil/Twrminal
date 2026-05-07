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
    KNOWN_EFFORT_LEVELS,
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
    ``last_completed_at`` / ``closed_at``, and the routing-decision
    projection ``routing_advisor_model`` / ``routing_advisor_max_uses``
    / ``routing_effort_level``.

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
    * ``routing_advisor_model`` outside :data:`KNOWN_EXECUTOR_MODELS`
      when not ``None`` and not a full SDK ID.
    * ``routing_advisor_max_uses`` negative.
    * ``routing_effort_level`` outside :data:`KNOWN_EFFORT_LEVELS`.
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
    # Routing-decision projection — persisted at session-create time so
    # the supervisor respawn (``agent/session_bootstrap.py``) reconstructs
    # the exact :class:`RoutingDecision` without falling back to template
    # defaults. NULL ``routing_advisor_model`` means "no advisor" for rows
    # created after this column landed and "unknown" (legacy fallback) for
    # rows that predate the column.
    routing_advisor_model: str | None
    routing_advisor_max_uses: int
    routing_effort_level: str
    # Spawn-from-reply back-pointers (gap-cycle-03-007). Set only when
    # the session was created via POST /api/sessions/{parent}/
    # spawn_from_reply/{msg_id}. NULL on every other session row.
    pivot_message_id: str | None
    parent_session_id: str | None

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
        if self.routing_advisor_model is not None and not _is_known_model(
            self.routing_advisor_model
        ):
            raise ValueError(
                f"Session.routing_advisor_model {self.routing_advisor_model!r} "
                f"is neither a known short name {sorted(KNOWN_EXECUTOR_MODELS)} "
                f"nor a full SDK ID prefixed with {EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
            )
        if self.routing_advisor_max_uses < 0:
            raise ValueError(
                f"Session.routing_advisor_max_uses must be ≥ 0 "
                f"(got {self.routing_advisor_max_uses})"
            )
        if self.routing_effort_level not in KNOWN_EFFORT_LEVELS:
            raise ValueError(
                f"Session.routing_effort_level {self.routing_effort_level!r} "
                f"not in {sorted(KNOWN_EFFORT_LEVELS)}"
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
    routing_advisor_model: str | None = None,
    routing_advisor_max_uses: int = 5,
    routing_effort_level: str = "auto",
    pivot_message_id: str | None = None,
    parent_session_id: str | None = None,
) -> Session:
    """Insert a fresh session row.

    The id is generated as ``ses_<32-hex>`` per the ``new_id`` prefix
    convention. Validation runs in :class:`Session.__post_init__` against
    a pre-INSERT phantom instance so a bad shape never touches the DB.

    The three ``routing_*`` keyword arguments persist the
    :class:`bearings.agent.routing.RoutingDecision` projection so that
    supervisor respawns (``agent/session_bootstrap.py``) reconstruct the
    exact decision without falling back to template-wide defaults.

    ``pivot_message_id`` / ``parent_session_id`` are set only by the
    spawn-from-reply route (gap-cycle-03-007); all other callers leave
    them ``None``.
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
        routing_advisor_model=routing_advisor_model,
        routing_advisor_max_uses=routing_advisor_max_uses,
        routing_effort_level=routing_effort_level,
        pivot_message_id=pivot_message_id,
        parent_session_id=parent_session_id,
    )
    await connection.execute(
        "INSERT INTO sessions "
        "(id, kind, title, description, session_instructions, working_dir, model, "
        "permission_mode, max_budget_usd, checklist_item_id, "
        "routing_advisor_model, routing_advisor_max_uses, routing_effort_level, "
        "pivot_message_id, parent_session_id, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            routing_advisor_model,
            routing_advisor_max_uses,
            routing_effort_level,
            pivot_message_id,
            parent_session_id,
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


async def import_session(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    kind: str,
    title: str,
    description: str | None,
    session_instructions: str | None,
    working_dir: str,
    model: str,
    permission_mode: str | None,
    max_budget_usd: float | None,
    total_cost_usd: float,
    message_count: int,
    last_context_pct: float | None,
    last_context_tokens: int | None,
    last_context_max: int | None,
    pinned: bool,
    closed_at: str | None,
    closing_summary: str | None,
    created_at: str,
    updated_at: str,
    last_viewed_at: str | None,
    last_completed_at: str | None,
) -> Session:
    """Insert a session row preserving the original id and timestamps.

    Used exclusively by ``POST /api/sessions/import`` to restore a
    session from an export blob.  Unlike :func:`create`, which generates
    a new id and timestamp, this function preserves the original values
    so a round-trip export→import produces an identical session id.

    ``checklist_item_id`` is always ``None`` on import — the FK target
    (a ``checklist_items`` row) does not exist in the destination
    instance.  The routing-decision columns
    (``routing_advisor_model``, ``routing_advisor_max_uses``,
    ``routing_effort_level``) are set to their schema defaults (``NULL``,
    ``5``, ``'auto'``) because ``SessionOut`` does not carry them.

    Raises ``ValueError`` when any field fails :class:`Session.__post_init__`
    validation so the route can surface a 422.  ``error_pending`` is
    unconditionally cleared — an imported session is never in an error
    state from the destination runner's perspective.
    """
    # Phantom-construct for validation before any DB write.
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
        total_cost_usd=total_cost_usd,
        message_count=message_count,
        last_context_pct=last_context_pct,
        last_context_tokens=last_context_tokens,
        last_context_max=last_context_max,
        pinned=pinned,
        error_pending=False,
        checklist_item_id=None,
        created_at=created_at,
        updated_at=updated_at,
        last_viewed_at=last_viewed_at,
        last_completed_at=last_completed_at,
        closed_at=closed_at,
        closing_summary=closing_summary,
        routing_advisor_model=None,
        routing_advisor_max_uses=5,
        routing_effort_level="auto",
        pivot_message_id=None,
        parent_session_id=None,
    )
    await connection.execute(
        "INSERT INTO sessions "
        "(id, kind, title, description, session_instructions, working_dir, model, "
        "permission_mode, max_budget_usd, total_cost_usd, message_count, "
        "last_context_pct, last_context_tokens, last_context_max, "
        "pinned, error_pending, checklist_item_id, "
        "closed_at, closing_summary, created_at, updated_at, "
        "last_viewed_at, last_completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, "
        "?, ?, ?, ?, ?, ?)",
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
            total_cost_usd,
            message_count,
            last_context_pct,
            last_context_tokens,
            last_context_max,
            pinned,
            closed_at,
            closing_summary,
            created_at,
            updated_at,
            last_viewed_at,
            last_completed_at,
        ),
    )
    await connection.commit()
    fetched = await get(connection, session_id)
    if fetched is None:  # pragma: no cover — INSERT just succeeded
        raise RuntimeError(f"sessions.import_session: row {session_id!r} vanished after INSERT")
    return fetched


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
    tag_ids_project: tuple[int, ...] | None = None,
    tag_ids_severity: tuple[int, ...] | None = None,
    tag_ids_other: tuple[int, ...] | None = None,
) -> list[Session]:
    """Every session row matching the filters; newest-first.

    Two filter shapes coexist:

    * ``tag_ids`` — legacy flat OR across every class. Returns sessions
      attached to **at least one** of the listed tags. Retained for
      back-compat with v0.18.x callers.
    * ``tag_ids_project`` / ``tag_ids_severity`` / ``tag_ids_other`` —
      three-section faceted filter from the tag-class feature. Each
      tuple is **OR within its class**; the three tuples compose
      **AND across classes**. An empty / ``None`` tuple means "no
      constraint from this section" (NOT "exclude everything"); the
      filter panel renders an empty section by emitting no constraint
      from that class.

    The two shapes can be combined: each layer is an additional AND
    constraint. Implementation uses correlated ``EXISTS`` subqueries
    rather than a multi-join so a session that matches all three
    classes returns once (no DISTINCT needed in the new path).

    Passing an empty tuple to ``tag_ids`` raises ``ValueError`` — the
    API layer maps "no filter" to ``None``, so an empty tuple is a
    caller bug rather than an "exclude everything" intent. The
    per-class params permit the empty / ``None`` distinction (both
    mean "no constraint from this section").
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
    # Three-section faceted filter: each non-empty per-class tuple
    # contributes one EXISTS subquery; empty / None contributes nothing
    # ("no constraint from this section"). Sections compose with AND.
    for section_ids in (tag_ids_project, tag_ids_severity, tag_ids_other):
        if section_ids:
            placeholders = ",".join(["?"] * len(section_ids))
            clauses.append(
                "EXISTS (SELECT 1 FROM session_tags st_section "
                "WHERE st_section.session_id = sessions.id "
                f"AND st_section.tag_id IN ({placeholders}))"
            )
            args.extend(section_ids)
    join = (
        " INNER JOIN session_tags ON session_tags.session_id = sessions.id"
        if tag_ids is not None
        else ""
    )
    where = "" if not clauses else " WHERE " + " AND ".join(clauses)
    # ``SELECT DISTINCT`` is only required on the legacy ``tag_ids``
    # join path; the EXISTS-based per-class path returns each row once
    # already.
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


_SENTINEL = object()


async def update_fields(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    title: object = _SENTINEL,
    description: object = _SENTINEL,
    max_budget_usd: object = _SENTINEL,
    session_instructions: object = _SENTINEL,
) -> Session | None:
    """Patch arbitrary mutable session columns in one round-trip.

    Only keyword arguments whose value is not ``_SENTINEL`` are written.
    Callers should pass exactly the columns they want to change; all
    others are left untouched (true PATCH semantics).

    Nullable columns (``description``, ``max_budget_usd``,
    ``session_instructions``) may be passed as ``None`` to clear them.
    ``title`` must be a non-empty string.

    Returns the refreshed :class:`Session` row, or ``None`` when no
    row matches ``session_id``.

    Gap: gap-cycle-10-001 (SessionEdit modal — full PATCH surface).
    """
    existing = await get(connection, session_id)
    if existing is None:
        return None

    assignments: list[str] = []
    params: list[object] = []

    if title is not _SENTINEL:
        if not isinstance(title, str) or not title:
            raise ValueError("update_fields: title must be a non-empty string")
        if len(title) > SESSION_TITLE_MAX_LENGTH:
            raise ValueError(f"update_fields: title must be ≤ {SESSION_TITLE_MAX_LENGTH} chars")
        assignments.append("title = ?")
        params.append(title)

    if description is not _SENTINEL:
        if description is not None:
            if not isinstance(description, str):
                raise ValueError("update_fields: description must be a string or None")
            if len(description) > SESSION_DESCRIPTION_MAX_LENGTH:
                raise ValueError(
                    f"update_fields: description must be ≤ {SESSION_DESCRIPTION_MAX_LENGTH} chars"
                )
        assignments.append("description = ?")
        params.append(description)

    if max_budget_usd is not _SENTINEL:
        if max_budget_usd is not None:
            if not isinstance(max_budget_usd, (int, float)):
                raise ValueError("update_fields: max_budget_usd must be a number or None")
            if max_budget_usd < 0:
                raise ValueError("update_fields: max_budget_usd must be ≥ 0")
        assignments.append("max_budget_usd = ?")
        params.append(max_budget_usd)

    if session_instructions is not _SENTINEL:
        if session_instructions is not None:
            if not isinstance(session_instructions, str):
                raise ValueError("update_fields: session_instructions must be a string or None")
            if len(session_instructions) > SESSION_DESCRIPTION_MAX_LENGTH:
                raise ValueError(
                    f"update_fields: session_instructions must be ≤ "
                    f"{SESSION_DESCRIPTION_MAX_LENGTH} chars"
                )
        assignments.append("session_instructions = ?")
        params.append(session_instructions)

    if not assignments:
        # Nothing to write — return existing row unchanged.
        return existing

    timestamp = now_iso()
    assignments.append("updated_at = ?")
    params.append(timestamp)
    params.append(session_id)
    await connection.execute(
        f"UPDATE sessions SET {', '.join(assignments)} WHERE id = ?",
        params,
    )
    await connection.commit()
    return await get(connection, session_id)


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


async def update_routing_decision(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    routing_advisor_model: str | None,
    routing_advisor_max_uses: int,
    routing_effort_level: str,
) -> Session | None:
    """Replace the routing-decision projection; returns the new row or ``None`` if absent.

    Called after session create (persists the full :class:`RoutingDecision`
    evaluated at session-create time) and after ``PATCH
    /api/sessions/{id}/model`` (updates to reflect the new executor's
    routing context). Validation mirrors the :class:`Session` field
    invariants; ``ValueError`` bubbles to the route layer as a 422.
    """
    if routing_advisor_model is not None and not _is_known_model(routing_advisor_model):
        raise ValueError(
            f"update_routing_decision: routing_advisor_model "
            f"{routing_advisor_model!r} not recognised"
        )
    if routing_advisor_max_uses < 0:
        raise ValueError(
            f"update_routing_decision: routing_advisor_max_uses must be ≥ 0 "
            f"(got {routing_advisor_max_uses})"
        )
    if routing_effort_level not in KNOWN_EFFORT_LEVELS:
        raise ValueError(
            f"update_routing_decision: routing_effort_level "
            f"{routing_effort_level!r} not in {sorted(KNOWN_EFFORT_LEVELS)}"
        )
    existing = await get(connection, session_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET "
        "routing_advisor_model = ?, routing_advisor_max_uses = ?, "
        "routing_effort_level = ?, updated_at = ? WHERE id = ?",
        (
            routing_advisor_model,
            routing_advisor_max_uses,
            routing_effort_level,
            timestamp,
            session_id,
        ),
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


async def mark_viewed(
    connection: aiosqlite.Connection,
    session_id: str,
) -> Session | None:
    """Stamp ``last_viewed_at`` to now (idempotent — re-stamps on every call).

    Called by ``POST /api/sessions/{id}/viewed`` when the user selects
    a session row or refocuses the tab while that row is already selected.
    The broadcast that follows clears the unviewed-dot on any other
    open tab / window within a single WebSocket tick.
    """
    existing = await get(connection, session_id)
    if existing is None:
        return None
    timestamp = now_iso()
    await connection.execute(
        "UPDATE sessions SET last_viewed_at = ?, updated_at = ? WHERE id = ?",
        (timestamp, timestamp, session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def update_pinned(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    pinned: bool,
) -> Session | None:
    """Set or clear the ``pinned`` flag; returns the updated row or ``None`` if absent."""
    existing = await get(connection, session_id)
    if existing is None:
        return None
    await connection.execute(
        "UPDATE sessions SET pinned = ?, updated_at = ? WHERE id = ?",
        (1 if pinned else 0, now_iso(), session_id),
    )
    await connection.commit()
    return await get(connection, session_id)


async def add_to_total_cost(
    connection: aiosqlite.Connection,
    session_id: str,
    delta_usd: float,
) -> None:
    """Atomically add ``delta_usd`` to the session row's ``total_cost_usd``.

    Called by :func:`bearings.agent.persistence.persist_assistant_turn`
    after each assistant turn so the session-level rollup the UI reads
    (``GET /api/sessions/{id}.total_cost_usd``) tracks every API call
    billed against the session.

    The row's ``total_cost_usd`` was initialised to ``0.0`` in
    :func:`create` and stays there until this helper increments it. The
    UPDATE uses SQL-side ``+=`` (one statement, atomic against
    concurrent readers) rather than a read-modify-write so two near-
    simultaneous turns on the same session don't race-lose a delta.

    ``delta_usd`` ≤ 0 is a no-op: the SDK emits ``None`` / ``0.0`` for
    cache-only turns or pure-tool turns where no billing happens, and
    skipping those keeps the rollup monotonic per the
    :class:`Session.total_cost_usd ≥ 0` dataclass invariant. ``updated_at``
    is intentionally **not** bumped — cost is a derived rollup, not a
    user-visible content mutation, so caches keyed on ``updated_at``
    stay valid across cost-only updates.
    """
    if delta_usd <= 0:
        return
    await connection.execute(
        "UPDATE sessions SET total_cost_usd = total_cost_usd + ? WHERE id = ?",
        (float(delta_usd), session_id),
    )
    await connection.commit()


async def set_error_pending(
    connection: aiosqlite.Connection,
    session_id: str,
    value: bool,
) -> Session | None:
    """Set or clear the ``error_pending`` flag on a session row.

    Called by the recover route to clear the flag on user-driven
    recovery, and by the runner error hook to set it when the agent
    loop enters the ERROR state.

    Returns the updated :class:`Session` row (re-fetched after the
    write) so callers can broadcast a session-upsert without a second
    query; returns ``None`` when ``session_id`` is not found.
    """
    existing = await get(connection, session_id)
    if existing is None:
        return None
    await connection.execute(
        "UPDATE sessions SET error_pending = ?, updated_at = ? WHERE id = ?",
        (1 if value else 0, now_iso(), session_id),
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


async def get_paired_chat_info(
    connection: aiosqlite.Connection,
    session_id: str,
) -> tuple[str, str] | None:
    """Fetch paired-chat metadata for a chat session.

    When a chat session (``kind='chat'``) is paired to a checklist item
    via ``checklist_item_id``, returns a tuple ``(parent_title, item_label)``
    where:

    * ``parent_title`` is the title of the parent checklist session.
    * ``item_label`` is the label of the checklist item.

    Returns ``None`` when the session is not paired or the session/item
    is absent. Used by the breadcrumb chip on the conversation header
    per ``docs/behavior/paired-chats.md`` §"From the chat side".
    """
    cursor = await connection.execute(
        "SELECT parent.title, item.label "
        "FROM sessions chat "
        "LEFT JOIN checklist_items item ON chat.checklist_item_id = item.id "
        "LEFT JOIN sessions parent ON item.checklist_id = parent.id "
        "WHERE chat.id = ? AND item.id IS NOT NULL",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return None
    parent_title = row[0]
    item_label = row[1]
    return (str(parent_title), str(item_label))


async def get_by_pivot_message_id(
    connection: aiosqlite.Connection,
    pivot_message_id: str,
) -> Session | None:
    """Return the open session spawned from ``pivot_message_id``, or ``None``.

    Used by the spawn-from-reply route (gap-cycle-03-007) to implement
    the idempotency clause: if a previous click already spawned a chat
    for this assistant message, return the existing open session rather
    than creating another.  A closed session is NOT returned — the
    next click should spawn a fresh chat (same semantics as the
    checklist-side paired-chat idempotency contract).
    """
    cursor = await connection.execute(
        _SELECT_SESSION_COLUMNS + " WHERE pivot_message_id = ? AND closed_at IS NULL",
        (pivot_message_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_session(row)


_SELECT_SESSION_COLUMNS = (
    "SELECT id, kind, title, description, session_instructions, working_dir, model, "
    "permission_mode, max_budget_usd, total_cost_usd, message_count, "
    "last_context_pct, last_context_tokens, last_context_max, pinned, error_pending, "
    "checklist_item_id, created_at, updated_at, last_viewed_at, last_completed_at, "
    "closed_at, closing_summary, "
    "routing_advisor_model, routing_advisor_max_uses, routing_effort_level, "
    "pivot_message_id, parent_session_id "
    "FROM sessions"
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
    "sessions.closing_summary, "
    "sessions.routing_advisor_model, sessions.routing_advisor_max_uses, "
    "sessions.routing_effort_level, "
    "sessions.pivot_message_id, sessions.parent_session_id FROM sessions"
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
        routing_advisor_model=None if row[23] is None else str(row[23]),
        routing_advisor_max_uses=int(str(row[24])),
        routing_effort_level=str(row[25]),
        pivot_message_id=None if row[26] is None else str(row[26]),
        parent_session_id=None if row[27] is None else str(row[27]),
    )


__all__ = [
    "Session",
    "add_to_total_cost",
    "close",
    "close_with_summary",
    "create",
    "delete",
    "exists",
    "get",
    "get_by_pivot_message_id",
    "get_kind",
    "get_paired_chat_info",
    "import_session",
    "is_closed",
    "list_all",
    "reopen",
    "update_fields",
    "update_pinned",
    "update_routing_decision",
    "update_title",
]
