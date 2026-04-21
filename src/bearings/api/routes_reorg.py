"""Session reorg routes — move / split message rows between sessions.

Slice 2 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`). Composes the Slice 1
`store.move_messages_tx` primitive into two user-facing ops:

- `POST /sessions/{id}/reorg/move` — cherry-pick specific message ids
  from the source into an existing target session.
- `POST /sessions/{id}/reorg/split` — anchor on a message id and move
  everything chronologically after it into a newly-created session
  (defaults for `model` / `working_dir` copy from the source).

Both routes stop any live runner on the affected sessions so the SDK's
in-memory context rebuilds against the new DB state on the next turn
(v0.3.15 priming is the belt). Tool-call-group warnings are deferred
to Slice 7; the response shape carries an empty `warnings` list so
the later addition is non-breaking.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from bearings.api.auth import require_auth
from bearings.api.models import (
    ReorgMoveRequest,
    ReorgMoveResult,
    ReorgSplitRequest,
    ReorgSplitResult,
    SessionOut,
)
from bearings.db import store

router = APIRouter(
    prefix="/sessions",
    tags=["reorg"],
    dependencies=[Depends(require_auth)],
)


async def _stop_runner_if_live(app_state: Any, session_id: str) -> None:
    """Best-effort: if a runner exists for `session_id`, request a stop
    so the next turn rebuilds against the new DB state. No-op when the
    registry is absent (non-lifespan test apps) or the runner is idle
    — `request_stop` itself no-ops when nothing's in flight.
    """
    runners = getattr(app_state, "runners", None)
    if runners is None:
        return
    runner = runners.get(session_id)
    if runner is None:
        return
    await runner.request_stop()


@router.post("/{session_id}/reorg/move", response_model=ReorgMoveResult)
async def reorg_move(
    session_id: str,
    body: ReorgMoveRequest,
    request: Request,
) -> ReorgMoveResult:
    conn = request.app.state.db
    if not body.message_ids:
        raise HTTPException(status_code=400, detail="message_ids must be non-empty")
    if session_id == body.target_session_id:
        raise HTTPException(status_code=400, detail="source and target sessions must differ")
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="source session not found")
    if await store.get_session(conn, body.target_session_id) is None:
        raise HTTPException(status_code=404, detail="target session not found")

    result = await store.move_messages_tx(
        conn,
        source_id=session_id,
        target_id=body.target_session_id,
        message_ids=body.message_ids,
    )
    await _stop_runner_if_live(request.app.state, session_id)
    await _stop_runner_if_live(request.app.state, body.target_session_id)

    return ReorgMoveResult(
        moved=result.moved,
        tool_calls_followed=result.tool_calls_followed,
        warnings=[],
    )


@router.post(
    "/{session_id}/reorg/split",
    response_model=ReorgSplitResult,
    status_code=201,
)
async def reorg_split(
    session_id: str,
    body: ReorgSplitRequest,
    request: Request,
) -> ReorgSplitResult:
    conn = request.app.state.db
    source = await store.get_session(conn, session_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source session not found")
    if not body.new_session.tag_ids:
        raise HTTPException(
            status_code=400,
            detail="at least one tag_id is required (sessions must be tagged)",
        )
    for tag_id in body.new_session.tag_ids:
        if await store.get_tag(conn, tag_id) is None:
            raise HTTPException(status_code=400, detail=f"tag_id {tag_id} does not exist")

    all_messages = await store.list_messages(conn, session_id)
    anchor_index = next(
        (i for i, m in enumerate(all_messages) if m["id"] == body.after_message_id),
        None,
    )
    if anchor_index is None:
        raise HTTPException(
            status_code=404,
            detail=f"after_message_id {body.after_message_id!r} not in session",
        )
    moved_ids = [m["id"] for m in all_messages[anchor_index + 1 :]]
    if not moved_ids:
        raise HTTPException(status_code=400, detail="no messages after the anchor to split")

    new_row = await store.create_session(
        conn,
        working_dir=body.new_session.working_dir or source["working_dir"],
        model=body.new_session.model or source["model"],
        title=body.new_session.title,
        description=body.new_session.description,
    )
    for tag_id in body.new_session.tag_ids:
        await store.attach_tag(conn, new_row["id"], tag_id)

    move_result = await store.move_messages_tx(
        conn,
        source_id=session_id,
        target_id=new_row["id"],
        message_ids=moved_ids,
    )
    # Only the source can have a live runner — the new session id is
    # one we just created, so no runner exists for it yet.
    await _stop_runner_if_live(request.app.state, session_id)

    refreshed = await store.get_session(conn, new_row["id"])
    assert refreshed is not None
    return ReorgSplitResult(
        session=SessionOut(**refreshed),
        result=ReorgMoveResult(
            moved=move_result.moved,
            tool_calls_followed=move_result.tool_calls_followed,
            warnings=[],
        ),
    )
