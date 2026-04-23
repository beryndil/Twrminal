"""Message mutation surface (Phase 8 of docs/context-menu-plan.md).

URL shape — mounted at `/api`:

  PATCH /messages/{message_id} — toggle `pinned` / `hidden_from_context`

Only flag columns are mutable here. The row's `content`, `thinking`, and
token counts stay immutable on purpose — editing a persisted turn would
desync the SDK's view of the conversation from the DB and the first
replay after a server restart would land the agent in an inconsistent
state. Flag changes are safe because they don't mutate the prompt text;
`hidden_from_context` only affects which prior rows the assembler hands
back to the next turn.

Thin handler: `store.update_message_flags` does the column-level work
and returns the refreshed row (or None on unknown id). A body with every
field unset is a no-op — we still return 200 with the current shape so
the UI reconciles without a dedicated "nothing-to-do" branch. Metrics
bump once per non-null field actually applied, so a single PATCH that
toggles both flags contributes two samples.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from bearings import metrics
from bearings.api.auth import require_auth
from bearings.api.models import MessageOut, MessagePatchBody
from bearings.db import store

router = APIRouter(
    prefix="/messages",
    tags=["messages"],
    dependencies=[Depends(require_auth)],
)


@router.patch("/{message_id}", response_model=MessageOut)
async def patch_message(message_id: str, body: MessagePatchBody, request: Request) -> MessageOut:
    """Update one or both message flags. Returns the refreshed row on
    success, 404 when the id is unknown. A body with every field unset
    returns the current row unchanged."""
    conn = request.app.state.db
    row = await store.update_message_flags(
        conn,
        message_id,
        pinned=body.pinned,
        hidden_from_context=body.hidden_from_context,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="message not found")
    if body.pinned is not None:
        metrics.message_flag_toggles.labels(flag="pinned").inc()
    if body.hidden_from_context is not None:
        metrics.message_flag_toggles.labels(flag="hidden_from_context").inc()
    return MessageOut(**row)
