"""User-preferences singleton endpoints (item 3.2 + gap-cycle-03-011).

Exposes operations against the :class:`bearings.db.preferences.Preferences`
singleton row:

* ``GET  /api/preferences``               — return current values.
* ``PATCH /api/preferences``              — update supplied fields; omitted
  fields are left unchanged.
* ``GET  /api/preferences/avatar``        — serve the current avatar bytes.
* ``POST /api/preferences/avatar``        — upload a new avatar image
  (multipart/form-data ``file`` field). Replaces any existing avatar.
* ``DELETE /api/preferences/avatar``      — remove the avatar file and clear
  the DB fields.
* ``POST /api/preferences/sync_from_system`` — populate ``display_name``
  from ``$USER`` and (when ``~/.face`` exists) copy it as the new avatar.

Avatar storage
--------------
Avatars are a singleton — exactly one file exists at a time. The file is
stored at ``<avatars_root>/current`` where ``avatars_root`` is read from
``app.state.avatars_root`` (injected by :func:`bearings.web.app.create_app`).
The MIME type is recorded in the DB row so the serve route never re-probes
the on-disk file.

The preferences row is seeded by ``schema.sql``'s
``INSERT OR IGNORE INTO preferences (id) VALUES (1)`` and therefore
always exists after :func:`bearings.db.connection.load_schema` has run.

PATCH semantics (Pydantic ``model_fields_set``)
------------------------------------------------
The request body is a JSON object; only explicitly-supplied keys are
written to the DB. This means:

* ``{}``                    — no-op; returns current row.
* ``{"theme": "evergreen"}``— updates theme only.
* ``{"default_model": null}``— clears default_model to NULL.
* ``{"default_model": "haiku", "default_working_dir": null}``
                            — updates two fields.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from bearings.config.constants import (
    AVATAR_ALLOWED_MIME_TYPES,
    DEFAULT_AVATARS_STORAGE_ROOT,
    DISPLAY_NAME_MAX_LENGTH,
    MAX_AVATAR_SIZE_BYTES,
)
from bearings.db import preferences as prefs_db
from bearings.db.preferences import Preferences
from bearings.web.models.preferences import PreferencesOut, PreferencesPatch

# URL path prefix for serving the avatar — kept as a constant so the
# ``_to_out`` helper and any future redirect logic share the same string.
_AVATAR_URL_PATH = "/api/preferences/avatar"

router = APIRouter()


def _db(request: Request) -> aiosqlite.Connection:
    """Pull the long-lived DB connection off ``app.state``."""
    db = getattr(request.app.state, "db_connection", None)
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="db_connection not configured on app.state",
        )
    return db  # type: ignore[no-any-return]


def _avatars_root(request: Request) -> Path:
    """Return the on-disk avatars directory, creating it when absent."""
    root: Path = getattr(request.app.state, "avatars_root", DEFAULT_AVATARS_STORAGE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _to_out(prefs: Preferences) -> PreferencesOut:
    return PreferencesOut(
        theme=prefs.theme,
        default_model=prefs.default_model,
        default_permission_mode=prefs.default_permission_mode,
        default_working_dir=prefs.default_working_dir,
        display_name=prefs.display_name,
        avatar_url=_AVATAR_URL_PATH if prefs.avatar_path is not None else None,
        notify_on_complete=prefs.notify_on_complete,
        updated_at=prefs.updated_at,
    )


# ---------------------------------------------------------------------------
# Standard preferences (GET / PATCH)
# ---------------------------------------------------------------------------


@router.get("/api/preferences", response_model=PreferencesOut)
async def get_preferences(request: Request) -> PreferencesOut:
    """Return the singleton user-preferences row."""
    prefs = await prefs_db.get_preferences(_db(request))
    return _to_out(prefs)


@router.patch("/api/preferences", response_model=PreferencesOut)
async def patch_preferences(
    body: PreferencesPatch,
    request: Request,
) -> PreferencesOut:
    """Partially update user preferences.

    Only fields present in the request body are written; omitted fields
    retain their current values.
    """
    db = _db(request)
    supplied = body.model_fields_set

    # Pass model_fields_set as ``fields`` so patch_preferences knows
    # which nullable columns were explicitly supplied (vs. omitted).
    prefs = await prefs_db.patch_preferences(
        db,
        theme=body.theme if "theme" in supplied else None,
        default_model=body.default_model,
        default_permission_mode=body.default_permission_mode,
        default_working_dir=body.default_working_dir,
        display_name=body.display_name,
        notify_on_complete=body.notify_on_complete,
        fields=frozenset(supplied - {"theme"}),
    )
    return _to_out(prefs)


# ---------------------------------------------------------------------------
# Avatar endpoints (GET / POST / DELETE)
# ---------------------------------------------------------------------------


@router.get("/api/preferences/avatar")
async def get_avatar(request: Request) -> Response:
    """Serve the current avatar image bytes.

    Returns 404 when no avatar has been set. The response carries the
    stored MIME type; callers append ``?v=<updated_at>`` to the URL for
    cache-busting.
    """
    prefs = await prefs_db.get_preferences(_db(request))
    if prefs.avatar_path is None or prefs.avatar_mime_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no avatar set",
        )
    path = Path(prefs.avatar_path)
    if not path.exists():  # noqa: ASYNC240
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="avatar file missing from disk",
        )
    return Response(
        content=path.read_bytes(),  # noqa: ASYNC240
        media_type=prefs.avatar_mime_type,
    )


@router.post("/api/preferences/avatar", response_model=PreferencesOut)
async def upload_avatar(
    request: Request,
    file: Annotated[UploadFile, File(description="Avatar image file.")],
) -> PreferencesOut:
    """Upload a new avatar image.

    Accepts ``multipart/form-data`` with a single ``file`` field. The
    MIME type must be one of ``image/jpeg``, ``image/png``,
    ``image/gif``, or ``image/webp``; anything else is rejected with
    415. The file may not exceed :data:`MAX_AVATAR_SIZE_BYTES`; a
    larger body is rejected with 413.

    The previous avatar (if any) is replaced atomically: the new file
    is written, then the DB row is updated.
    """
    db = _db(request)
    avatars_root = _avatars_root(request)

    # Validate MIME type at the boundary.
    mime_type = (file.content_type or "").split(";")[0].strip().lower()
    if mime_type not in AVATAR_ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"unsupported avatar MIME type {mime_type!r}; "
                f"allowed: {sorted(AVATAR_ALLOWED_MIME_TYPES)}"
            ),
        )

    # Read body with size guard.
    body = await file.read()
    if len(body) > MAX_AVATAR_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"avatar exceeds {MAX_AVATAR_SIZE_BYTES} bytes ({len(body)} received)"),
        )
    if len(body) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="avatar file body is empty",
        )

    # Write to disk.
    dest = avatars_root / "current"
    dest.write_bytes(body)

    # Persist path + mime type.
    prefs = await prefs_db.patch_preferences(
        db,
        avatar_path=str(dest),
        avatar_mime_type=mime_type,
        fields=frozenset({"avatar_path", "avatar_mime_type"}),
    )
    return _to_out(prefs)


@router.delete("/api/preferences/avatar", response_model=PreferencesOut)
async def delete_avatar(request: Request) -> PreferencesOut:
    """Remove the current avatar and clear the DB fields.

    Returns the updated preferences row. A no-op (no avatar set) is
    treated as success (idempotent DELETE).
    """
    db = _db(request)
    prefs = await prefs_db.get_preferences(db)

    if prefs.avatar_path is not None:
        path = Path(prefs.avatar_path)
        if path.exists():  # noqa: ASYNC240
            path.unlink()  # noqa: ASYNC240

    updated = await prefs_db.patch_preferences(
        db,
        avatar_path=None,
        avatar_mime_type=None,
        fields=frozenset({"avatar_path", "avatar_mime_type"}),
    )
    return _to_out(updated)


# ---------------------------------------------------------------------------
# Sync from system ($USER + ~/.face)
# ---------------------------------------------------------------------------


@router.post("/api/preferences/sync_from_system", response_model=PreferencesOut)
async def sync_from_system(request: Request) -> PreferencesOut:
    """Populate display_name and avatar from the running user environment.

    * ``display_name`` ← ``$USER`` (falls back to ``$LOGNAME``, then
      ``$USERNAME``; empty string is treated as "not set").
    * avatar ← ``~/.face`` when that file exists and is ≤
      :data:`MAX_AVATAR_SIZE_BYTES`.  The MIME type is guessed from
      the file's magic header (first 4 bytes); unrecognised formats
      are stored with ``image/jpeg`` as the fallback.

    Fields are written unconditionally — a subsequent sync always
    refreshes both values. Returns the updated preferences row.
    """
    db = _db(request)
    avatars_root = _avatars_root(request)

    # --- display_name from $USER / $LOGNAME / $USERNAME ---
    raw_user = (
        os.environ.get("USER") or os.environ.get("LOGNAME") or os.environ.get("USERNAME") or ""
    )
    display_name: str | None = raw_user.strip()[:DISPLAY_NAME_MAX_LENGTH] or None

    # --- avatar from ~/.face ---
    face_path = Path.home() / ".face"
    new_avatar_path: str | None = None
    new_avatar_mime: str | None = None

    if face_path.exists() and face_path.is_file():
        face_bytes = face_path.read_bytes()
        if 0 < len(face_bytes) <= MAX_AVATAR_SIZE_BYTES:
            # Detect MIME from magic header.
            new_avatar_mime = _sniff_image_mime(face_bytes)
            dest = avatars_root / "current"
            dest.write_bytes(face_bytes)
            new_avatar_path = str(dest)

    fields: frozenset[str] = frozenset({"display_name", "avatar_path", "avatar_mime_type"})
    prefs = await prefs_db.patch_preferences(
        db,
        display_name=display_name,
        avatar_path=new_avatar_path,
        avatar_mime_type=new_avatar_mime,
        fields=fields,
    )
    return _to_out(prefs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sniff_image_mime(data: bytes) -> str:
    """Return an image MIME type guessed from ``data``'s first bytes.

    Only checks the magic header bytes for the four formats Bearings
    accepts (JPEG, PNG, GIF, WebP). Returns ``"image/jpeg"`` for any
    unrecognised format to ensure the DB always has a valid MIME type.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # JPEG: FF D8 (all valid JPEG streams start with this marker).
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    # Unknown — default to JPEG as the most common avatar format.
    return "image/jpeg"


# Re-export for ``app.py``'s ``from bearings.web.routes.preferences import
# router`` — no change needed there.
__all__ = ["router"]
