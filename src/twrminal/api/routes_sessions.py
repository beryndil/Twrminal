from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from twrminal import metrics
from twrminal.api.auth import require_auth
from twrminal.api.models import (
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    ToolCallOut,
)
from twrminal.db import store

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    dependencies=[Depends(require_auth)],
)


@router.post("", response_model=SessionOut)
async def create_session(body: SessionCreate, request: Request) -> SessionOut:
    row = await store.create_session(
        request.app.state.db,
        working_dir=body.working_dir,
        model=body.model,
        title=body.title,
        max_budget_usd=body.max_budget_usd,
    )
    metrics.sessions_created.inc()
    return SessionOut(**row)


@router.get("", response_model=list[SessionOut])
async def list_sessions(request: Request) -> list[SessionOut]:
    rows = await store.list_sessions(request.app.state.db)
    return [SessionOut(**r) for r in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, request: Request) -> SessionOut:
    row = await store.get_session(request.app.state.db, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionOut(**row)


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(session_id: str, body: SessionUpdate, request: Request) -> SessionOut:
    # Only fields the client explicitly set are applied — unset fields
    # leave the column untouched, explicit null clears it.
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    row = await store.update_session(request.app.state.db, session_id, fields=fields)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionOut(**row)


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict[str, bool]:
    ok = await store.delete_session(request.app.state.db, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": True}


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: str,
    request: Request,
    before: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=500),
) -> list[MessageOut]:
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_messages(conn, session_id, before=before, limit=limit)
    return [MessageOut(**r) for r in rows]


@router.get("/{session_id}/tool_calls", response_model=list[ToolCallOut])
async def list_tool_calls(session_id: str, request: Request) -> list[ToolCallOut]:
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_tool_calls(conn, session_id)
    return [ToolCallOut(**r) for r in rows]
