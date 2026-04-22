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

from bearings.api.auth import require_auth
from bearings.api.models import (
    ChecklistOut,
    ChecklistUpdate,
    ItemCreate,
    ItemOut,
    ItemToggle,
    ItemUpdate,
    ReorderRequest,
    ReorderResult,
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
    existing = await store.get_item(request.app.state.db, item_id)
    if existing is None or existing["checklist_id"] != session_id:
        raise HTTPException(status_code=404, detail="item not found")
    row = await store.toggle_item(request.app.state.db, item_id, checked=body.checked)
    if row is None:
        # Race: item was deleted between the check and the toggle.
        raise HTTPException(status_code=404, detail="item not found")
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
