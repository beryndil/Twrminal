"""Checklist API surface. Mounted at `/api` with an internal prefix
of `/sessions/{session_id}/checklist` so URLs read
`/api/sessions/{id}/checklist/items`. Every endpoint validates that
the parent session exists and has `kind == 'checklist'` — chat
sessions can't carry checklist bodies, and the 404/400 split tells
a curl user exactly what went wrong.

Shape mirrors `routes_tags.py`: thin handlers, `store` does the
work, `HTTPException(404)` on missing parent, no business logic
inlined here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from bearings import metrics
from bearings.agent.auto_driver import DriverConfig
from bearings.api.auth import require_auth
from bearings.api.models import (
    AutoRunStart,
    AutoRunStatus,
    ChecklistOut,
    ChecklistUpdate,
    ItemCreate,
    ItemOut,
    ItemToggle,
    ItemUpdate,
    PairedChatCreate,
    ReorderRequest,
    ReorderResult,
    SessionOut,
)
from bearings.db import store

router = APIRouter(
    prefix="/sessions/{session_id}/checklist",
    tags=["checklists"],
    dependencies=[Depends(require_auth)],
)


async def _require_checklist_session(request: Request, session_id: str) -> None:
    """Resolve the session row and reject anything that isn't a
    checklist. A missing session returns 404; a chat session returns
    400 so the client can distinguish a typo from a kind mismatch."""
    session = await store.get_session(request.app.state.db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session["kind"] != "checklist":
        raise HTTPException(status_code=400, detail="session is not a checklist session")


@router.get("", response_model=ChecklistOut)
async def get_checklist(session_id: str, request: Request) -> ChecklistOut:
    await _require_checklist_session(request, session_id)
    row = await store.get_checklist(request.app.state.db, session_id)
    if row is None:
        # The session exists and is a checklist-kind, but the
        # companion row is missing. Normally POST /sessions creates
        # both atomically; a missing body here means the create path
        # failed partway through and the user should re-issue.
        raise HTTPException(status_code=404, detail="checklist not found")
    return ChecklistOut(**row)


@router.patch("", response_model=ChecklistOut)
async def update_checklist(
    session_id: str, body: ChecklistUpdate, request: Request
) -> ChecklistOut:
    await _require_checklist_session(request, session_id)
    # Only fields the client explicitly set are applied — mirrors the
    # SessionUpdate / TagUpdate pattern.
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    row = await store.update_checklist(request.app.state.db, session_id, fields=fields)
    if row is None:
        raise HTTPException(status_code=404, detail="checklist not found")
    return ChecklistOut(**row)


@router.post("/items", response_model=ItemOut, status_code=201)
async def create_item(session_id: str, body: ItemCreate, request: Request) -> ItemOut:
    await _require_checklist_session(request, session_id)
    row = await store.create_item(
        request.app.state.db,
        session_id,
        label=body.label,
        notes=body.notes,
        parent_item_id=body.parent_item_id,
        sort_order=body.sort_order,
    )
    if row is None:
        # `create_item` returns None only when the parent checklist
        # doesn't exist — but `_require_checklist_session` already
        # guaranteed the session row; a missing checklist body here
        # points at the same partial-create case as GET.
        raise HTTPException(status_code=404, detail="checklist not found")
    return ItemOut(**row)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(session_id: str, item_id: int, body: ItemUpdate, request: Request) -> ItemOut:
    await _require_checklist_session(request, session_id)
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    row = await store.update_item(request.app.state.db, item_id, fields=fields)
    if row is None:
        raise HTTPException(status_code=404, detail="item not found")
    # Defense in depth: the item id is global across checklists so
    # reject when the hit doesn't belong to this session.
    if row["checklist_id"] != session_id:
        raise HTTPException(status_code=404, detail="item not found")
    return ItemOut(**row)


@router.post("/items/{item_id}/toggle", response_model=ItemOut)
async def toggle_item(session_id: str, item_id: int, body: ItemToggle, request: Request) -> ItemOut:
    await _require_checklist_session(request, session_id)
    conn = request.app.state.db
    existing = await store.get_item(conn, item_id)
    if existing is None or existing["checklist_id"] != session_id:
        raise HTTPException(status_code=404, detail="item not found")
    row = await store.toggle_item(conn, item_id, checked=body.checked)
    if row is None:
        # Race: item was deleted between the check and the toggle.
        raise HTTPException(status_code=404, detail="item not found")
    # Slice 4.1: if the cascade just completed the checklist, close
    # the parent session. One-directional — unchecking never reopens.
    if body.checked and await store.is_checklist_complete(conn, session_id):
        await store.close_session(conn, session_id)
    return ItemOut(**row)


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(session_id: str, item_id: int, request: Request) -> Response:
    await _require_checklist_session(request, session_id)
    existing = await store.get_item(request.app.state.db, item_id)
    if existing is None or existing["checklist_id"] != session_id:
        raise HTTPException(status_code=404, detail="item not found")
    ok = await store.delete_item(request.app.state.db, item_id)
    if not ok:
        # Race with a concurrent delete — idempotent 204 instead would
        # hide the race; prefer 404 so the client retries on its own.
        raise HTTPException(status_code=404, detail="item not found")
    return Response(status_code=204)


@router.post("/reorder", response_model=ReorderResult)
async def reorder_items(session_id: str, body: ReorderRequest, request: Request) -> ReorderResult:
    await _require_checklist_session(request, session_id)
    reordered = await store.reorder_items(request.app.state.db, session_id, body.item_ids)
    return ReorderResult(reordered=reordered)


@router.get("/items/{item_id}/chat", response_model=SessionOut)
async def get_paired_chat(session_id: str, item_id: int, request: Request) -> SessionOut:
    """Resolve the paired chat for an item, or 404 if the item has
    never been worked on in a chat. The ChecklistView uses this when
    the user clicks a "Continue working" button on an already-paired
    item — the button state comes from `ItemOut.chat_session_id` so
    we could short-circuit client-side, but keeping a resolve
    endpoint means the server stays authoritative if a race drops
    the pairing."""
    await _require_checklist_session(request, session_id)
    conn = request.app.state.db
    item = await store.get_item(conn, item_id)
    if item is None or item["checklist_id"] != session_id:
        raise HTTPException(status_code=404, detail="item not found")
    chat_id = item["chat_session_id"]
    if chat_id is None:
        raise HTTPException(status_code=404, detail="no paired chat for this item")
    chat_row = await store.get_session(conn, chat_id)
    if chat_row is None:
        # Pairing FK is SET NULL on chat delete, but a race between
        # DELETE and GET can hand a stale id back. Surface as 404 and
        # let the client re-fetch the item so the next click spawns
        # a fresh paired chat.
        raise HTTPException(status_code=404, detail="paired chat session is gone")
    return SessionOut(**chat_row)


@router.post("/items/{item_id}/chat", response_model=SessionOut, status_code=201)
async def spawn_paired_chat(
    session_id: str, item_id: int, body: PairedChatCreate, request: Request
) -> SessionOut:
    """Spawn a new chat session paired to a checklist item. Inherits
    defaults (working_dir, model, tags) from the parent checklist
    session when the client doesn't override them — the typical
    workflow is "click Work on this, get a chat pre-wired to the
    same project context." If the item already has a paired chat the
    existing session is returned unchanged (idempotent spawn — the
    UI routes to /chat and the first spawn wins); callers that need
    a fresh chat must delete the old one first.

    Raises 404 on unknown session or item, 400 when the parent is
    not a checklist session, 400 when the parent carries no tags
    (since every session requires ≥1 tag and defaults from the
    parent means we must have *something* to attach)."""
    await _require_checklist_session(request, session_id)
    conn = request.app.state.db
    item = await store.get_item(conn, item_id)
    if item is None or item["checklist_id"] != session_id:
        raise HTTPException(status_code=404, detail="item not found")
    existing_chat_id = item["chat_session_id"]
    if existing_chat_id is not None:
        # Idempotent: return the existing pairing so a double-click
        # doesn't create dangling chats. The frontend navigates on
        # success; second click lands on the same session.
        existing = await store.get_session(conn, existing_chat_id)
        if existing is not None:
            return SessionOut(**existing)
        # Existing pointer is stale (chat deleted mid-flight, FK
        # should have nulled but we raced). Fall through and spawn
        # a fresh one — clear the stale pointer so the INSERT below
        # doesn't trip the UNIQUE-ish semantics we rely on at the UI.
        await store.set_item_chat_session(conn, item_id, None)

    parent_session = await store.get_session(conn, session_id)
    assert parent_session is not None  # _require_checklist_session checked
    parent_tags = await store.list_session_tags(conn, session_id)
    if not parent_tags and not body.tag_ids:
        # Every session requires ≥1 tag (v0.2.13). The parent
        # checklist is supposed to be tagged; if it isn't (imported
        # from a pre-v0.2.13 export, say) the client must pass tags.
        raise HTTPException(
            status_code=400,
            detail="parent checklist has no tags and no tag_ids supplied",
        )
    effective_tag_ids = body.tag_ids or [t["id"] for t in parent_tags]
    # Validate every tag exists before inserting — matches routes_sessions.
    for tag_id in effective_tag_ids:
        if await store.get_tag(conn, tag_id) is None:
            raise HTTPException(status_code=400, detail=f"tag_id {tag_id} does not exist")

    working_dir = body.working_dir or parent_session["working_dir"]
    model = body.model or parent_session["model"]
    title = body.title if body.title is not None else f"{item['label']}"
    # Apply the global default cap when the caller didn't specify —
    # same fallback as `/api/sessions` POST (security audit §7).
    budget = body.max_budget_usd
    if budget is None:
        budget = request.app.state.settings.agent.default_max_budget_usd

    chat_row = await store.create_session(
        conn,
        working_dir=working_dir,
        model=model,
        title=title,
        description=body.description,
        max_budget_usd=budget,
        kind="chat",
        checklist_item_id=item_id,
    )
    for tag_id in effective_tag_ids:
        await store.attach_tag(conn, chat_row["id"], tag_id)
    # Mirrors routes_sessions: paired chats also inherit the default
    # severity when the caller (or parent checklist's tag set) didn't
    # include one. See migration 0021.
    await store.ensure_default_severity(conn, chat_row["id"])
    await store.set_item_chat_session(conn, item_id, chat_row["id"])
    metrics.sessions_created.inc()

    refreshed = await store.get_session(conn, chat_row["id"])
    assert refreshed is not None
    return SessionOut(**refreshed)


# --- autonomous driver (slice 3 of nimble-checking-heron) ------------


def _build_driver_config(body: AutoRunStart | None) -> DriverConfig | None:
    """Translate optional API overrides to a `DriverConfig`.

    `None` body / all-None fields → return `None` so the driver falls
    back to its hard-coded defaults. Per-invocation scope: callers
    override on a per-run basis, not globally."""
    if body is None:
        return None
    provided = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if not provided:
        return None
    return DriverConfig(**provided)


@router.post("/run", response_model=AutoRunStatus, status_code=202)
async def start_autonomous_run(
    session_id: str,
    request: Request,
    body: AutoRunStart | None = None,
) -> AutoRunStatus:
    """Launch the autonomous driver against this checklist. Returns
    202 with the initial `running` status snapshot. A second POST
    while a driver is still running returns 409 Conflict — the
    client is expected to GET the status or DELETE the run first."""
    await _require_checklist_session(request, session_id)
    registry = request.app.state.auto_drivers
    config = _build_driver_config(body)
    try:
        await registry.start(
            app=request.app,
            checklist_session_id=session_id,
            config=config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = registry.status(session_id)
    assert snapshot is not None, "driver was just started"
    return AutoRunStatus(**snapshot)


@router.get("/run", response_model=AutoRunStatus)
async def get_autonomous_run(session_id: str, request: Request) -> AutoRunStatus:
    """Poll the autonomous driver's current state. 404 when no driver
    has ever been started for this checklist; returns `finished` /
    `errored` for completed runs so the client can read the final
    outcome before calling DELETE to clear the entry."""
    await _require_checklist_session(request, session_id)
    registry = request.app.state.auto_drivers
    snapshot = registry.status(session_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="no autonomous driver run for this checklist",
        )
    return AutoRunStatus(**snapshot)


@router.delete("/run", status_code=204)
async def stop_autonomous_run(session_id: str, request: Request) -> Response:
    """Stop a running driver AND forget a finished one in a single
    call. Idempotent — 204 whether there was a live driver or not."""
    await _require_checklist_session(request, session_id)
    registry = request.app.state.auto_drivers
    await registry.stop(session_id)
    registry.forget(session_id)
    return Response(status_code=204)
