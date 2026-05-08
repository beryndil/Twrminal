"""Messages routes — per-session transcript fetch + single-message lookup.

Per ``docs/architecture-v1.md`` §1.1.5 every route group lives in its
own module; this one owns:

* ``GET /api/sessions/{session_id}/messages`` — transcript list
  (oldest first; optional ``limit`` returns the tail of N rows so a
  long-running session's first paint stays bounded).
* ``GET /api/messages/{message_id}`` — single-row fetch (used by the
  InspectorRouting "Why this model?" panel per spec §10 to fetch
  the per-message routing decision on demand).

Per ``docs/model-routing-v1-spec.md`` §5 + §7 the response carries
every routing-decision and per-model-usage column the spec declares,
plus the spec §App A ``matched_rule_id`` projection. The DB-layer
read paths in :mod:`bearings.db.messages` already select all columns
in their canonical order; this module is a thin shape adapter.

Item 1.9 contract:

* The list endpoint returns rows in chronological order (the natural
  order assistant + user turns interleaved on the wire).
* The single-fetch endpoint 404s on a missing ``message_id`` — the
  same shape the sessions / checklist single-fetch endpoints use.
* Both endpoints return :class:`bearings.web.models.messages.MessageOut`
  (Pydantic shape pinned in ``web/models/messages.py``); FastAPI's
  ``response_model`` validator enforces the wire schema.
"""

from __future__ import annotations

from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.config.constants import MESSAGES_LIST_MAX_LIMIT
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.messages import Message
from bearings.web.models.messages import (
    MessageHiddenUpdate,
    MessageMoveRequest,
    MessageOut,
    MessagePage,
    MessagePinnedUpdate,
)

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state`` (503 if absent)."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _to_out(message: Message) -> MessageOut:
    """Translate :class:`Message` to the wire shape (column-by-column)."""
    return MessageOut(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        executor_model=message.executor_model,
        advisor_model=message.advisor_model,
        effort_level=message.effort_level,
        routing_source=message.routing_source,
        routing_reason=message.routing_reason,
        matched_rule_id=message.matched_rule_id,
        evaluated_rules=message.evaluated_rules,
        executor_input_tokens=message.executor_input_tokens,
        executor_output_tokens=message.executor_output_tokens,
        advisor_input_tokens=message.advisor_input_tokens,
        advisor_output_tokens=message.advisor_output_tokens,
        advisor_calls_count=message.advisor_calls_count,
        cache_read_tokens=message.cache_read_tokens,
        input_tokens=message.input_tokens,
        output_tokens=message.output_tokens,
        seq=message.seq,
        pinned=message.pinned,
        hidden_from_context=message.hidden_from_context,
    )


@router.get(
    "/api/sessions/{session_id}/messages",
    response_model=MessagePage,
    operation_id="list-messages",
)
async def list_messages(
    session_id: str,
    request: Request,
    limit: int | None = Query(
        default=None,
        gt=0,
        le=MESSAGES_LIST_MAX_LIMIT,
        description=(
            "If set, return the last N messages (most recent N). "
            "Omit for the full transcript (``has_more`` is always ``False``)."
        ),
    ),
    before: int | None = Query(
        default=None,
        gt=0,
        description=(
            "Cursor for backward pagination (item 1.3). Pass the ``seq`` "
            "(SQLite rowid) of the oldest message currently held to fetch "
            "the page that precedes it. Combine with ``limit`` for bounded "
            "pages; omit ``limit`` to fetch everything older than the cursor."
        ),
    ),
) -> MessagePage:
    """List messages for ``session_id``, oldest first, with pagination.

    Returns a :class:`MessagePage` envelope: ``items`` in chronological
    order + ``has_more: bool`` indicating whether an older page exists.

    Pagination contract (item 1.3):

    * Session-open: call with ``limit=N`` (no ``before``). Response
      carries the *tail* N messages + ``has_more`` flag.
    * Load-older: call with ``limit=N`` + ``before=<seq>`` where
      ``seq`` is the lowest ``seq`` value in the current view.
      Each call walks one page further into the past.
    * Full-transcript (e.g. Inspector panel): omit both params.
      ``has_more`` is always ``False`` in this case.

    404s if no session matches ``session_id``, distinguishing "session
    does not exist" from "session has no messages" (empty ``items`` is
    a valid response for a freshly-created session).
    """
    db = _db(request)
    session = await sessions_db.get(db, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no session matches {session_id!r}",
        )
    # Fetch one extra row to detect has_more without a separate COUNT.
    # The DB layer returns rows in chronological order (oldest first) after
    # DESC + LIMIT + reverse. Fetching N+1 means if we get N+1 rows, the
    # extra one is at index 0 (the oldest, outside the actual page window),
    # so we trim from the front with ``rows[-limit:]``.
    fetch_limit = None if limit is None else limit + 1
    rows = await messages_db.list_for_session(db, session_id, limit=fetch_limit, before=before)
    has_more = False
    if limit is not None and len(rows) > limit:
        has_more = True
        rows = rows[-limit:]
    return MessagePage(items=[_to_out(row) for row in rows], has_more=has_more)


@router.get("/api/messages/{message_id}", response_model=MessageOut, operation_id="get-message")
async def get_message(message_id: str, request: Request) -> MessageOut:
    """Fetch a single message by id; 404 if absent."""
    db = _db(request)
    row = await messages_db.get(db, message_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no message matches {message_id!r}",
        )
    return _to_out(row)


@router.patch(
    "/api/messages/{message_id}/pinned",
    response_model=MessageOut,
    operation_id="patch-message-pinned",
)
async def patch_message_pinned(
    message_id: str,
    payload: MessagePinnedUpdate,
    request: Request,
) -> MessageOut:
    """Pin or unpin a message via ``PATCH /api/messages/{id}/pinned`` (G3).

    ``{pinned: true}`` pins the bubble; ``{pinned: false}`` unpins it.
    Idempotent. Returns the updated message row. 404 when absent.
    """
    db = _db(request)
    row = await messages_db.update_pinned(db, message_id, pinned=payload.pinned)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no message matches {message_id!r}",
        )
    return _to_out(row)


@router.patch(
    "/api/messages/{message_id}/hidden",
    response_model=MessageOut,
    operation_id="patch-message-hidden",
)
async def patch_message_hidden(
    message_id: str,
    payload: MessageHiddenUpdate,
    request: Request,
) -> MessageOut:
    """Show or hide a message from the context window (G3).

    ``{hidden: true}`` drops the message from the next prompt context;
    ``{hidden: false}`` restores it. Returns the updated row. 404 when absent.
    """
    db = _db(request)
    row = await messages_db.update_hidden(db, message_id, hidden=payload.hidden)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no message matches {message_id!r}",
        )
    return _to_out(row)


@router.delete(
    "/api/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete-message",
)
async def delete_message(message_id: str, request: Request) -> None:
    """Delete a message by id (G3). 204 on success; 404 when absent."""
    db = _db(request)
    deleted = await messages_db.delete(db, message_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no message matches {message_id!r}",
        )


@router.post(
    "/api/messages/{message_id}/move",
    response_model=MessageOut,
    operation_id="move-message",
)
async def move_message(
    message_id: str,
    payload: MessageMoveRequest,
    request: Request,
) -> MessageOut:
    """Re-parent a message to another session (G3).

    Body: ``{target_session_id: str}``. Returns the updated message row.
    404 when the message or target session is absent.
    """
    db = _db(request)
    row = await messages_db.move_to_session(
        db, message_id, target_session_id=payload.target_session_id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"no message {message_id!r} or no session {payload.target_session_id!r}"),
        )
    return _to_out(row)


__all__ = ["router"]
