"""Paired-chat spawn-and-link routes.

Per ``docs/architecture-v1.md`` §1.1.5 the paired-chat *link* /
*unlink* endpoints already live in ``web/routes/checklists.py``
(linking-to-existing + clearing the pair pointer); this module owns
the **spawn-a-fresh-chat** path that ``💬 Work on this`` per
``docs/behavior/paired-chats.md`` §"Spawning a new pair" resolves to.

The single endpoint:

* ``POST /api/checklist-items/{id}/spawn-chat`` — 201 on first spawn,
  200 on the idempotent re-click. Body in :class:`SpawnPairedChatOut`.

The route's body is thin per arch §1.1.5: argument parsing, single
domain call into :func:`bearings.agent.paired_chats.spawn_paired_chat`,
response formatting. The agent service does the cross-table
composition (session create + tag attach + leg record + pair
pointer set).
"""

from __future__ import annotations

from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, Response, status

from bearings.agent.paired_chats import (
    PairedChatSpawnError,
    spawn_paired_chat,
)
from bearings.agent.session_assembly import SessionAssemblyError
from bearings.config.constants import KNOWN_PAIRED_CHAT_SPAWNED_BY
from bearings.db import checklists as checklists_db
from bearings.db import sessions as sessions_db
from bearings.db.checklists import ChecklistItem
from bearings.web.models.paired_chats import SpawnPairedChatIn, SpawnPairedChatOut

router = APIRouter()


async def _get_pre_existing_open_chat_id(
    db: aiosqlite.Connection,
    item: ChecklistItem,
) -> str | None:
    """Return the existing open chat session id, or None when absent/closed."""
    chat_id = item.chat_session_id
    if chat_id is None:
        return None
    if await sessions_db.is_closed(db, chat_id) is False:
        return chat_id
    return None


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


@router.post("/api/checklist-items/{item_id}/spawn-chat")
async def spawn_chat(
    item_id: int,
    payload: SpawnPairedChatIn,
    request: Request,
) -> Response:
    """Materialise a fresh paired chat for the leaf, or return existing pair.

    Per ``docs/behavior/paired-chats.md`` §"Spawning a new pair":

    1. First click — 201 Created with the new session id, title, etc.
    2. Subsequent clicks on an already-paired item — 200 OK with the
       existing pair (idempotency clause).
    3. Parent items / unknown items — 422 / 404 respectively.
    4. Working directory unresolvable from parent + tags — 422.
    """
    db = _db(request)
    if payload.spawned_by not in KNOWN_PAIRED_CHAT_SPAWNED_BY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"spawned_by {payload.spawned_by!r} not in {sorted(KNOWN_PAIRED_CHAT_SPAWNED_BY)}"
            ),
        )
    # Pre-check the item-side state so we can distinguish 404 (item
    # missing) from 422 (parent item / leaves-only) from 200 (existing
    # pair) before invoking the spawn — the spawn function itself
    # raises a single PairedChatSpawnError covering both, but the route
    # layer wants distinct status codes.
    item = await checklists_db.get(db, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"item {item_id} not found",
        )
    pre_existing_open_chat_id = await _get_pre_existing_open_chat_id(db, item)
    try:
        chat_id, _config = await spawn_paired_chat(
            db,
            item_id=item_id,
            spawned_by=payload.spawned_by,
            title_override=payload.title,
            plug=payload.plug,
        )
    except PairedChatSpawnError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except SessionAssemblyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    chat = await sessions_db.get(db, chat_id)
    if chat is None:  # pragma: no cover — spawn just succeeded
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"paired chat {chat_id!r} vanished after spawn",
        )
    created = pre_existing_open_chat_id != chat_id
    body = SpawnPairedChatOut(
        chat_session_id=chat.id,
        item_id=item_id,
        title=chat.title,
        working_dir=chat.working_dir,
        model=chat.model,
        created=created,
    )
    return Response(
        content=body.model_dump_json(),
        status_code=(status.HTTP_201_CREATED if created else status.HTTP_200_OK),
        media_type="application/json",
    )


__all__ = ["router"]
