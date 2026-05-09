# mypy: disable-error-code=explicit-any
"""API route for importing data from the original Bearings database."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from bearings.db.import_bearings import import_from_bearings
from bearings.web.models.errors import DetailError
from bearings.web.models.import_bearings import BearingsImportRequest


class ImportResultOut(BaseModel):
    """Response model for import operation."""

    tags_imported: int
    sessions_imported: int
    messages_imported: int
    session_tags_imported: int
    tag_memories_imported: int
    checklist_items_imported: int
    tags_skipped: int
    sessions_skipped: int
    messages_skipped: int
    session_tags_skipped: int
    tag_memories_skipped: int
    checklist_items_skipped: int
    errors: list[str]


def _db(request: Request) -> aiosqlite.Connection:
    """Get the database connection from app state. Raise 503 if not available."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _source_db_path() -> Path:
    """Return the path to the original Bearings database for import."""
    return Path.home() / ".local" / "share" / "bearings" / "db.sqlite"


router = APIRouter()


@router.post(
    "/api/import/bearings",
    response_model=ImportResultOut,
    operation_id="import-bearings-db",
    responses={
        400: {"model": DetailError},
        404: {"model": DetailError},
        503: {"model": DetailError},
    },
)
async def post_import_bearings(payload: BearingsImportRequest, request: Request) -> ImportResultOut:
    """Import all data from the original Bearings database.

    ``payload.confirm`` must be ``True``; omitting it or passing ``False``
    returns 400 without touching any data.  ``payload.source_dir`` overrides
    the default source location (``~/.local/share/bearings/``); when
    ``None``, the default is used and the database is read from
    ``<source_dir>/db.sqlite``.

    Rows with duplicate IDs are silently skipped (INSERT OR IGNORE).
    The entire operation is wrapped in a transaction — on any error,
    the import rolls back completely.

    Returns:
        ImportResultOut with counts of imported/skipped rows per table.
        If errors occurred, they are listed in the errors field (but
        the operation was rolled back, so no partial state persists).

    Raises:
        400: If confirm is False or not provided.
        404: If the source database file does not exist.
        503: If db_connection is not configured on app.state.
    """
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm must be true to proceed with import",
        )

    db = _db(request)

    source_path = (
        payload.source_dir / "db.sqlite" if payload.source_dir is not None else _source_db_path()
    )

    if not source_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Source database not found: {source_path}",
        )

    result = await import_from_bearings(
        dest=db,
        source_path=source_path,
    )

    return ImportResultOut(
        tags_imported=result.tags_imported,
        sessions_imported=result.sessions_imported,
        messages_imported=result.messages_imported,
        session_tags_imported=result.session_tags_imported,
        tag_memories_imported=result.tag_memories_imported,
        checklist_items_imported=result.checklist_items_imported,
        tags_skipped=result.tags_skipped,
        sessions_skipped=result.sessions_skipped,
        messages_skipped=result.messages_skipped,
        session_tags_skipped=result.session_tags_skipped,
        tag_memories_skipped=result.tag_memories_skipped,
        checklist_items_skipped=result.checklist_items_skipped,
        errors=result.errors,
    )


__all__ = ["router"]
