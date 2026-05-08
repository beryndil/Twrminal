"""File-upload routes (item 1.10).

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/uploads.py``
owns the multipart-form upload surface. Behavior docs are silent on
endpoint shape; see ``src/bearings/config/constants.py`` §"Uploads"
for the decided-and-documented contract:

* ``POST   /api/uploads`` — multipart/form-data with single ``file``
  part. Body is content-addressed by sha256; duplicate uploads
  return the existing row (dedup at zero cost).
* ``GET    /api/uploads`` — newest-first list, capped at
  ``UPLOADS_LIST_DEFAULT_LIMIT``.
* ``GET    /api/uploads/{id}`` — metadata only.
* ``GET    /api/uploads/{id}/content`` — streams the on-disk body.
* ``DELETE /api/uploads/{id}`` — removes both row and on-disk body.
"""

from __future__ import annotations

from typing import Annotated, cast

import aiosqlite
from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from bearings.agent.uploads import (
    compute_sha256,
    delete_bytes,
    store_bytes,
    stream_bytes,
)
from bearings.config.constants import (
    MAX_UPLOAD_SIZE_BYTES,
    UPLOAD_DEFAULT_MIME_TYPE,
    UPLOAD_FILENAME_MAX_LENGTH,
    UPLOAD_MIME_TYPE_MAX_LENGTH,
    UPLOADS_LIST_DEFAULT_LIMIT,
    UPLOADS_LIST_MAX_LIMIT,
)
from bearings.config.settings import UploadsCfg
from bearings.db import uploads as uploads_db
from bearings.db.uploads import UploadRow
from bearings.web.models.uploads import UploadListOut, UploadOut

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state`` (503 if absent)."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return cast(aiosqlite.Connection, db)


def _cfg(request: Request) -> UploadsCfg:
    """Pull the :class:`UploadsCfg` off ``app.state``; falls back to defaults."""
    cfg = getattr(request.app.state, "uploads_cfg", None)
    if cfg is None:
        return UploadsCfg()
    if not isinstance(cfg, UploadsCfg):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="uploads_cfg on app.state is not an UploadsCfg instance",
        )
    return cfg


def _to_out(row: UploadRow) -> UploadOut:
    """Wire shape for an upload row."""
    return UploadOut(
        id=row.id,
        sha256=row.sha256,
        filename=row.filename,
        mime_type=row.mime_type,
        size=row.size,
        created_at=row.created_at,
    )


@router.post(
    "/api/uploads",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="create-upload",
)
async def post_upload(
    request: Request,
    file: Annotated[UploadFile, File(description="The file body to upload.")],
) -> UploadOut:
    """Accept a multipart upload; store body + metadata; return the row."""
    db = _db(request)
    cfg = _cfg(request)
    body = await file.read()
    if len(body) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="upload body is empty",
        )
    if len(body) > cfg.max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"upload body is {len(body)} bytes "
                f"(cap {cfg.max_size_bytes}, default {MAX_UPLOAD_SIZE_BYTES})"
            ),
        )
    filename = (file.filename or "upload").strip()
    if len(filename) > UPLOAD_FILENAME_MAX_LENGTH:
        filename = filename[:UPLOAD_FILENAME_MAX_LENGTH]
    mime_type = (file.content_type or UPLOAD_DEFAULT_MIME_TYPE)[:UPLOAD_MIME_TYPE_MAX_LENGTH]
    sha256 = compute_sha256(body)
    store_bytes(cfg.storage_root, sha256, body)
    row = await uploads_db.insert_or_get(
        db,
        sha256=sha256,
        filename=filename,
        mime_type=mime_type,
        size=len(body),
    )
    return _to_out(row)


@router.get("/api/uploads", response_model=UploadListOut, operation_id="list-uploads")
async def list_uploads(
    request: Request,
    limit: int = Query(
        default=UPLOADS_LIST_DEFAULT_LIMIT,
        gt=0,
        le=UPLOADS_LIST_MAX_LIMIT,
        description=f"Max rows to return (1-{UPLOADS_LIST_MAX_LIMIT}).",
    ),
) -> UploadListOut:
    """List uploads newest-first."""
    db = _db(request)
    rows = await uploads_db.list_all(db, limit=limit)
    return UploadListOut(uploads=[_to_out(r) for r in rows])


@router.get("/api/uploads/{upload_id}", response_model=UploadOut, operation_id="get-upload")
async def get_upload(upload_id: int, request: Request) -> UploadOut:
    """Fetch one upload by id; 404 if absent."""
    db = _db(request)
    row = await uploads_db.get(db, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upload {upload_id} not found",
        )
    return _to_out(row)


@router.get("/api/uploads/{upload_id}/content", operation_id="get-upload-content")
async def get_upload_content(upload_id: int, request: Request) -> StreamingResponse:
    """Stream the on-disk body for ``upload_id``; 404 if absent."""
    db = _db(request)
    cfg = _cfg(request)
    row = await uploads_db.get(db, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upload {upload_id} not found",
        )
    return StreamingResponse(
        content=stream_bytes(cfg.storage_root, row.sha256),
        media_type=row.mime_type,
        headers={"Content-Length": str(row.size)},
    )


@router.delete(
    "/api/uploads/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete-upload",
)
async def delete_upload(upload_id: int, request: Request) -> None:
    """Remove the row + on-disk body; 404 if absent."""
    db = _db(request)
    cfg = _cfg(request)
    row = await uploads_db.get(db, upload_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"upload {upload_id} not found",
        )
    await uploads_db.delete(db, upload_id)
    delete_bytes(cfg.storage_root, row.sha256)


__all__ = ["router"]
