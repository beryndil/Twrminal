"""Filesystem listing for the folder- and file-picker UIs.

Lists directories under an absolute path so the FolderPicker and
FilePickerModal can walk the tree without relying on a browser-side
file dialog (which can't access server-side paths). Read-only; no
write or execute semantics.

Security posture: Bearings binds 127.0.0.1 by default and is a
single-user tool. Exposing directory and filenames to the local
browser is equivalent to the user running `ls` in a terminal — not a
meaningful disclosure.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from bearings.api.auth import require_auth
from bearings.api.models import FsEntryOut, FsListOut

router = APIRouter(
    prefix="/fs",
    tags=["fs"],
    dependencies=[Depends(require_auth)],
)


def _list_dir(path: Path, *, hidden: bool, include_files: bool) -> FsListOut:
    """Assemble an FsListOut for an already-resolved directory. Caller
    is responsible for validating that `path` exists and is a dir.

    `include_files=False` is the historical FolderPicker contract —
    only directories are returned. `include_files=True` adds regular
    files so the in-app FilePickerModal can render them alongside dirs.
    Special entries (sockets, fifos, devices) are filtered out either
    way — they're never useful to hand to Claude.
    """
    entries: list[FsEntryOut] = []
    for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
        if not hidden and child.name.startswith("."):
            continue
        try:
            is_dir = child.is_dir()
            is_file = child.is_file()
        except OSError:
            # Broken symlink or racing deletion — skip rather than 500
            # the whole listing.
            continue
        if is_dir:
            entries.append(FsEntryOut(name=child.name, path=str(child), is_dir=True))
        elif include_files and is_file:
            entries.append(FsEntryOut(name=child.name, path=str(child), is_dir=False))
    parent = str(path.parent) if path.parent != path else None
    return FsListOut(path=str(path), parent=parent, entries=entries)


@router.get("/list", response_model=FsListOut)
async def list_dir(
    path: str | None = None,
    hidden: bool = False,
    include_files: bool = False,
) -> FsListOut:
    target = Path(path) if path else Path.home()
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="path must be absolute")
    try:
        resolved = target.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="path not found") from exc
    if not resolved.is_dir():
        raise HTTPException(status_code=404, detail="path is not a directory")
    try:
        return _list_dir(resolved, hidden=hidden, include_files=include_files)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="permission denied") from exc
