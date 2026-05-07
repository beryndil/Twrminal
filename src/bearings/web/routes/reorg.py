"""Reorg REST endpoints (gap-cycle-03-008/009).

Per ``docs/architecture-v1.md`` §1.1.5 this module owns:

* ``POST /api/sessions/{src_id}/reorg/merge?target={dst_id}`` — merge
  ``src_id`` into ``dst_id`` in a single atomic transaction. Re-parents
  all messages from the source to the destination (preserving
  ``created_at`` order), writes a ``reorg_audit`` row, then deletes the
  source session. Returns 200 with the :class:`ReorgAuditOut` envelope.
* ``GET /api/sessions/{id}/reorg/audits`` — list all merge audit rows
  for the destination session ``id``, oldest-first. Used by the
  frontend to hydrate dividers on initial conversation load.
* ``DELETE /api/sessions/{id}/reorg/audits/{audit_id}`` — atomically
  reverse a merge and remove the audit row. Returns 200 with the id of
  the newly created source session, 404 when the audit row is absent,
  or 409 when the destination session has been mutated since the merge.

Error responses for merge:

* 409 when ``src_id == dst_id`` (self-merge is not permitted).
* 404 when either session does not exist.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.db import reorg as reorg_db
from bearings.web.models.reorg import ReorgAuditListOut, ReorgAuditOut, UndoMergeOut

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state`` (503 if absent)."""
    conn: aiosqlite.Connection | None = getattr(request.app.state, "db_connection", None)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database not available",
        )
    return conn


def _to_out(audit: reorg_db.ReorgAudit) -> ReorgAuditOut:
    return ReorgAuditOut(
        id=audit.id,
        dst_session_id=audit.dst_session_id,
        src_session_id=audit.src_session_id,
        merged_at=audit.merged_at,
        src_title=audit.src_title,
        boundary_msg_id=audit.boundary_msg_id,
    )


@router.post(
    "/api/sessions/{src_id}/reorg/merge",
    response_model=ReorgAuditOut,
    status_code=status.HTTP_200_OK,
)
async def merge_session(
    src_id: str,
    request: Request,
    target: str = Query(..., description="Destination session id to merge into"),
) -> ReorgAuditOut:
    """Merge ``src_id`` into ``target`` in one atomic transaction.

    Re-parents every message from the source session to the destination,
    writes a ``reorg_audit`` row (carrying the id of the first
    re-parented message as ``boundary_msg_id``), then deletes the source
    session. Cascade deletes clean up the source's checkpoints, tags,
    sdk_session_entries, and other FK-linked rows.

    Returns 200 with the audit row on success.
    Returns 409 when ``src_id == target`` (self-merge).
    Returns 404 when either session does not exist.
    """
    if src_id == target:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="src and target session ids must differ (self-merge is not permitted)",
        )
    db = _db(request)
    result = await reorg_db.merge_sessions(db, src_id, target)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"one or both sessions not found: src={src_id!r} target={target!r}",
        )
    return _to_out(result)


@router.get(
    "/api/sessions/{dst_id}/reorg/audits",
    response_model=ReorgAuditListOut,
    status_code=status.HTTP_200_OK,
)
async def list_reorg_audits(
    dst_id: str,
    request: Request,
) -> ReorgAuditListOut:
    """Return all merge audit rows for ``dst_id``, oldest-first.

    Used by the frontend on conversation load to hydrate persistent
    divider rows.  Returns an empty list when no merges have been made
    into this session.
    """
    db = _db(request)
    rows = await reorg_db.list_audit_for_session(db, dst_id)
    return ReorgAuditListOut(items=[_to_out(r) for r in rows])


@router.delete(
    "/api/sessions/{dst_id}/reorg/audits/{audit_id}",
    response_model=UndoMergeOut,
    status_code=status.HTTP_200_OK,
)
async def undo_reorg_audit(
    dst_id: str,
    audit_id: str,
    request: Request,
) -> UndoMergeOut:
    """Atomically reverse a merge and delete the audit row.

    Re-creates the source session with its original title, moves the
    merged messages back, updates message counts on both sessions, and
    removes the audit row — all inside a single transaction.

    Returns 200 with ``new_session_id`` on success.
    Returns 404 when ``audit_id`` is absent or does not belong to ``dst_id``.
    Returns 409 when messages have been added to ``dst_id`` after the merge,
    or when the boundary message has been moved away.
    """
    db = _db(request)
    try:
        new_session_id = await reorg_db.undo_merge_audit(db, audit_id, dst_id)
    except reorg_db.StaleAuditError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if new_session_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"reorg audit not found: {audit_id!r} for session {dst_id!r}",
        )
    return UndoMergeOut(new_session_id=new_session_id)


__all__ = ["router"]
