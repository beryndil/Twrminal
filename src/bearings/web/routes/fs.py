"""Filesystem-walk routes (item 1.10 + item 3.1).

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/fs.py`` is the
general-purpose FS picker (distinct from the plan/todo-only vault
index per ``docs/behavior/vault.md``):

* ``GET /api/fs/list?path=<abs>`` — directory entries.
* ``GET /api/fs/read?path=<abs>`` — utf-8 text body.
* ``POST /api/fs/pick`` — bootstrap a folder-picker session (item 3.1).

``list`` and ``read`` validate paths through
:func:`bearings.agent.fs.validate_path` (realpath resolution +
allow-roots boundary check) before opening anything.  ``pick``
applies the same validation but falls back to the user's home
directory as the effective root when ``allow_roots`` is empty — so
the picker works on default installations that have no TOML config.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, status

from bearings.agent.fs import (
    FsValidationError,
    list_dir,
    read_text,
    validate_path,
)
from bearings.config.settings import FsCfg
from bearings.web.models.fs import FsEntryOut, FsListOut, FsPickIn, FsPickOut, FsReadOut

router = APIRouter()


def _cfg(request: Request) -> FsCfg:
    """Pull the :class:`FsCfg` off ``app.state``; falls back to defaults."""
    cfg = getattr(request.app.state, "fs_cfg", None)
    if cfg is None:
        return FsCfg()
    if not isinstance(cfg, FsCfg):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="fs_cfg on app.state is not an FsCfg instance",
        )
    return cfg


@router.get("/api/fs/list", response_model=FsListOut)
async def get_list(
    request: Request,
    path: str = Query(..., description="Absolute path to list."),
) -> FsListOut:
    """List a directory under one of the configured allow-roots."""
    cfg = _cfg(request)
    try:
        resolved = validate_path(path, cfg.allow_roots)
        listing = list_dir(resolved, cfg.list_max_entries)
    except FsValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FsListOut(
        path=listing.path,
        entries=[
            FsEntryOut(
                name=e.name,
                kind=e.kind,
                size=e.size,
                mtime=e.mtime,
                is_readable=e.is_readable,
            )
            for e in listing.entries
        ],
        capped=listing.capped,
    )


@router.get("/api/fs/read", response_model=FsReadOut)
async def get_read(
    request: Request,
    path: str = Query(..., description="Absolute path to read as utf-8 text."),
) -> FsReadOut:
    """Read a file's content as utf-8 text under one of the allow-roots."""
    cfg = _cfg(request)
    try:
        resolved = validate_path(path, cfg.allow_roots)
        result = read_text(resolved, cfg.read_max_bytes)
    except FsValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FsReadOut(
        path=result.path,
        content=result.content,
        size=result.size,
        truncated=result.truncated,
    )


def _pick_roots(cfg: FsCfg) -> tuple[Path, ...]:
    """Effective allow-roots for the folder picker.

    When ``allow_roots`` is explicitly configured, honour it.  When the
    list is empty (fresh :class:`~bearings.config.settings.FsCfg` with
    no TOML config), fall back to filesystem root so the picker can
    navigate anywhere on a default single-user localhost install.
    Bearings ships in single-user localhost mode (no auth gate); the
    picker is user-driven and the alternative — locking to ``$HOME`` —
    rejects common working dirs like ``/tmp``, ``/srv``, ``/var/www``,
    or any other-user project tree the operator has read access to.
    This fallback only applies to ``POST /api/fs/pick``; ``GET
    /api/fs/list`` and ``GET /api/fs/read`` remain strict (they 403
    unless ``allow_roots`` is explicitly configured).
    """
    if cfg.allow_roots:
        return cfg.allow_roots
    return (Path("/"),)


@router.post("/api/fs/pick", response_model=FsPickOut, status_code=status.HTTP_200_OK)
async def post_pick(
    request: Request,
    body: FsPickIn,
) -> FsPickOut:
    """Bootstrap a folder-picker session.

    Validates ``body.root`` (or ``$HOME`` when omitted), returns the
    directory listing, and issues a fresh ``token`` UUID the client
    uses to identify the picker session.  Subsequent navigation steps
    repeat this endpoint with the new path — no separate traversal
    endpoint is needed.

    When ``fs.allow_roots`` is empty the endpoint accepts any path
    under the user's home directory so the picker is usable on
    default installations.
    """
    cfg = _cfg(request)
    roots = _pick_roots(cfg)
    raw = body.root if body.root else str(Path.home())
    try:
        resolved = validate_path(raw, roots)
        listing = list_dir(resolved, cfg.list_max_entries)
    except FsValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FsPickOut(
        token=str(uuid.uuid4()),
        path=listing.path,
        entries=[
            FsEntryOut(
                name=e.name,
                kind=e.kind,
                size=e.size,
                mtime=e.mtime,
                is_readable=e.is_readable,
            )
            for e in listing.entries
        ],
        capped=listing.capped,
    )


__all__ = ["router"]
