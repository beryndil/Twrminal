from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from twrminal import metrics
from twrminal.agent.prompt import assemble_prompt, estimate_tokens
from twrminal.api.auth import require_auth
from twrminal.api.models import (
    MessageOut,
    SessionCreate,
    SessionOut,
    SessionUpdate,
    SystemPromptLayerOut,
    SystemPromptOut,
    TagOut,
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
    # v0.2.13: require ≥1 tag on every externally-created session.
    # Tags carry the project-like defaults + memories, so a tag-less
    # session has no context hooks at all — guard rail against that.
    if not body.tag_ids:
        raise HTTPException(
            status_code=400,
            detail="at least one tag_id is required (sessions must be tagged)",
        )
    conn = request.app.state.db
    # Validate every tag exists before inserting the session — avoids a
    # partial state where the session row is created but some tags fail
    # to attach.
    for tag_id in body.tag_ids:
        if await store.get_tag(conn, tag_id) is None:
            raise HTTPException(status_code=400, detail=f"tag_id {tag_id} does not exist")
    row = await store.create_session(
        conn,
        working_dir=body.working_dir,
        model=body.model,
        title=body.title,
        description=body.description,
        max_budget_usd=body.max_budget_usd,
    )
    for tag_id in body.tag_ids:
        await store.attach_tag(conn, row["id"], tag_id)
    metrics.sessions_created.inc()
    # Re-fetch so the returned row carries any updated_at bump from
    # the attach step, for frontend sort consistency.
    refreshed = await store.get_session(conn, row["id"])
    assert refreshed is not None
    return SessionOut(**refreshed)


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    tags: str | None = Query(None, description="Comma-separated tag ids"),
    mode: str = Query("any", pattern="^(any|all)$"),
) -> list[SessionOut]:
    tag_ids: list[int] | None = None
    if tags:
        try:
            tag_ids = [int(t) for t in tags.split(",") if t.strip()]
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="tags must be comma-separated integers"
            ) from exc
    rows = await store.list_sessions(
        request.app.state.db,
        tag_ids=tag_ids,
        mode=mode,
    )
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


@router.post("/import", response_model=SessionOut)
async def import_session(payload: dict[str, Any], request: Request) -> SessionOut:
    """Restore a session from the v0.1.30 export shape. Generates new
    ids so the import can land next to an existing session with the
    same original id. Sibling of the per-session /export endpoint."""
    if not isinstance(payload.get("session"), dict):
        raise HTTPException(status_code=400, detail="missing or malformed `session` object")
    row = await store.import_session(request.app.state.db, payload)
    metrics.sessions_created.inc()
    return SessionOut(**row)


@router.get("/{session_id}/export")
async def export_session(session_id: str, request: Request) -> dict[str, Any]:
    """Single-session dump — session metadata + every message and
    tool call. Keeps the `/api/history/export` shape-per-section but
    scoped to one session so users can archive a finished
    conversation as a standalone JSON file."""
    conn = request.app.state.db
    session = await store.get_session(conn, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    messages = await store.list_messages(conn, session_id)
    tool_calls = await store.list_tool_calls(conn, session_id)
    return {
        "session": session,
        "messages": messages,
        "tool_calls": tool_calls,
    }


@router.get("/{session_id}/tags", response_model=list[TagOut])
async def list_session_tags(session_id: str, request: Request) -> list[TagOut]:
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_session_tags(conn, session_id)
    return [TagOut(**r) for r in rows]


@router.get("/{session_id}/system_prompt", response_model=SystemPromptOut)
async def get_session_system_prompt(session_id: str, request: Request) -> SystemPromptOut:
    """Inspect the layered system prompt that would be sent to the SDK on
    the next turn. Read-only — calls the same `assemble_prompt` the
    agent uses so what you see here is what the model sees."""
    conn = request.app.state.db
    if await store.get_session(conn, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    assembled = await assemble_prompt(conn, session_id)
    layers = [
        SystemPromptLayerOut(
            name=layer.name,
            kind=layer.kind,
            content=layer.content,
            token_count=estimate_tokens(layer.content),
        )
        for layer in assembled.layers
    ]
    return SystemPromptOut(
        layers=layers,
        total_tokens=sum(layer.token_count for layer in layers),
    )


@router.post("/{session_id}/tags/{tag_id}", response_model=list[TagOut])
async def attach_session_tag(session_id: str, tag_id: int, request: Request) -> list[TagOut]:
    conn = request.app.state.db
    ok = await store.attach_tag(conn, session_id, tag_id)
    if not ok:
        # attach_tag returns False when either the session or the tag
        # doesn't exist — both map to 404 from the client's view.
        if await store.get_session(conn, session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        raise HTTPException(status_code=404, detail="tag not found")
    rows = await store.list_session_tags(conn, session_id)
    return [TagOut(**r) for r in rows]


@router.delete("/{session_id}/tags/{tag_id}", response_model=list[TagOut])
async def detach_session_tag(session_id: str, tag_id: int, request: Request) -> list[TagOut]:
    conn = request.app.state.db
    ok = await store.detach_tag(conn, session_id, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    rows = await store.list_session_tags(conn, session_id)
    return [TagOut(**r) for r in rows]
