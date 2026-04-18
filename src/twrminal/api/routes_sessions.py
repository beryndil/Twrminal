from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from twrminal.api.models import MessageOut, SessionCreate, SessionOut
from twrminal.db import store

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionOut)
async def create_session(body: SessionCreate, request: Request) -> SessionOut:
    row = await store.create_session(
        request.app.state.db,
        working_dir=body.working_dir,
        model=body.model,
        title=body.title,
    )
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


@router.delete("/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict[str, bool]:
    ok = await store.delete_session(request.app.state.db, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": True}


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session_id: str, request: Request) -> list[MessageOut]:
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_messages(conn, session_id)
    return [MessageOut(**r) for r in rows]
