"""Spawn-from-reply route — gap-cycle-03-007.

Per ``docs/behavior/paired-chats.md`` §"Spawn from reply" the user
clicks the **+ SPAWN** pill on an assistant message in a non-paired
session and observes:

1. A fresh chat session is created with ``kind='chat'``, inheriting
   the parent session's ``working_dir`` and ``model``.
2. The first user message in the new chat is a blockquote of the
   clicked assistant message body.
3. The new session records ``pivot_message_id`` (the clicked message)
   and ``parent_session_id`` (the originating session) for the
   idempotency check and the sidebar back-link.

The spawn is **idempotent**: if an open session already exists for this
``pivot_message_id``, the same session id is returned (HTTP 200 instead
of 201).

The single endpoint:

* ``POST /api/sessions/{parent_id}/spawn_from_reply/{message_id}``
"""

from __future__ import annotations

from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, Response, status

from bearings.config.constants import SESSION_KIND_CHAT, SPAWN_FROM_REPLY_QUOTE_PREFIX
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.web.models.spawn_from_reply import SpawnFromReplyOut

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _quote_body(body: str) -> str:
    """Wrap ``body`` in a Markdown blockquote for the seed message.

    Each line is prefixed with ``SPAWN_FROM_REPLY_QUOTE_PREFIX``
    (``"> "``).  Empty trailing lines are stripped so the seed message
    is clean without requiring the user to delete whitespace.
    """
    lines = body.rstrip().splitlines() or [""]
    return "\n".join(f"{SPAWN_FROM_REPLY_QUOTE_PREFIX}{line}" for line in lines)


@router.post(
    "/api/sessions/{parent_id}/spawn_from_reply/{message_id}",
    operation_id="spawn-session-from-reply",
)
async def spawn_from_reply(
    parent_id: str,
    message_id: str,
    request: Request,
) -> Response:
    """Create a paired chat seeded with a quote of the pivot assistant message.

    Per ``docs/behavior/paired-chats.md`` §"Spawn from reply":

    1. First click — 201 Created with the new session id.
    2. Subsequent clicks on the same ``message_id`` while the spawned
       chat is still open — 200 OK with the existing session (idempotent).
    3. ``parent_id`` not found — 404.
    4. ``message_id`` not found or does not belong to ``parent_id`` — 404.
    5. ``message_id`` is not an assistant-role message — 422 (only
       assistant messages can be the pivot).
    """
    db = _db(request)

    # Validate parent session exists.
    parent = await sessions_db.get(db, parent_id)
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {parent_id!r} not found",
        )

    # Validate pivot message exists and belongs to the parent session.
    pivot = await messages_db.get(db, message_id)
    if pivot is None or pivot.session_id != parent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"message {message_id!r} not found in session {parent_id!r}",
        )
    if pivot.role != "assistant":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"message {message_id!r} has role {pivot.role!r}; "
                "only assistant messages can be the spawn pivot"
            ),
        )

    # Idempotency check: return existing open session if one already
    # exists for this pivot message.
    existing = await sessions_db.get_by_pivot_message_id(db, message_id)
    if existing is not None:
        body = SpawnFromReplyOut(
            chat_session_id=existing.id,
            parent_session_id=parent_id,
            pivot_message_id=message_id,
            title=existing.title,
            working_dir=existing.working_dir,
            model=existing.model,
            created=False,
        )
        return Response(
            content=body.model_dump_json(),
            status_code=status.HTTP_200_OK,
            media_type="application/json",
        )

    # First spawn — derive title from parent session title + a short
    # truncation of the pivot message so the sidebar row is recognisable.
    snippet = pivot.content[:60].rstrip()
    if len(pivot.content) > 60:
        snippet += "…"
    title = f"{parent.title} - reply"

    new_session = await sessions_db.create(
        db,
        kind=SESSION_KIND_CHAT,
        title=title,
        working_dir=parent.working_dir,
        model=parent.model,
        pivot_message_id=message_id,
        parent_session_id=parent_id,
    )

    # Seed the first user message as a blockquote of the pivot body.
    seed_content = _quote_body(pivot.content)
    await messages_db.insert_user(db, session_id=new_session.id, content=seed_content)

    body = SpawnFromReplyOut(
        chat_session_id=new_session.id,
        parent_session_id=parent_id,
        pivot_message_id=message_id,
        title=new_session.title,
        working_dir=new_session.working_dir,
        model=new_session.model,
        created=True,
    )
    return Response(
        content=body.model_dump_json(),
        status_code=status.HTTP_201_CREATED,
        media_type="application/json",
    )


__all__ = ["router"]
