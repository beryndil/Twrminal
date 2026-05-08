"""Tag-memory CRUD endpoints (sub-resource of tags).

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/memories.py`` is
its own module so the boundary between "tags as labels" and "tag
memories as system-prompt fragments" stays visible (mirrors the same
db-layer split — :mod:`bearings.db.tags` vs :mod:`bearings.db.memories`).

Endpoints:

* ``GET /api/memories`` — global flat-list across all tags (gap-cycle-13-007).
* ``POST /api/tags/{tag_id}/memories`` — create.
* ``GET /api/tags/{tag_id}/memories`` — list (optional
  ``?only_enabled=true`` filter for prompt-assembler consumers).
* ``GET /api/memories/{id}`` — fetch one.
* ``PATCH /api/memories/{id}`` — replace mutable fields.
* ``DELETE /api/memories/{id}`` — delete.

Memories are addressable both via their parent tag (``/tags/{id}/
memories``) and directly by id (``/memories/{id}``); the dual surface
matches v0.17.x's UI which shows the editor in two places — inside
the per-tag panel and as a flat list.

Route ordering note: ``GET /api/memories`` (no path param) is
registered BEFORE ``GET /api/memories/{memory_id}`` (path param) so
FastAPI's static-path-first precedence resolves correctly.
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status

from bearings.db import memories as memories_db
from bearings.db import tags as tags_db
from bearings.db.memories import TagMemory
from bearings.web.models.tags import AllMemoriesOut, TagMemoryIn, TagMemoryOut

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state`` (see
    :func:`bearings.web.routes.tags._db`)."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return db  # type: ignore[no-any-return]


def _to_out(memory: TagMemory) -> TagMemoryOut:
    """Wire shape for a tag-memory row."""
    return TagMemoryOut(
        id=memory.id,
        tag_id=memory.tag_id,
        title=memory.title,
        body=memory.body,
        enabled=memory.enabled,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


@router.post(
    "/api/tags/{tag_id}/memories",
    status_code=status.HTTP_201_CREATED,
    response_model=TagMemoryOut,
    operation_id="create-tag-memory",
)
async def create_memory(
    tag_id: int,
    payload: TagMemoryIn,
    request: Request,
) -> TagMemoryOut:
    """Create a memory under ``tag_id``; 404 if the tag is absent."""
    db = _db(request)
    parent = await tags_db.get(db, tag_id)
    if parent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    try:
        memory = await memories_db.create(
            db,
            tag_id=tag_id,
            title=payload.title,
            body=payload.body,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _to_out(memory)


@router.get(
    "/api/tags/{tag_id}/memories",
    response_model=list[TagMemoryOut],
    operation_id="list-tag-memories",
)
async def list_memories_for_tag(
    tag_id: int,
    request: Request,
    only_enabled: bool = False,
) -> list[TagMemoryOut]:
    """Every memory attached to ``tag_id``; ``only_enabled`` filters disabled."""
    db = _db(request)
    parent = await tags_db.get(db, tag_id)
    if parent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    rows = await memories_db.list_for_tag(db, tag_id, only_enabled=only_enabled)
    return [_to_out(row) for row in rows]


@router.get(
    "/api/memories",
    response_model=list[AllMemoriesOut],
    operation_id="list-all-memories",
)
async def list_all_memories(
    request: Request,
    only_enabled: bool = False,
) -> list[AllMemoriesOut]:
    """Every memory across every tag, sorted by tag name then memory title.

    Returns a flat list of :class:`AllMemoriesOut` rows — each row
    carries enough tag context for the global-index view to render
    without a second round-trip. ``memory_body_preview`` is the body
    truncated to
    :data:`bearings.config.constants.MEMORY_BODY_PREVIEW_MAX_LENGTH`
    chars; the full body is still available via ``GET /api/memories/{id}``.

    ``?only_enabled=true`` restricts to enabled memories — mirrors the
    same query param supported by the per-tag list endpoint.
    """
    db = _db(request)
    rows = await memories_db.list_all(db, only_enabled=only_enabled)
    return [
        AllMemoriesOut(
            tag_id=row.tag_id,
            tag_name=row.tag_name,
            tag_color=row.tag_color,
            memory_id=row.memory_id,
            memory_title=row.memory_title,
            memory_body_preview=row.memory_body_preview,
            enabled=row.enabled,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/api/memories/{memory_id}", response_model=TagMemoryOut, operation_id="get-memory")
async def get_memory(memory_id: int, request: Request) -> TagMemoryOut:
    """Fetch one memory; 404 if absent."""
    db = _db(request)
    memory = await memories_db.get(db, memory_id)
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"memory {memory_id} not found"
        )
    return _to_out(memory)


@router.patch(
    "/api/memories/{memory_id}",
    response_model=TagMemoryOut,
    operation_id="update-memory",
)
async def update_memory(
    memory_id: int,
    payload: TagMemoryIn,
    request: Request,
) -> TagMemoryOut:
    """Replace a memory's mutable fields; 404 if absent."""
    db = _db(request)
    try:
        memory = await memories_db.update(
            db,
            memory_id,
            title=payload.title,
            body=payload.body,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if memory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"memory {memory_id} not found"
        )
    return _to_out(memory)


@router.delete(
    "/api/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete-memory",
)
async def delete_memory(memory_id: int, request: Request) -> None:
    """Delete one memory; 404 if absent."""
    db = _db(request)
    removed = await memories_db.delete(db, memory_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"memory {memory_id} not found"
        )


__all__ = ["router"]
