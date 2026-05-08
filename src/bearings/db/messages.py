"""``messages`` table queries — chat-kind transcript rows.

Per ``docs/architecture-v1.md`` §1.1.3 this concern module owns every
query that touches ``messages``. Per ``docs/model-routing-v1-spec.md``
§5 the table carries per-model routing/usage columns from day 1
(see ``schema.sql`` — ``executor_model`` / ``advisor_model`` /
``effort_level`` / ``routing_source`` / ``routing_reason`` plus the
five usage columns); item 1.7 laid the user-message INSERT path that
the prompt endpoint uses; item 1.8 added ``matched_rule_id`` for the
override-rate aggregator; item 1.9 wires the assistant-turn INSERT
path that captures :class:`bearings.agent.routing.RoutingDecision`
plus ``ResultMessage.model_usage`` into the per-message row.

Public surface:

* :class:`Message` — frozen dataclass row mirror with
  ``__post_init__`` validation. Carries every spec §5 routing/usage
  column plus the spec §App A ``matched_rule_id`` projection.
* :func:`insert_user`, :func:`insert_system` — non-routing rows
  (``role='user'`` / ``'system'``); the routing/usage columns stay
  NULL.
* :func:`insert_assistant` — assistant-turn row carrying the active
  :class:`bearings.agent.routing.RoutingDecision` + the projected
  per-model token counts from ``ResultMessage.model_usage`` (item
  1.9; spec §5 + arch §5 #3). Called by
  :mod:`bearings.agent.persistence`.
* :func:`get`, :func:`list_for_session`, :func:`count_for_session` —
  read paths the WS handler, the prompt endpoint, and the messages
  API (item 1.9 ``GET /api/sessions/{id}/messages``) use.

Per ``docs/behavior/prompt-endpoint.md`` §"Observability of the queued
prompt" — "The user message is durably persisted **before** the runner
begins the turn." That guarantees a 202 ack survives a server crash
between accept and turn-start; the prompt is replayed on next boot.

Per spec §5 "Backfill for legacy data" the routing/usage columns are
nullable; pre-v1 rows carry ``NULL`` on every column and analytics
queries filter via ``routing_source IS NULL`` or
``routing_source = 'unknown_legacy'``. The schema.sql defaults
encode this contract — see the column-by-column commentary at the
top of ``insert_assistant``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import aiosqlite

from bearings.config.constants import MESSAGE_ID_PREFIX
from bearings.db._id import new_id, now_iso

# Roles the schema accepts (CHECK constraint mirror).
KNOWN_MESSAGE_ROLES: frozenset[str] = frozenset({"user", "assistant", "system", "tool"})


@dataclass(frozen=True)
class Message:
    """Row mirror for the ``messages`` table.

    The routing/usage columns are nullable — only assistant rows
    (filled by :func:`insert_assistant` from
    :mod:`bearings.agent.persistence`) carry them. User and system
    rows leave them ``None``, which the analytics queries filter out
    via ``routing_source IS NULL``.

    ``matched_rule_id`` mirrors :attr:`bearings.agent.routing.RoutingDecision.matched_rule_id`
    per spec §App A and is used by :class:`bearings.agent.override_aggregator.OverrideAggregator`
    (item 1.8) to attribute overrides back to individual rules. ``None`` for
    rows whose routing source is ``'manual'`` / ``'manual_override_quota'`` /
    ``'unknown_legacy'`` / ``'default'`` (no rule fired).

    ``pinned`` and ``hidden_from_context`` are G3 context-menu columns:
    pinned floats the bubble in the conversation header; hidden_from_context
    drops the message from the next prompt context window.
    """

    id: str
    session_id: str
    role: str
    content: str
    created_at: str
    executor_model: str | None
    advisor_model: str | None
    effort_level: str | None
    routing_source: str | None
    routing_reason: str | None
    matched_rule_id: int | None
    executor_input_tokens: int | None
    executor_output_tokens: int | None
    advisor_input_tokens: int | None
    advisor_output_tokens: int | None
    advisor_calls_count: int | None
    cache_read_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    # SQLite implicit rowid — monotonically increasing per insertion order.
    # Exposed as the cursor integer for ``before=`` pagination (item 1.3).
    seq: int
    # G3 context-menu state columns (DEFAULT 0 for all existing rows).
    pinned: bool = False
    hidden_from_context: bool = False
    # Inspector Routing eval-chain — ordered rule ids tested by the
    # routing engine (``RoutingDecision.evaluated_rules``). Empty list
    # for rows that predate this column or used a manual/legacy source.
    evaluated_rules: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Message.id must be non-empty")
        if not self.session_id:
            raise ValueError("Message.session_id must be non-empty")
        if self.role not in KNOWN_MESSAGE_ROLES:
            raise ValueError(f"Message.role {self.role!r} not in {sorted(KNOWN_MESSAGE_ROLES)}")
        # Empty content is allowed for tool rows (a tool that produced no
        # stdout); user rows are validated at the API boundary against
        # the prompt-endpoint's "non-empty after stripping whitespace"
        # rule, so this dataclass does not gate on user-row content.
        # Token counters are non-negative when set (NULL = legacy /
        # not-yet-captured row per spec §5 "Backfill for legacy data").
        for field_name, value in (
            ("executor_input_tokens", self.executor_input_tokens),
            ("executor_output_tokens", self.executor_output_tokens),
            ("advisor_input_tokens", self.advisor_input_tokens),
            ("advisor_output_tokens", self.advisor_output_tokens),
            ("advisor_calls_count", self.advisor_calls_count),
            ("cache_read_tokens", self.cache_read_tokens),
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if value is not None and value < 0:
                raise ValueError(f"Message.{field_name} must be >= 0 if set (got {value})")


async def insert_user(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    content: str,
) -> Message:
    """Insert a user-role message row + bump ``sessions.message_count``.

    The two writes happen inside one transaction (a single ``commit``
    after both UPDATEs) so the count never lies relative to the row.
    Per ``docs/behavior/prompt-endpoint.md`` §"Observability of the
    queued prompt" the row must be durable before the runner picks up
    the prompt — the caller is responsible for not dispatching to the
    runner until this returns.
    """
    return await _insert(connection, session_id=session_id, role="user", content=content)


async def insert_system(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    content: str,
) -> Message:
    """Insert a system-role message row.

    System rows are how Bearings surfaces session-state notices the
    user observes inline (e.g. the "resuming prompt from previous
    session" hint per behavior doc §"Observability of the queued
    prompt"). Same write-then-bump shape as :func:`insert_user`.
    """
    return await _insert(connection, session_id=session_id, role="system", content=content)


async def _insert(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    role: str,
    content: str,
) -> Message:
    """Internal — insert a non-routing row and bump the session counter."""
    timestamp = now_iso()
    message_id = new_id(MESSAGE_ID_PREFIX)
    Message(
        id=message_id,
        session_id=session_id,
        role=role,
        content=content,
        created_at=timestamp,
        executor_model=None,
        advisor_model=None,
        effort_level=None,
        routing_source=None,
        routing_reason=None,
        matched_rule_id=None,
        executor_input_tokens=None,
        executor_output_tokens=None,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=None,
        cache_read_tokens=None,
        input_tokens=None,
        output_tokens=None,
        seq=0,  # placeholder — rowid assigned by DB; actual value via get()
        evaluated_rules=[],
    )
    await connection.execute(
        "INSERT INTO messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (message_id, session_id, role, content, timestamp),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
        (timestamp, session_id),
    )
    await connection.commit()
    fetched = await get(connection, message_id)
    if fetched is None:  # pragma: no cover — INSERT just succeeded
        raise RuntimeError(f"messages._insert: row {message_id!r} vanished after INSERT")
    return fetched


async def insert_assistant(
    connection: aiosqlite.Connection,
    *,
    session_id: str,
    content: str,
    executor_model: str,
    advisor_model: str | None,
    effort_level: str,
    routing_source: str,
    routing_reason: str,
    matched_rule_id: int | None,
    evaluated_rules: list[int],
    executor_input_tokens: int | None,
    executor_output_tokens: int | None,
    advisor_input_tokens: int | None,
    advisor_output_tokens: int | None,
    advisor_calls_count: int,
    cache_read_tokens: int | None,
) -> Message:
    """Insert an assistant-role row carrying the spec §5 routing + usage fields.

    Called by :func:`bearings.agent.persistence.persist_assistant_turn`
    at message-completion time per spec §11 build-step 6 ("Wire
    executor/advisor/effort/source/reason into the agent call path.
    Read ``ResultMessage.model_usage`` and persist to message rows").
    The five routing fields project the active
    :class:`bearings.agent.routing.RoutingDecision`; the six token
    fields project ``ResultMessage.model_usage`` via
    :func:`bearings.agent.persistence.extract_model_usage`.

    Per spec §5 "Backfill for legacy data" all six token fields are
    nullable so legacy ``unknown_legacy`` rows can be migrated with
    NULLs where the data is unavailable; the migration in item 3.2
    populates what it can. ``advisor_calls_count`` is required (not
    NULL) because the SDK always reports a count (zero if no advisor
    call was made on this turn) — the column carries an explicit
    ``DEFAULT 0`` in schema.sql for the same reason.

    Bumps ``sessions.message_count`` in the same transaction so the
    sidebar count never lies relative to the row.
    """
    timestamp = now_iso()
    message_id = new_id(MESSAGE_ID_PREFIX)
    # Construct + validate the dataclass first; surfaces shape errors
    # before any DB write occurs (atomicity holds because the entire
    # method runs inside one connection's implicit transaction).
    # ``seq=0`` is a placeholder — the real rowid is assigned by SQLite
    # and returned via ``get()`` below; validation only needs to catch
    # business-rule violations (role, token sign, etc.).
    Message(
        id=message_id,
        session_id=session_id,
        role="assistant",
        content=content,
        created_at=timestamp,
        executor_model=executor_model,
        advisor_model=advisor_model,
        effort_level=effort_level,
        routing_source=routing_source,
        routing_reason=routing_reason,
        matched_rule_id=matched_rule_id,
        executor_input_tokens=executor_input_tokens,
        executor_output_tokens=executor_output_tokens,
        advisor_input_tokens=advisor_input_tokens,
        advisor_output_tokens=advisor_output_tokens,
        advisor_calls_count=advisor_calls_count,
        cache_read_tokens=cache_read_tokens,
        input_tokens=None,
        output_tokens=None,
        seq=0,
        evaluated_rules=evaluated_rules,
    )
    await connection.execute(
        "INSERT INTO messages ("
        "id, session_id, role, content, created_at, "
        "executor_model, advisor_model, effort_level, "
        "routing_source, routing_reason, matched_rule_id, evaluated_rules, "
        "executor_input_tokens, executor_output_tokens, "
        "advisor_input_tokens, advisor_output_tokens, "
        "advisor_calls_count, cache_read_tokens"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            message_id,
            session_id,
            "assistant",
            content,
            timestamp,
            executor_model,
            advisor_model,
            effort_level,
            routing_source,
            routing_reason,
            matched_rule_id,
            json.dumps(evaluated_rules),
            executor_input_tokens,
            executor_output_tokens,
            advisor_input_tokens,
            advisor_output_tokens,
            advisor_calls_count,
            cache_read_tokens,
        ),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = message_count + 1, updated_at = ? WHERE id = ?",
        (timestamp, session_id),
    )
    await connection.commit()
    fetched = await get(connection, message_id)
    if fetched is None:  # pragma: no cover — INSERT just succeeded
        raise RuntimeError(f"messages.insert_assistant: row {message_id!r} vanished after INSERT")
    return fetched


async def get(
    connection: aiosqlite.Connection,
    message_id: str,
) -> Message | None:
    """Fetch a single message by id; ``None`` if absent."""
    cursor = await connection.execute(
        _SELECT_MESSAGE_COLUMNS + " WHERE id = ?",
        (message_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_message(row)


async def latest_user_content(
    connection: aiosqlite.Connection,
    session_id: str,
) -> str | None:
    """Return the most recent user-role message content; ``None`` if none.

    Backs ``POST /api/sessions/{id}/regenerate`` (arch §1.1.5 — landed
    in the v1.1 closing-sweep). The route replays the latest user
    prompt by re-dispatching its content; this helper is the read.

    Returns ``None`` when the session has no user-role messages yet
    (a freshly created session that's never been prompted) — the
    route layer translates that to a 409 because there's nothing to
    regenerate from.
    """
    cursor = await connection.execute(
        _SELECT_MESSAGE_COLUMNS + " WHERE session_id = ? AND role = 'user' "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_message(row).content


async def list_for_session(
    connection: aiosqlite.Connection,
    session_id: str,
    *,
    limit: int | None = None,
    before: int | None = None,
) -> list[Message]:
    """Messages under ``session_id``, oldest-first.

    ``limit`` returns the **last** N rows (most recent N) — used by the
    session-open tail fetch and ``loadOlder()`` cursor pages (item 1.3).

    ``before`` (SQLite rowid) restricts to rows inserted before that
    cursor, enabling backward pagination: the caller passes the lowest
    ``seq`` it has seen so far to walk further into the past.
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"list_for_session: limit must be > 0 if set (got {limit})")
    conditions = ["session_id = ?"]
    params: list[object] = [session_id]
    if before is not None:
        conditions.append("rowid < ?")
        params.append(before)
    where = " WHERE " + " AND ".join(conditions)
    if limit is None:
        cursor = await connection.execute(
            _SELECT_MESSAGE_COLUMNS + where + " ORDER BY created_at ASC, id ASC",
            tuple(params),
        )
    else:
        # Tail-N: DESC + limit, reversed to chronological at the call site.
        cursor = await connection.execute(
            _SELECT_MESSAGE_COLUMNS + where + " ORDER BY created_at DESC, id DESC LIMIT ?",
            (*tuple(params), limit),
        )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    messages = [_row_to_message(row) for row in rows]
    if limit is not None:
        messages.reverse()
    return messages


async def get_token_totals(
    connection: aiosqlite.Connection,
    session_id: str,
) -> tuple[int, int, int, int]:
    """Aggregate lifetime token totals for ``session_id``.

    Returns ``(input, output, cache_read, cache_creation)`` summed across
    all assistant-role rows.  NULL token fields are treated as 0 by
    ``COALESCE``.  ``cache_creation`` is always ``0`` in v18 — the
    ``messages`` table has no ``cache_creation_tokens`` column yet; the
    slot is reserved in the response shape for when the backend surface
    lands.

    Per ``docs/behavior/chat.md`` §"Token totals hydration contract"
    (gap-cycle-13-003).
    """
    cursor = await connection.execute(
        "SELECT"
        "  COALESCE(SUM(executor_input_tokens), 0),"
        "  COALESCE(SUM(executor_output_tokens), 0),"
        "  COALESCE(SUM(cache_read_tokens), 0)"
        " FROM messages"
        " WHERE session_id = ? AND role = 'assistant'",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    if row is None:
        return (0, 0, 0, 0)
    return (int(row[0]), int(row[1]), int(row[2]), 0)


async def count_for_session(
    connection: aiosqlite.Connection,
    session_id: str,
) -> int:
    """Number of messages on ``session_id``."""
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ?",
        (session_id,),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return 0 if row is None else int(row[0])


async def get_preceding_user_message(
    connection: aiosqlite.Connection,
    session_id: str,
    before_seq: int,
) -> Message | None:
    """Return the most recent user-role message with rowid < ``before_seq``.

    Backs ``POST /api/sessions/{id}/regenerate_from/{message_id}`` — finds
    the user prompt that immediately precedes the assistant turn the user
    right-clicked. Returns ``None`` when no user message exists before that
    seq (the assistant turn is the first message, which is unusual but
    possible in edge cases).
    """
    cursor = await connection.execute(
        _SELECT_MESSAGE_COLUMNS + " WHERE session_id = ? AND role = 'user' AND rowid < ?"
        " ORDER BY rowid DESC LIMIT 1",
        (session_id, before_seq),
    )
    try:
        row = await cursor.fetchone()
    finally:
        await cursor.close()
    return None if row is None else _row_to_message(row)


async def truncate_after(
    connection: aiosqlite.Connection,
    session_id: str,
    pivot_seq: int,
) -> int:
    """Delete all messages with rowid > ``pivot_seq`` on ``session_id``; fix message_count.

    Returns the count of deleted rows. Used by
    ``POST /api/sessions/{id}/regenerate_from/{message_id}`` to discard the
    clicked assistant turn and any messages that follow it before
    re-queuing the pivot user prompt.

    The ``message_count`` decrement and the DELETE happen inside one
    ``commit`` so the sidebar counter never drifts relative to the row count.
    """
    cursor = await connection.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND rowid > ?",
        (session_id, pivot_seq),
    )
    try:
        count_row = await cursor.fetchone()
    finally:
        await cursor.close()
    deleted_count = 0 if count_row is None else int(count_row[0])
    if deleted_count == 0:
        return 0
    await connection.execute(
        "DELETE FROM messages WHERE session_id = ? AND rowid > ?",
        (session_id, pivot_seq),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - ?) WHERE id = ?",
        (deleted_count, session_id),
    )
    await connection.commit()
    return deleted_count


async def update_pinned(
    connection: aiosqlite.Connection,
    message_id: str,
    *,
    pinned: bool,
) -> Message | None:
    """Set or clear the ``pinned`` flag; returns the updated row or ``None`` if absent."""
    existing = await get(connection, message_id)
    if existing is None:
        return None
    await connection.execute(
        "UPDATE messages SET pinned = ? WHERE id = ?",
        (1 if pinned else 0, message_id),
    )
    await connection.commit()
    return await get(connection, message_id)


async def update_hidden(
    connection: aiosqlite.Connection,
    message_id: str,
    *,
    hidden: bool,
) -> Message | None:
    """Set or clear the ``hidden_from_context`` flag; returns the updated row or ``None``."""
    existing = await get(connection, message_id)
    if existing is None:
        return None
    await connection.execute(
        "UPDATE messages SET hidden_from_context = ? WHERE id = ?",
        (1 if hidden else 0, message_id),
    )
    await connection.commit()
    return await get(connection, message_id)


async def delete(
    connection: aiosqlite.Connection,
    message_id: str,
) -> bool:
    """Delete a message by id; returns ``True`` if a row was deleted, ``False`` if absent."""
    existing = await get(connection, message_id)
    if existing is None:
        return False
    await connection.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    # Decrement the session message count to keep the sidebar counter accurate.
    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - 1) WHERE id = ?",
        (existing.session_id,),
    )
    await connection.commit()
    return True


async def move_to_session(
    connection: aiosqlite.Connection,
    message_id: str,
    *,
    target_session_id: str,
) -> Message | None:
    """Re-parent a message to ``target_session_id``.

    Decrements the source session's ``message_count`` and increments the
    target's. Returns the updated message row, or ``None`` if the message
    or target session is absent.
    """
    existing = await get(connection, message_id)
    if existing is None:
        return None
    # Verify the target session exists before mutating.
    cursor = await connection.execute("SELECT id FROM sessions WHERE id = ?", (target_session_id,))
    try:
        target_row = await cursor.fetchone()
    finally:
        await cursor.close()
    if target_row is None:
        return None
    source_session_id = existing.session_id
    await connection.execute(
        "UPDATE messages SET session_id = ? WHERE id = ?",
        (target_session_id, message_id),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = MAX(0, message_count - 1) WHERE id = ?",
        (source_session_id,),
    )
    await connection.execute(
        "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
        (target_session_id,),
    )
    await connection.commit()
    return await get(connection, message_id)


_SELECT_MESSAGE_COLUMNS = (
    "SELECT id, session_id, role, content, created_at, "
    "executor_model, advisor_model, effort_level, routing_source, routing_reason, "
    "matched_rule_id, "
    "executor_input_tokens, executor_output_tokens, advisor_input_tokens, "
    "advisor_output_tokens, advisor_calls_count, cache_read_tokens, "
    "input_tokens, output_tokens, rowid AS seq, "
    "COALESCE(pinned, 0) AS pinned, "
    "COALESCE(hidden_from_context, 0) AS hidden_from_context, "
    "COALESCE(evaluated_rules, '[]') AS evaluated_rules "
    "FROM messages"
)


async def import_messages(
    connection: aiosqlite.Connection,
    *,
    messages: list[dict[str, object]],
) -> None:
    """Bulk-insert message rows preserving original ids and all field values.

    Used exclusively by ``POST /api/sessions/import``.  Unlike
    :func:`insert_user` / :func:`insert_assistant`, this path accepts
    full-fidelity rows from an export blob and inserts them verbatim —
    including original ids, timestamps, routing columns, and token
    counts.  ``message_count`` on the parent session is managed by the
    route handler (set once from the export, not incremented per row
    here).

    ``messages`` is a list of dicts whose keys match the column names
    of the ``messages`` table.  Each dict is the ``model_dump()`` of a
    :class:`bearings.web.models.sessions.MessageExport` instance.

    Raises ``ValueError`` when the role of any message is outside
    :data:`KNOWN_MESSAGE_ROLES` (validated before any INSERT).
    """
    if not messages:
        return
    for m in messages:
        role = str(m.get("role", ""))
        if role not in KNOWN_MESSAGE_ROLES:
            raise ValueError(f"import_messages: role {role!r} not in {sorted(KNOWN_MESSAGE_ROLES)}")
    rows = [
        (
            str(m["id"]),
            str(m["session_id"]),
            str(m["role"]),
            str(m["content"]),
            str(m["created_at"]),
            m.get("executor_model"),
            m.get("advisor_model"),
            m.get("effort_level"),
            m.get("routing_source"),
            m.get("routing_reason"),
            m.get("matched_rule_id"),
            json.dumps(m.get("evaluated_rules") or []),
            m.get("executor_input_tokens"),
            m.get("executor_output_tokens"),
            m.get("advisor_input_tokens"),
            m.get("advisor_output_tokens"),
            m.get("advisor_calls_count"),
            m.get("cache_read_tokens"),
            m.get("input_tokens"),
            m.get("output_tokens"),
            int(bool(m.get("pinned", False))),
            int(bool(m.get("hidden_from_context", False))),
        )
        for m in messages
    ]
    await connection.executemany(
        "INSERT INTO messages "
        "(id, session_id, role, content, created_at, "
        "executor_model, advisor_model, effort_level, routing_source, routing_reason, "
        "matched_rule_id, evaluated_rules, executor_input_tokens, executor_output_tokens, "
        "advisor_input_tokens, advisor_output_tokens, advisor_calls_count, "
        "cache_read_tokens, input_tokens, output_tokens, pinned, hidden_from_context) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    await connection.commit()


def _row_to_message(row: aiosqlite.Row | tuple[object, ...]) -> Message:
    """Translate a raw SELECT tuple into a validated :class:`Message`."""
    raw_evaluated = row[22]
    try:
        evaluated_rules: list[int] = json.loads(str(raw_evaluated)) if raw_evaluated else []
    except (ValueError, TypeError):
        evaluated_rules = []
    return Message(
        id=str(row[0]),
        session_id=str(row[1]),
        role=str(row[2]),
        content=str(row[3]),
        created_at=str(row[4]),
        executor_model=None if row[5] is None else str(row[5]),
        advisor_model=None if row[6] is None else str(row[6]),
        effort_level=None if row[7] is None else str(row[7]),
        routing_source=None if row[8] is None else str(row[8]),
        routing_reason=None if row[9] is None else str(row[9]),
        matched_rule_id=None if row[10] is None else int(str(row[10])),
        executor_input_tokens=None if row[11] is None else int(str(row[11])),
        executor_output_tokens=None if row[12] is None else int(str(row[12])),
        advisor_input_tokens=None if row[13] is None else int(str(row[13])),
        advisor_output_tokens=None if row[14] is None else int(str(row[14])),
        advisor_calls_count=None if row[15] is None else int(str(row[15])),
        cache_read_tokens=None if row[16] is None else int(str(row[16])),
        input_tokens=None if row[17] is None else int(str(row[17])),
        output_tokens=None if row[18] is None else int(str(row[18])),
        seq=int(str(row[19])),
        pinned=bool(int(str(row[20]))) if row[20] is not None else False,
        hidden_from_context=bool(int(str(row[21]))) if row[21] is not None else False,
        evaluated_rules=evaluated_rules,
    )


__all__ = [
    "KNOWN_MESSAGE_ROLES",
    "Message",
    "count_for_session",
    "delete",
    "get",
    "get_preceding_user_message",
    "get_token_totals",
    "import_messages",
    "insert_assistant",
    "insert_system",
    "insert_user",
    "list_for_session",
    "move_to_session",
    "truncate_after",
    "update_hidden",
    "update_pinned",
]
