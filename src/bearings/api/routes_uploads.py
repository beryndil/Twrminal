"""File upload bridge for browser drag-and-drop.

Chrome on Wayland strips the `text/uri-list` path metadata from file
drops even though `DataTransfer.files` still carries the bytes. The
frontend reads those bytes, POSTs them here, and the server persists
them to a UUID-named file under the configured upload directory. The
resulting absolute path is injected into the prompt — Claude reads
the file from disk exactly as if the user had typed the path by hand.

Security posture: Bearings is localhost/single-user. The endpoint
accepts any file up to the configured size cap; a short extension
blocklist rejects shell scripts and binaries as defense-in-depth
(Claude has no business being handed those via a drag gesture, and
the rare legitimate case can go through the native picker instead).

Original filenames are treated as untrusted input: only the extension
is preserved, and only if it matches a safe shape — alphanumerics
with length ≤16. The on-disk name is always a UUID so a malicious
filename like `../../etc/passwd` can't escape the upload directory
and two drops of `screenshot.png` don't collide.

No transcript persistence in v1 — the uploaded file's path is the
whole UX. GC is deferred; see TODO.md.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from bearings.api.auth import require_auth
from bearings.api.models import UploadOut

router = APIRouter(
    prefix="/uploads",
    tags=["uploads"],
    dependencies=[Depends(require_auth)],
)

# Only `.xxx` where `xxx` is alphanumeric and ≤16 chars is preserved.
# Anything weirder (multi-dot, unicode, punctuation) is dropped — if
# the original filename had a genuinely useful extension it'll still
# match this shape, and if it didn't, the file is saved without one
# rather than with a malformed suffix that trips downstream tools.
_EXT_ALLOWED_SHAPE = re.compile(r"^\.[A-Za-z0-9]{1,16}$")

_DEFAULT_MIME = "application/octet-stream"

# Streaming chunk size for the size-cap loop. 1 MiB balances syscall
# overhead against the max memory a single read holds. The cap is
# enforced as bytes arrive so a client that lies about Content-Length
# still hits the limit in bounded memory.
_CHUNK_SIZE = 1 << 20


def _safe_extension(filename: str, blocked: set[str]) -> str:
    """Extract the extension from `filename`. Returns the lowercased
    suffix (including the leading dot) when it's a safe shape AND not
    in the blocklist; otherwise returns an empty string.

    `Path(filename).suffix` neutralises traversal payloads — even if
    `filename` is `../../etc/passwd.sh`, `suffix` is just `.sh`, and
    we only ever consult the suffix. The on-disk name never uses any
    other part of the user-supplied filename.
    """
    suffix = Path(filename).suffix
    if not suffix:
        return ""
    if not _EXT_ALLOWED_SHAPE.match(suffix):
        return ""
    lowered = suffix.lower()
    if lowered in blocked:
        return ""
    return lowered


@router.post("", response_model=UploadOut)
async def upload_file(request: Request, file: UploadFile) -> UploadOut:
    """Persist the uploaded bytes under the configured upload dir and
    return the absolute path. Size cap is enforced while reading so a
    client that lies about Content-Length can't blow up server memory.

    The route auto-creates the upload directory on first call (XDG
    data home by default). Enforcement order: extension check first
    (cheap, rejects before any bytes land on disk), then streaming
    write with a size cap that tears down the partial file on reject.
    """
    settings = request.app.state.settings
    cfg = settings.uploads
    max_bytes = cfg.max_size_mb * 1024 * 1024
    blocked = {e.lower() for e in cfg.blocked_extensions}

    original_name = file.filename or "upload"
    requested_suffix = Path(original_name).suffix
    ext = _safe_extension(original_name, blocked)

    # Differentiate "had no extension, don't need one" (accept,
    # save without a suffix) from "had an extension we refused"
    # (reject with 415 so the caller knows why). Silently stripping
    # a blocked extension would land the file on disk with a
    # misleading name, which is the exact failure mode the blocklist
    # exists to prevent.
    if requested_suffix and not ext:
        raise HTTPException(
            status_code=415,
            detail=f"extension not allowed: {requested_suffix}",
        )

    upload_dir = Path(cfg.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest_name = f"{uuid.uuid4().hex}{ext}"
    dest = upload_dir / dest_name

    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"file exceeds {cfg.max_size_mb} MB limit",
                    )
                out.write(chunk)
    except HTTPException:
        # Don't leave half-written rejects on disk — the caller sees
        # an error and will not retry with the server path.
        dest.unlink(missing_ok=True)
        raise
    except OSError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="failed to persist upload") from exc

    return UploadOut(
        path=str(dest),
        # Strip any path components from the display name — the on-disk
        # name is a UUID anyway, this is just what the UI shows.
        filename=Path(original_name).name,
        size_bytes=size,
        mime_type=file.content_type or _DEFAULT_MIME,
    )
