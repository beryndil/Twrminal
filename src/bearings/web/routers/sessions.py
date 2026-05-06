"""Sessions HTTP endpoints.

Thin layer per the service-layer rules: validate input via Pydantic,
call the service, translate the dict to a response model, return the
response. 404s and validation errors flow through the
:mod:`bearings.web.errors` envelope handler — no error rendering here.
"""

from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from bearings.models.sessions import (
    SessionCreate,
    SessionKind,
    SessionList,
    SessionResponse,
    SessionUpdate,
)
from bearings.services import sessions as sessions_service
from bearings.web.auth import require_auth
from bearings.web.db import get_db

router = APIRouter(
    prefix="/api/sessions",
    tags=["sessions"],
    # Apply auth at the router level so individual routes don't have
    # to re-declare it. Health stays unauthenticated because it's on a
    # different router with no dependencies.
    dependencies=[Depends(require_auth)],
)

DbDep = Annotated[aiosqlite.Connection, Depends(get_db)]


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a session",
)
async def create_session(payload: SessionCreate, db: DbDep) -> SessionResponse:
    """Create a new session and return the persisted record."""
    row = await sessions_service.create_session(db, payload)
    return SessionResponse.model_validate(row)


@router.get(
    "",
    response_model=SessionList,
    summary="List sessions (paginated)",
)
async def list_sessions(
    db: DbDep,
    limit: Annotated[
        int,
        Query(ge=1, le=sessions_service.LIST_LIMIT_MAX),
    ] = sessions_service.LIST_LIMIT_DEFAULT,
    offset: Annotated[int, Query(ge=0)] = 0,
    kind: SessionKind | None = None,
) -> SessionList:
    """Return a page of sessions ordered by ``created_at`` DESC."""
    items, total = await sessions_service.list_sessions(
        db,
        limit=limit,
        offset=offset,
        kind=kind,
    )
    return SessionList(
        items=[SessionResponse.model_validate(row) for row in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Get one session by id",
)
async def get_session(session_id: str, db: DbDep) -> SessionResponse:
    """Return one session, or 404 if no row matches *session_id*."""
    row = await sessions_service.get_session(db, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id!r} not found",
        )
    return SessionResponse.model_validate(row)


@router.patch(
    "/{session_id}",
    response_model=SessionResponse,
    summary="Partial update of a session",
)
async def update_session(
    session_id: str,
    payload: SessionUpdate,
    db: DbDep,
) -> SessionResponse:
    """Apply a partial update; 404 if the session does not exist."""
    row = await sessions_service.update_session(db, session_id, payload)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id!r} not found",
        )
    return SessionResponse.model_validate(row)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session",
)
async def delete_session(session_id: str, db: DbDep) -> Response:
    """Hard-delete the session row; 404 if it doesn't exist."""
    deleted = await sessions_service.delete_session(db, session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"session {session_id!r} not found",
        )
    # 204 must not include a body — return an empty Response explicitly
    # so FastAPI doesn't try to serialize ``None`` against the absent
    # response_model.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
