"""Session reorg routes — move / split / merge message rows between
sessions, plus the audit-trail read + undo plumbing.

Slice 2 of the Session Reorg plan
(`~/.claude/plans/sparkling-triaging-otter.md`) added move + split;
Slice 5 adds merge and the persistent audit surface rendered as
inline dividers in the source conversation. All three write-ops
record a `reorg_audits` row on success; `DELETE /reorg/audits/{id}`
lets the 30s undo window remove the divider when the inverse op
runs. Past the undo window the row stays as audit trail.

Every route stops any live runner on the affected sessions so the
SDK's in-memory context rebuilds against the new DB state on the
next turn (v0.3.15 priming is the belt).

Slice 7 wired in tool-call-group warnings (via
`store.detect_tool_call_group_warnings`) and a
`bearings_session_reorg_total{op}` Prometheus counter. Warnings are
advisory — the op still runs, the UI surfaces them. Merge never
produces group-split warnings because it moves every source row
together, preserving chronology.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from bearings.api.auth import require_auth
from bearings.api.models import (
    ReorgAuditOut,
    ReorgMergeRequest,
    ReorgMergeResult,
    ReorgMoveRequest,
    ReorgMoveResult,
    ReorgSplitRequest,
    ReorgSplitResult,
    ReorgWarning,
    SessionOut,
)
from bearings.db import store
from bearings.metrics import session_reorg_total

router = APIRouter(
    prefix="/sessions",
    tags=["reorg"],
    dependencies=[Depends(require_auth)],
)


def _require_chat_kind(row: dict[str, Any] | None, *, role: str) -> None:
    """v0.4.0 reorg guard. Move/split/merge semantics are defined over
    message rows, which only exist on chat sessions. Reject with 400
    (not 404) so the caller can tell "wrong session kind" from "no
    such session". `role` is e.g. 'source' / 'target' so the message
    points at the offending side."""
    if row is None:
        return  # missing-row check happens at the call site; stay single-purpose here.
    if row.get("kind", "chat") != "chat":
        raise HTTPException(
            status_code=400,
            detail=f"reorg requires chat sessions ({role} kind={row.get('kind')!r})",
        )


def _target_title(row: dict[str, Any] | None) -> str | None:
    """Snapshot the target title for the audit row. Falls through to
    `None` for untitled sessions so the UI can render '(untitled)' in
    one place rather than splattering that fallback across the DB."""
    if row is None:
        return None
    title = row.get("title")
    return str(title) if title is not None else None


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


async def _detect_warnings(
    conn: Any,
    source_id: str,
    moved_ids: list[str],
) -> list[ReorgWarning]:
    """Gather tool-call-group-split warnings for a proposed move.

    Pure read against the source session's current state — safe to
    call before or after the move since it only compares message ids.
    We call it before so the warning reflects *what was asked for*,
    not what landed (idempotent re-moves would otherwise silently
    show an empty list).
    """
    msgs = await store.list_messages(conn, source_id)
    calls = await store.list_tool_calls(conn, source_id)
    raw = store.detect_tool_call_group_warnings(msgs, calls, moved_ids)
    return [ReorgWarning(**w) for w in raw]


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
    source = await store.get_session(conn, session_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source session not found")
    target = await store.get_session(conn, body.target_session_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target session not found")
    _require_chat_kind(source, role="source")
    _require_chat_kind(target, role="target")

    # Detect tool-call-group splits BEFORE the move so the source
    # still has both halves of any affected pair — otherwise the
    # pair's already partly on the target and the scan can't see it.
    warnings = await _detect_warnings(conn, session_id, body.message_ids)

    result = await store.move_messages_tx(
        conn,
        source_id=session_id,
        target_id=body.target_session_id,
        message_ids=body.message_ids,
    )
    # Audit rows are written only when at least one message actually
    # moved — an idempotent re-run with zero moves leaves no divider.
    audit_id: int | None = None
    if result.moved > 0:
        audit_id = await store.record_reorg_audit(
            conn,
            source_session_id=session_id,
            target_session_id=body.target_session_id,
            target_title_snapshot=_target_title(target),
            message_count=result.moved,
            op="move",
        )
        await conn.commit()
        session_reorg_total.labels(op="move").inc()
        # v0.3.25: work resumed — clear the closed flag on either side
        # that was closed. Both sessions are candidates; the helper
        # no-ops on open rows.
        await store.reopen_if_closed(conn, session_id, body.target_session_id)
    await _stop_runner_if_live(request.app.state, session_id)
    await _stop_runner_if_live(request.app.state, body.target_session_id)

    return ReorgMoveResult(
        moved=result.moved,
        tool_calls_followed=result.tool_calls_followed,
        warnings=warnings,
        audit_id=audit_id,
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
    _require_chat_kind(source, role="source")
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

    # Warning scan against the pre-split source — the proposed moved
    # set is the post-anchor tail, any tool-call pair that straddles
    # the anchor boundary is the one we flag.
    source_calls = await store.list_tool_calls(conn, session_id)
    raw_warnings = store.detect_tool_call_group_warnings(all_messages, source_calls, moved_ids)
    warnings = [ReorgWarning(**w) for w in raw_warnings]

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
    audit_id: int | None = None
    if move_result.moved > 0:
        audit_id = await store.record_reorg_audit(
            conn,
            source_session_id=session_id,
            target_session_id=new_row["id"],
            target_title_snapshot=body.new_session.title,
            message_count=move_result.moved,
            op="split",
        )
        await conn.commit()
        session_reorg_total.labels(op="split").inc()
        # v0.3.25: splitting *off* a closed session means the user is
        # actively reworking it — reopen so the flag isn't stale. The
        # newly-created target is open by default.
        await store.reopen_if_closed(conn, session_id)
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
            warnings=warnings,
            audit_id=audit_id,
        ),
    )


@router.post("/{session_id}/reorg/merge", response_model=ReorgMergeResult)
async def reorg_merge(
    session_id: str,
    body: ReorgMergeRequest,
    request: Request,
) -> ReorgMergeResult:
    """Move every message on `session_id` into `target_session_id`,
    optionally dropping the source. Merging an empty source is a
    no-op (moves 0, deletes nothing). `delete_source=True` is applied
    after the move so the cascade doesn't take the target's rows
    too — `ON DELETE CASCADE` on `messages.session_id` would otherwise
    drop the freshly-moved rows along with the source.
    """
    conn = request.app.state.db
    if session_id == body.target_session_id:
        raise HTTPException(status_code=400, detail="source and target sessions must differ")
    source = await store.get_session(conn, session_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source session not found")
    target = await store.get_session(conn, body.target_session_id)
    if target is None:
        raise HTTPException(status_code=404, detail="target session not found")
    _require_chat_kind(source, role="source")
    _require_chat_kind(target, role="target")

    rows = await store.list_messages(conn, session_id)
    message_ids = [r["id"] for r in rows]
    if not message_ids:
        # Nothing to move, no audit row, no runner bump. Still honor
        # `delete_source` — merging an empty session to clear it out
        # of the sidebar is a legitimate request.
        deleted = False
        if body.delete_source:
            await store.delete_session(conn, session_id)
            deleted = True
        return ReorgMergeResult(
            moved=0,
            tool_calls_followed=0,
            warnings=[],
            deleted_source=deleted,
        )

    result = await store.move_messages_tx(
        conn,
        source_id=session_id,
        target_id=body.target_session_id,
        message_ids=message_ids,
    )
    audit_id: int | None = None
    deleted = False
    if result.moved > 0 and not body.delete_source:
        # Only record the audit when the source survives — a deleted
        # source has nowhere to render the divider, and the cascade
        # would have dropped the row anyway.
        audit_id = await store.record_reorg_audit(
            conn,
            source_session_id=session_id,
            target_session_id=body.target_session_id,
            target_title_snapshot=_target_title(target),
            message_count=result.moved,
            op="merge",
        )
        await conn.commit()
    if body.delete_source:
        await store.delete_session(conn, session_id)
        deleted = True

    if result.moved > 0:
        session_reorg_total.labels(op="merge").inc()
        # v0.3.25: merging messages into a closed target reopens it
        # (charter being amended). Skip the source when it was just
        # deleted — no row to update.
        candidates: tuple[str, ...] = (
            (body.target_session_id,) if deleted else (session_id, body.target_session_id)
        )
        await store.reopen_if_closed(conn, *candidates)

    await _stop_runner_if_live(request.app.state, session_id)
    await _stop_runner_if_live(request.app.state, body.target_session_id)

    # Merge moves every source row together, so it cannot create a
    # group split — both halves of any pre-existing pair ride the
    # same boundary. Warnings intentionally left empty.
    return ReorgMergeResult(
        moved=result.moved,
        tool_calls_followed=result.tool_calls_followed,
        warnings=[],
        audit_id=audit_id,
        deleted_source=deleted,
    )


@router.get(
    "/{session_id}/reorg/audits",
    response_model=list[ReorgAuditOut],
)
async def list_reorg_audits(
    session_id: str,
    request: Request,
) -> list[ReorgAuditOut]:
    """Return every audit divider attached to `session_id`, oldest
    first. 404 when the session itself is gone so the caller doesn't
    silently paper over a stale id."""
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_reorg_audits(conn, session_id)
    return [ReorgAuditOut(**row) for row in rows]


@router.delete(
    "/{session_id}/reorg/audits/{audit_id}",
    status_code=204,
)
async def delete_reorg_audit(
    session_id: str,
    audit_id: int,
    request: Request,
) -> None:
    """Used by the undo path to remove a divider for an op that was
    cancelled inside the 30s window. Returns 204 on success, 404 when
    the row is already gone or belongs to a different session. The
    session-id guard means a stale URL can't delete audits belonging
    to an unrelated session."""
    conn = request.app.state.db
    async with conn.execute(
        "SELECT source_session_id FROM reorg_audits WHERE id = ?",
        (audit_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or row["source_session_id"] != session_id:
        raise HTTPException(status_code=404, detail="audit row not found")
    await store.delete_reorg_audit(conn, audit_id)
    return None
