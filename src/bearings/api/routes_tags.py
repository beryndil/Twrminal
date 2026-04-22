from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from bearings.api.auth import require_auth
from bearings.api.models import TagCreate, TagMemoryOut, TagMemoryPut, TagOut, TagUpdate
from bearings.db import store

router = APIRouter(
    prefix="/tags",
    tags=["tags"],
    dependencies=[Depends(require_auth)],
)


async def _drop_runners_for_tag(request: Request, tag_id: int) -> None:
    """Tear down every live runner attached to `tag_id` so their next
    WS turn re-assembles the system prompt with the updated tag-memory
    layer. A tag-memory edit affects every session carrying that tag;
    without respawn, live runners keep serving the stale `--system-
    prompt` they were spawned with. Idempotent when no runners match."""
    runners = getattr(request.app.state, "runners", None)
    if runners is None:
        return
    conn = request.app.state.db
    session_ids = await store.list_session_ids_for_tag(conn, tag_id)
    for sid in session_ids:
        await runners.drop(sid)


@router.get("", response_model=list[TagOut])
async def list_tags(request: Request) -> list[TagOut]:
    rows = await store.list_tags(request.app.state.db)
    return [TagOut(**r) for r in rows]


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(body: TagCreate, request: Request) -> TagOut:
    try:
        row = await store.create_tag(
            request.app.state.db,
            name=body.name,
            color=body.color,
            pinned=body.pinned,
            sort_order=body.sort_order,
            default_working_dir=body.default_working_dir,
            default_model=body.default_model,
            tag_group=body.tag_group,
        )
    except Exception as exc:  # aiosqlite raises IntegrityError on UNIQUE
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="tag name already exists") from exc
        raise
    return TagOut(**row)


@router.get("/{tag_id}", response_model=TagOut)
async def get_tag(tag_id: int, request: Request) -> TagOut:
    row = await store.get_tag(request.app.state.db, tag_id)
    if row is None:
        raise HTTPException(status_code=404, detail="tag not found")
    return TagOut(**row)


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(tag_id: int, body: TagUpdate, request: Request) -> TagOut:
    # Only fields the client explicitly set are applied — unset fields
    # leave the column untouched.
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    try:
        row = await store.update_tag(request.app.state.db, tag_id, fields=fields)
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(status_code=409, detail="tag name already exists") from exc
        raise
    if row is None:
        raise HTTPException(status_code=404, detail="tag not found")
    return TagOut(**row)


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: int, request: Request) -> Response:
    ok = await store.delete_tag(request.app.state.db, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="tag not found")
    return Response(status_code=204)


@router.get("/{tag_id}/memory", response_model=TagMemoryOut)
async def get_tag_memory(tag_id: int, request: Request) -> TagMemoryOut:
    row = await store.get_tag_memory(request.app.state.db, tag_id)
    if row is None:
        # Could be missing tag OR missing memory — both render as 404 to
        # the client. The tag-memory editor UI loads lazily on open, so
        # a missing memory is expected on first edit, not an error.
        raise HTTPException(status_code=404, detail="tag memory not found")
    return TagMemoryOut(**row)


@router.put("/{tag_id}/memory", response_model=TagMemoryOut)
async def put_tag_memory(tag_id: int, body: TagMemoryPut, request: Request) -> TagMemoryOut:
    row = await store.put_tag_memory(request.app.state.db, tag_id, body.content)
    if row is None:
        raise HTTPException(status_code=404, detail="tag not found")
    await _drop_runners_for_tag(request, tag_id)
    return TagMemoryOut(**row)


@router.delete("/{tag_id}/memory", status_code=204)
async def delete_tag_memory(tag_id: int, request: Request) -> Response:
    ok = await store.delete_tag_memory(request.app.state.db, tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="tag memory not found")
    await _drop_runners_for_tag(request, tag_id)
    return Response(status_code=204)
