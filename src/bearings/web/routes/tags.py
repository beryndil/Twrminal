"""Tag CRUD + per-session attach/detach endpoints.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/tags.py`` owns:

* ``POST /api/tags`` — create a tag.
* ``GET /api/tags`` — list tags (optional ``class_=`` filter; the
  legacy ``group=`` filter is retained for one release).
* ``GET /api/tags/{id}`` — fetch one tag.
* ``PATCH /api/tags/{id}`` — replace a tag's mutable fields.
* ``PUT /api/tags/sort-order`` — re-sequence ``sort_order`` within a
  class to match an explicit id list (drag-reorder path).
* ``DELETE /api/tags/{id}`` — delete one tag (cascades).
* ``GET /api/tag-groups`` — **deprecated** — list distinct slash-prefix
  groups; superseded by the ``class`` column.
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

from typing import TYPE_CHECKING, cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request, status

from bearings.config.constants import KNOWN_TAG_CLASSES, TAG_CLASS_PROJECT, TAG_CLASS_SEVERITY
from bearings.db import tags as tags_db
from bearings.db.tags import Tag
from bearings.web.models.tags import (
    TagIn,
    TagOut,
    TagPinnedUpdate,
    TagSortOrderUpdate,
)

if TYPE_CHECKING:
    from bearings.web.routes.ws_sessions import SessionsBroadcaster

router = APIRouter()


def _broadcaster(request: Request) -> SessionsBroadcaster | None:
    """Pull the optional sessions broadcaster off ``app.state``.

    Returns ``None`` when no broadcaster is wired (test-only paths
    that construct a minimal app without a DB); callers guard on
    ``if broadcaster is not None`` before publishing.
    """
    from bearings.web.routes.ws_sessions import SessionsBroadcaster as _SB

    return cast(
        _SB | None,
        getattr(request.app.state, "sessions_broadcaster", None),
    )


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


def _to_out(
    tag: Tag,
    *,
    open_session_count: int = 0,
    session_count: int = 0,
) -> TagOut:
    """Wire shape for a tag — ``group`` derived via the dataclass property.

    ``open_session_count`` / ``session_count`` are only populated by
    :func:`list_tags` (which uses :func:`bearings.db.tags.list_all_with_counts`);
    all other endpoints default to ``0``.
    """
    return TagOut(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        default_model=tag.default_model,
        working_dir=tag.working_dir,
        pinned=tag.pinned,
        class_=tag.class_,  # type: ignore[arg-type]
        sort_order=tag.sort_order,
        group=tag.group,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
        open_session_count=open_session_count,
        session_count=session_count,
    )


async def _validate_tag_cardinality(
    db: aiosqlite.Connection,
    tag_ids: tuple[int, ...],
) -> None:
    """Reject tag-id sets that violate the ≤1 project / ≤1 severity rule.

    Cardinality is enforced at the API boundary (not the schema) so a
    half-built create transaction can roll back cleanly. Called by every
    path that mutates a session's tag set:

    * ``POST /api/sessions`` — initial tag assignment on create.
    * ``PATCH /api/sessions/{id}`` — bulk tag replacement.
    * ``PUT /api/sessions/{sid}/tags/{tid}`` — single-attach.

    Raises :class:`HTTPException` 422 with a structured detail listing
    the violating ids per class. Empty ``tag_ids`` is valid.
    """
    if not tag_ids:
        return
    # Resolve class for each id in one round-trip. Existing-id validation
    # happens upstream; if any id is missing here the count below simply
    # ignores it (the missing-id 404 fires before we reach this function).
    placeholders = ",".join("?" * len(tag_ids))
    cursor = await db.execute(
        f"SELECT id, class FROM tags WHERE id IN ({placeholders})",
        tag_ids,
    )
    try:
        rows = await cursor.fetchall()
    finally:
        await cursor.close()
    by_class: dict[str, list[int]] = {}
    for row in rows:
        by_class.setdefault(str(row[1]), []).append(int(str(row[0])))
    project_ids = by_class.get(TAG_CLASS_PROJECT, [])
    severity_ids = by_class.get(TAG_CLASS_SEVERITY, [])
    violations: list[str] = []
    if len(project_ids) > 1:
        violations.append(f"≤1 project tag allowed (got {sorted(project_ids)})")
    if len(severity_ids) > 1:
        violations.append(f"≤1 severity tag allowed (got {sorted(severity_ids)})")
    if violations:
        # f-string keeps the detail value AST-detectable as string-typed
        # for the consistency_lint error-shape rule (which rejects bare
        # ``str.join`` calls — only ``str(...)``, literals, f-strings,
        # and string-typed ternaries are accepted).
        message = "; ".join(violations)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{message}",
        )


@router.post(
    "/api/tags",
    status_code=status.HTTP_201_CREATED,
    response_model=TagOut,
    operation_id="create-tag",
)
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
            class_=payload.class_,
            sort_order=payload.sort_order,
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
    out = _to_out(tag)
    broadcaster = _broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_tag_upsert(out)
    return out


@router.get("/api/tags", response_model=list[TagOut], operation_id="list-tags")
async def list_tags(
    request: Request,
    class_: str | None = None,
    group: str | None = None,
) -> list[TagOut]:
    """Every tag, ordered ``(class, sort_order, name)``; optional filters.

    ``?class_=`` filters to ``project`` / ``severity`` / ``general``;
    422 on an unknown value. ``?group=`` is the deprecated slash-prefix
    filter, retained for one release. Both compose via AND when set.

    Each tag carries ``open_session_count`` (sessions with
    ``closed_at IS NULL``) and ``session_count`` (all sessions) via a
    single LEFT JOIN aggregation — one round-trip, no per-tag fetch.
    """
    db = _db(request)
    if class_ is not None and class_ not in KNOWN_TAG_CLASSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"class_ {class_!r} is not in {sorted(KNOWN_TAG_CLASSES)}",
        )
    rows = await tags_db.list_all_with_counts(db, class_=class_, group=group)
    return [
        _to_out(tag, open_session_count=open_count, session_count=total_count)
        for tag, open_count, total_count in rows
    ]


@router.put(
    "/api/tags/sort-order",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="update-tags-sort-order",
)
async def update_tags_sort_order(payload: TagSortOrderUpdate, request: Request) -> None:
    """Re-sequence ``sort_order`` within ``payload.class_`` to match the id list.

    Drag-to-reorder path on the ``/tags`` page. Each id at index ``i``
    in ``ordered_ids`` gets ``sort_order = i``. Empty ``ordered_ids``
    is a no-op (validates the class only). 422 if any id is missing
    or belongs to a different class.
    """
    db = _db(request)
    ordered_ids = tuple(payload.ordered_ids)
    try:
        await tags_db.update_sort_orders(
            db,
            class_=payload.class_,
            ordered_ids=ordered_ids,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    broadcaster = _broadcaster(request)
    if broadcaster is not None and ordered_ids:
        # Broadcast tag_upsert for every reordered tag so filter panels in
        # other tabs refresh sort positions without polling.
        rows = await tags_db.list_all_with_counts(db, class_=payload.class_)
        for tag, open_count, total_count in rows:
            broadcaster.publish_tag_upsert(
                _to_out(tag, open_session_count=open_count, session_count=total_count)
            )


@router.get(
    "/api/tag-groups",
    response_model=list[str],
    deprecated=True,
    operation_id="list-tag-groups",
)
async def list_tag_groups(request: Request) -> list[str]:
    """Distinct slash-prefix groups across the tag set.

    **Deprecated** — the slash-namespace concept is superseded by the
    :class:`Tag.class_` column. Retained for one release so v0.18.x
    frontend builds keep rendering. Frontend should migrate to
    ``GET /api/tags?class_=...``.
    """
    db = _db(request)
    return await tags_db.list_groups(db)


@router.get("/api/tags/{tag_id}", response_model=TagOut, operation_id="get-tag")
async def get_tag(tag_id: int, request: Request) -> TagOut:
    """Fetch one tag; 404 if absent."""
    db = _db(request)
    tag = await tags_db.get(db, tag_id)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    return _to_out(tag)


@router.patch("/api/tags/{tag_id}", response_model=TagOut, operation_id="update-tag")
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
            class_=payload.class_,
            sort_order=payload.sort_order,
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
    out = _to_out(tag)
    broadcaster = _broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_tag_upsert(out)
    return out


@router.patch("/api/tags/{tag_id}/pinned", response_model=TagOut, operation_id="patch-tag-pinned")
async def patch_tag_pinned(tag_id: int, payload: TagPinnedUpdate, request: Request) -> TagOut:
    """Pin or unpin a tag via ``PATCH /api/tags/{id}/pinned``.

    ``{pinned: true}`` pins the tag in the sidebar filter panel;
    ``{pinned: false}`` unpins it. 404 if absent.
    """
    db = _db(request)
    tag = await tags_db.update_pinned(db, tag_id, pinned=payload.pinned)
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    out = _to_out(tag)
    broadcaster = _broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_tag_upsert(out)
    return out


@router.delete(
    "/api/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete-tag",
)
async def delete_tag(tag_id: int, request: Request) -> None:
    """Delete one tag; cascades through ``session_tags`` + ``tag_memories``."""
    db = _db(request)
    removed = await tags_db.delete(db, tag_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tag {tag_id} not found")
    broadcaster = _broadcaster(request)
    if broadcaster is not None:
        broadcaster.publish_tag_delete(tag_id)


@router.get(
    "/api/sessions/{session_id}/tags",
    response_model=list[TagOut],
    operation_id="list-session-tags",
)
async def list_session_tags(session_id: str, request: Request) -> list[TagOut]:
    """Every tag attached to ``session_id``, alphabetical."""
    db = _db(request)
    rows = await tags_db.list_for_session(db, session_id)
    return [_to_out(tag) for tag in rows]


@router.put(
    "/api/sessions/{session_id}/tags/{tag_id}",
    response_model=TagOut,
    operation_id="attach-tag-to-session",
)
async def attach_tag(session_id: str, tag_id: int, request: Request) -> TagOut:
    """Attach a tag to a session; idempotent (200 either way).

    Returns the tag row. 404 if either FK is absent (raised as
    ``IntegrityError`` from the DB layer when foreign-key enforcement
    is on). 422 when attaching the tag would violate the ≤1 project /
    ≤1 severity cardinality rule for the session.

    Idempotency: re-attaching an already-attached tag skips the
    cardinality check (the existing state is already valid) and returns
    200 without touching the DB.
    """
    db = _db(request)
    # Load the set already attached so we can (a) detect idempotent
    # re-attach without a DB write and (b) validate cardinality against
    # the would-be new set before persisting.
    existing_tags = await tags_db.list_for_session(db, session_id)
    existing_ids = {t.id for t in existing_tags}
    if tag_id not in existing_ids:
        # The attach is genuinely new — enforce cardinality on the union.
        candidate_ids = tuple(existing_ids | {tag_id})
        await _validate_tag_cardinality(db, candidate_ids)
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
    broadcaster = _broadcaster(request)
    if broadcaster is not None:
        # Broadcast the post-mutation session row so other tabs see the
        # updated tag set without a full re-fetch (feature-5-003 / CCW-3).
        # Local import avoids circular dependency: sessions.py already
        # imports _validate_tag_cardinality from this module at module load.
        from bearings.db import sessions as sessions_db
        from bearings.web.routes.sessions import _to_out as _session_to_out

        session_row = await sessions_db.get(db, session_id)
        if session_row is not None:
            broadcaster.publish_upsert(_session_to_out(session_row))
    return _to_out(tag)


@router.delete(
    "/api/sessions/{session_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="detach-tag-from-session",
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
    broadcaster = _broadcaster(request)
    if broadcaster is not None:
        # Broadcast the post-detach session row so other tabs see the
        # updated tag set without polling (feature-5-003 / CCW-3).
        from bearings.db import sessions as sessions_db
        from bearings.web.routes.sessions import _to_out as _session_to_out

        session_row = await sessions_db.get(db, session_id)
        if session_row is not None:
            broadcaster.publish_upsert(_session_to_out(session_row))


__all__ = ["router"]
