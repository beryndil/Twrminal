"""Reorg REST endpoints (gap-cycle-03-008).

Per ``docs/architecture-v1.md`` §1.1.5 this module owns:

* ``POST /api/sessions/{src_id}/reorg/merge?target={dst_id}`` — merge
  ``src_id`` into ``dst_id`` in a single atomic transaction. Re-parents
  all messages from the source to the destination (preserving
  ``created_at`` order), writes a ``reorg_audit`` row, then deletes the
  source session. Returns 200 with the :class:`ReorgAuditOut` envelope.

Error responses:

* 409 when ``src_id == dst_id`` (self-merge is not permitted).
* 404 when either session does not exist.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.db import reorg as reorg_db
from bearings.web.models.reorg import ReorgAuditOut

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


__all__ = ["router"]
