"""Bulk-session operations — ``POST /api/sessions/bulk``.

Per ``docs/architecture-v1.md`` §1.1.5 and gap-cycle-13-001 this route
replaces the N-independent-HTTP-request pattern the frontend used for
multi-select close / delete / export / tag / untag with a single atomic
server-side call.

Design choices
--------------

* All mutating ops (close, delete, tag, untag) execute in a **single DB
  transaction** with per-ID savepoints so a failure on one ID rolls back
  only that ID's changes without aborting the batch.
* The route writes raw SQL inside the route body (rather than delegating
  to the high-level ``db/`` functions that each call ``connection.commit()``
  internally) so we control the outer commit boundary.
* ``op="export"`` is read-only and shares the ``SessionExport`` schema
  already defined for ``GET /api/sessions/{id}/export`` — one bundle
  object, not N files.
* The HTTP status is always **200** for mutating ops. Callers inspect the
  per-ID ``ok`` fields to detect partial failures. For ``export`` the
  content-type is ``application/json`` with the bundle body.

References
----------

* ``docs/behavior/sessions.md`` §"Bulk operations contract"
* ``bearings.config.constants.KNOWN_BULK_OPS``
* ``bearings.web.models.sessions.BulkSessionsIn`` /
  ``BulkSessionsOut`` / ``BulkExportOut``
"""

from __future__ import annotations

import json
import logging
from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, Response, status

from bearings.config.constants import (
    BULK_OP_CLOSE,
    BULK_OP_DELETE,
    BULK_OP_EXPORT,
    BULK_OP_TAG,
    BULK_OP_UNTAG,
    KNOWN_BULK_OPS,
)
from bearings.db import checkpoints as checkpoints_db
from bearings.db import messages as messages_db
from bearings.db import sdk_entries as sdk_entries_db
from bearings.db import sessions as sessions_db
from bearings.db._id import now_iso
from bearings.web.models.sessions import (
    BulkExportOut,
    BulkResultItem,
    BulkSessionsIn,
    BulkSessionsOut,
    CheckpointExport,
    MessageExport,
    SessionExport,
)
from bearings.web.routes.sessions import _sessions_broadcaster, _to_out
from bearings.web.routes.ws_sessions import SessionsBroadcaster

_LOG = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


async def _build_session_export(db: aiosqlite.Connection, session_id: str) -> SessionExport:
    """Assemble a full :class:`SessionExport` for *session_id*.

    Mirrors the logic in ``routes/sessions.export_session`` without the
    HTTP layer, so the bulk-export path reuses the same schema without
    importing the route function (which would introduce a circular dep).
    """
    row = await sessions_db.get(db, session_id)
    if row is None:
        raise LookupError(session_id)
    paired_parent_title: str | None = None
    if row.kind == "chat" and row.checklist_item_id is not None:
        info = await sessions_db.get_paired_chat_info(db, session_id)
        paired_parent_title = info[0] if info else None
    messages = await messages_db.list_for_session(db, session_id)
    tool_calls = await sdk_entries_db.load(db, session_id=session_id)
    checkpoints = await checkpoints_db.list_for_session(db, session_id)
    return SessionExport(
        session=_to_out(row, paired_parent_title=paired_parent_title),
        messages=[
            MessageExport(
                id=m.id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                executor_model=m.executor_model,
                advisor_model=m.advisor_model,
                effort_level=m.effort_level,
                routing_source=m.routing_source,
                routing_reason=m.routing_reason,
                matched_rule_id=m.matched_rule_id,
                executor_input_tokens=m.executor_input_tokens,
                executor_output_tokens=m.executor_output_tokens,
                advisor_input_tokens=m.advisor_input_tokens,
                advisor_output_tokens=m.advisor_output_tokens,
                advisor_calls_count=m.advisor_calls_count,
                cache_read_tokens=m.cache_read_tokens,
                input_tokens=m.input_tokens,
                output_tokens=m.output_tokens,
                seq=m.seq,
                pinned=m.pinned,
                hidden_from_context=m.hidden_from_context,
            )
            for m in messages
        ],
        tool_calls=tool_calls,
        checkpoints=[
            CheckpointExport(
                id=c.id,
                session_id=c.session_id,
                message_id=c.message_id,
                label=c.label,
                created_at=c.created_at,
            )
            for c in checkpoints
        ],
        attachments=[],
    )


# ---------------------------------------------------------------------------
# Per-op bulk helpers (run inside a single shared transaction)
# ---------------------------------------------------------------------------

_SAVEPOINT = "bulk_item"


async def _bulk_close(
    db: aiosqlite.Connection,
    session_ids: list[str],
) -> list[BulkResultItem]:
    """Close each session; per-ID savepoint isolation."""
    results: list[BulkResultItem] = []
    for sid in session_ids:
        await db.execute(f"SAVEPOINT {_SAVEPOINT}")
        try:
            timestamp = now_iso()
            cursor = await db.execute(
                "UPDATE sessions SET closed_at = ?, updated_at = ? WHERE id = ?",
                (timestamp, timestamp, sid),
            )
            rowcount = cursor.rowcount
            await cursor.close()
            if rowcount == 0:
                await db.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
                await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                results.append(
                    BulkResultItem(
                        session_id=sid,
                        ok=False,
                        detail=f"no session matches {sid!r}",
                    )
                )
            else:
                await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                results.append(BulkResultItem(session_id=sid, ok=True))
        except Exception as exc:
            await db.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            results.append(BulkResultItem(session_id=sid, ok=False, detail=str(exc)))
            _LOG.warning("bulk close failed for %r: %s", sid, exc)
    await db.commit()
    return results


async def _bulk_delete(
    db: aiosqlite.Connection,
    session_ids: list[str],
) -> list[BulkResultItem]:
    """Delete each session (CASCADE); per-ID savepoint isolation."""
    results: list[BulkResultItem] = []
    for sid in session_ids:
        await db.execute(f"SAVEPOINT {_SAVEPOINT}")
        try:
            cursor = await db.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            rowcount = cursor.rowcount
            await cursor.close()
            if rowcount == 0:
                await db.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
                await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                results.append(
                    BulkResultItem(
                        session_id=sid,
                        ok=False,
                        detail=f"no session matches {sid!r}",
                    )
                )
            else:
                await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
                results.append(BulkResultItem(session_id=sid, ok=True))
        except Exception as exc:
            await db.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            results.append(BulkResultItem(session_id=sid, ok=False, detail=str(exc)))
            _LOG.warning("bulk delete failed for %r: %s", sid, exc)
    await db.commit()
    return results


async def _bulk_tag(
    db: aiosqlite.Connection,
    session_ids: list[str],
    tag_id: int,
    *,
    attach: bool,
) -> list[BulkResultItem]:
    """Attach or detach *tag_id* on each session; per-ID savepoint isolation."""
    results: list[BulkResultItem] = []
    timestamp = now_iso()
    for sid in session_ids:
        await db.execute(f"SAVEPOINT {_SAVEPOINT}")
        try:
            if attach:
                cursor = await db.execute(
                    "INSERT OR IGNORE INTO session_tags (session_id, tag_id, created_at)"
                    " VALUES (?, ?, ?)",
                    (sid, tag_id, timestamp),
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM session_tags WHERE session_id = ? AND tag_id = ?",
                    (sid, tag_id),
                )
            await cursor.close()
            await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            results.append(BulkResultItem(session_id=sid, ok=True))
        except Exception as exc:
            await db.execute(f"ROLLBACK TO SAVEPOINT {_SAVEPOINT}")
            await db.execute(f"RELEASE SAVEPOINT {_SAVEPOINT}")
            results.append(BulkResultItem(session_id=sid, ok=False, detail=str(exc)))
            _LOG.warning("bulk tag(attach=%s) failed for %r: %s", attach, sid, exc)
    await db.commit()
    return results


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/api/sessions/bulk")
async def run_sessions_bulk(payload: BulkSessionsIn, request: Request) -> Response:
    """Atomic batch operation across multiple sessions.

    Per ``docs/behavior/sessions.md`` §"Bulk operations contract"
    (gap-cycle-13-001):

    * **close / delete / tag / untag** — executes in a single DB
      transaction with per-ID savepoints; returns
      ``{"op": ..., "results": [{session_id, ok, detail?}, …]}`` with
      HTTP 200. Inspect each ``ok`` field for partial failures.
    * **export** — read-only; returns
      ``{"sessions": [SessionExport|null, …]}`` as
      ``application/json``.  A ``null`` entry means the session was not
      found; callers filter those out before triggering the download.

    ``tag_id`` is required for ``tag`` and ``untag`` ops. Missing
    ``tag_id`` for those ops → 422.

    Unknown ``op`` values → 422. Empty ``session_ids`` → 422 (Pydantic
    enforces ``min_length=1`` on the list field).
    """
    if payload.op not in KNOWN_BULK_OPS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"op {payload.op!r} not in {sorted(KNOWN_BULK_OPS)}",
        )

    db = _db(request)
    broadcaster: SessionsBroadcaster | None = _sessions_broadcaster(request)
    session_ids = payload.session_ids

    # ---- export (read-only; no transaction needed) ---------------------------
    if payload.op == BULK_OP_EXPORT:
        session_exports: list[SessionExport | None] = []
        for sid in session_ids:
            try:
                exp = await _build_session_export(db, sid)
                session_exports.append(exp)
            except LookupError:
                session_exports.append(None)
        bundle = BulkExportOut(sessions=session_exports)
        body = json.dumps(bundle.model_dump(), ensure_ascii=False, indent=2)
        return Response(content=body, media_type="application/json")

    # ---- tag / untag ---------------------------------------------------------
    if payload.op in (BULK_OP_TAG, BULK_OP_UNTAG):
        if payload.tag_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="tag_id is required for tag and untag ops",
            )
        results = await _bulk_tag(
            db,
            session_ids,
            payload.tag_id,
            attach=(payload.op == BULK_OP_TAG),
        )
        out = BulkSessionsOut(op=payload.op, results=results)
        return Response(content=out.model_dump_json(), media_type="application/json")

    # ---- close / delete ------------------------------------------------------
    # Structured as if/elif so both constants are referenced (ruff F401).
    # The KNOWN_BULK_OPS guard above ensures op is "close" or "delete" here.
    if payload.op == BULK_OP_CLOSE:
        results = await _bulk_close(db, session_ids)
        # Broadcast upserts so the sidebar refreshes on all open tabs.
        if broadcaster is not None:
            for r in results:
                if r.ok:
                    row = await sessions_db.get(db, r.session_id)
                    if row is not None:
                        broadcaster.publish_upsert(_to_out(row))
    elif payload.op == BULK_OP_DELETE:
        results = await _bulk_delete(db, session_ids)
        if broadcaster is not None:
            for r in results:
                if r.ok:
                    broadcaster.publish_delete(r.session_id)
    else:  # pragma: no cover — KNOWN_BULK_OPS guard rejects all other values
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"unhandled op {payload.op!r}",
        )
    out = BulkSessionsOut(op=payload.op, results=results)
    return Response(content=out.model_dump_json(), media_type="application/json")


__all__ = ["router"]
