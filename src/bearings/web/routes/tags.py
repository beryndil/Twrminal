"""Tag CRUD + per-session attach/detach endpoints.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/tags.py`` owns:

* ``POST /api/tags`` — create a tag.
* ``GET /api/tags`` — list tags (optional ``group=`` filter).
* ``GET /api/tags/{id}`` — fetch one tag.
* ``PATCH /api/tags/{id}`` — replace a tag's mutable fields.
* ``DELETE /api/tags/{id}`` — delete one tag (cascades).
* ``GET /api/tag-groups`` — list distinct group prefixes.
* ``GET /api/sessions/{sid}/tags`` — list tags attached to a session.
* ``PUT /api/sessions/{sid}/tags/{tid}`` — attach (idempotent).
* ``DELETE /api/sessions/{sid}/tags/{tid}`` — detach.

Memory CRUD lives in :mod:`bearings.web.routes.memories` per arch
§1.1.5; the boundary keeps the tags-as-labels surface separable from
the tags-as-prompt-fragments surface.

Handler bodies are thin per arch §1.1.5: argument parsing, single
domain call into :mod:`bearings.db.tags`, response formatting. Errors
follow FastAPI :class:`fastapi.HTTPException` with structured ``detail``
tuples — 404 for absent resource, 409 for unique-constraint violation,
422 from the Pydantic input validators (auto-emitted).
"""

from __future__ import annotations

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status

from bearings.db import tags as tags_db
from bearings.db.tags import Tag
from bearings.web.models.tags import TagIn, TagOut, TagPinnedUpdate

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``.

    Per arch §1.1.5 ``web/app.py`` lifespan owns connection lifecycle;
    routes just read the handle. Raises 503 if the app was constructed
    without a DB (the streaming-only surface from item 1.2).
    """
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return db  # type: ignore[no-any-return]


def _to_out(tag: Tag) -> TagOut:
    """Wire shape for a tag — ``group`` derived via the dataclass property."""
    return TagOut(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        default_model=tag.default_model,
        working_dir=tag.working_dir,
        pinned=tag.pinned,
        group=tag.group,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


@router.post("/api/tags", status_code=status.HTTP_201_CREATED, response_model=TagOut)
async def create_tag(payload: TagIn, request: Request) -> TagOut:
    """Create a tag; 409 if ``name`` is taken, 422 if the shape is bad."""
    db = _db(request)
    try:
        tag = await tags_db.create(
            db,
            name=payload.name,
            color=payload.color,
            default_model=payload.default_model,
            working_dir=payload.working_dir,
        )
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"tag name {payload.name!r} already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return _to_out(tag)


@router.get("/api/tags", response_model=list[TagOut])
async def list_tags(request: Request, group: str | None = None) -> list[TagOut]:
    """Every tag, alphabetical; optional ``?group=`` filter for the prefix."""
    db = _db(request)
    rows = await tags_db.list_all(db, group=group)
    return [_to_out(tag) for tag in rows]


@router.get("/api/tag-groups", response_model=list[str])
async def list_tag_groups(request: Request) -> list[str]:
    """Distinct slash-prefix groups across the tag set."""
    db = _db(request)
    return await tags_db.list_groups(db)


@router.get("/api/tags/{tag_id}", response_model=TagOut)
async def get_tag(tag_id: int, request: Request) -> TagOut:
    """Fetch one tag; 404 if absent."""
    db = _db(request)
    tag = await tags_db.get(db, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    return _to_out(tag)


@router.patch("/api/tags/{tag_id}", response_model=TagOut)
async def update_tag(tag_id: int, payload: TagIn, request: Request) -> TagOut:
    """Replace a tag's mutable fields; 404 if absent, 409 on rename collision."""
    db = _db(request)
    try:
        tag = await tags_db.update(
            db,
            tag_id,
            name=payload.name,
            color=payload.color,
            default_model=payload.default_model,
            working_dir=payload.working_dir,
        )
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"tag name {payload.name!r} already exists",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    return _to_out(tag)


@router.patch("/api/tags/{tag_id}/pinned", response_model=TagOut)
async def patch_tag_pinned(tag_id: int, payload: TagPinnedUpdate, request: Request) -> TagOut:
    """Pin or unpin a tag via ``PATCH /api/tags/{id}/pinned``.

    ``{pinned: true}`` pins the tag in the sidebar filter panel;
    ``{pinned: false}`` unpins it. 404 if absent.
    """
    db = _db(request)
    tag = await tags_db.update_pinned(db, tag_id, pinned=payload.pinned)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    return _to_out(tag)


@router.delete("/api/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: int, request: Request) -> None:
    """Delete one tag; cascades through ``session_tags`` + ``tag_memories``."""
    db = _db(request)
    removed = await tags_db.delete(db, tag_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")


@router.get("/api/sessions/{session_id}/tags", response_model=list[TagOut])
async def list_session_tags(session_id: str, request: Request) -> list[TagOut]:
    """Every tag attached to ``session_id``, alphabetical."""
    db = _db(request)
    rows = await tags_db.list_for_session(db, session_id)
    return [_to_out(tag) for tag in rows]


@router.put(
    "/api/sessions/{session_id}/tags/{tag_id}",
    response_model=TagOut,
)
async def attach_tag(session_id: str, tag_id: int, request: Request) -> TagOut:
    """Attach a tag to a session; idempotent (200 either way).

    Returns the tag row. 404 if either FK is absent (raised as
    ``IntegrityError`` from the DB layer when foreign-key enforcement
    is on).
    """
    db = _db(request)
    try:
        await tags_db.attach(db, session_id=session_id, tag_id=tag_id)
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id!r} or tag {tag_id} not found",
        ) from exc
    tag = await tags_db.get(db, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    return _to_out(tag)


@router.delete(
    "/api/sessions/{session_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def detach_tag(session_id: str, tag_id: int, request: Request) -> None:
    """Detach a tag from a session; 404 if no such attachment existed."""
    db = _db(request)
    removed = await tags_db.detach(db, session_id=session_id, tag_id=tag_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id!r} not tagged with {tag_id}",
        )


__all__ = ["router"]
