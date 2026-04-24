"""Agent-authored artifact surface for inline UI display.

URL shape:

  POST   /sessions/{session_id}/artifacts        — register an on-disk file
  GET    /sessions/{session_id}/artifacts        — list newest-first
  GET    /artifacts/{artifact_id}                — stream bytes inline
  DELETE /sessions/{session_id}/artifacts/{aid}  — drop row (bytes untouched)

This is the outbound counterpart to `routes_uploads.py`: uploads carry
browser bytes *to* the agent via drag-and-drop; artifacts carry
agent-authored files *back* to the browser so the Conversation view can
render them inline. The agent writes a file it wants to show (image,
PDF, generated HTML report), POSTs the absolute path here, and the
server validates the path is under `settings.artifacts.serve_roots`,
stats it, hashes it, inserts a row, and returns a stable
`/api/artifacts/{id}` URL. The agent embeds that URL in its reply
(`![diagram](/api/artifacts/abc123)`); the existing markdown renderer's
`<img>` allowlist makes it render inline without any frontend changes.

Security posture: Bearings is localhost/single-user behind auth. The
register-time allowlist is the primary gate — a path outside the
configured roots never lands in the table. Serve-time re-validation
runs the same check against current config, so narrowing
`serve_roots` in `config.toml` revokes access to previously-registered
artifacts on the next request rather than needing a DB purge. Path
traversal is neutralised via `Path.resolve()` before the allowlist
check, so a symlink planted under a root can't escape.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from bearings.api.auth import require_auth
from bearings.api.models import ArtifactOut, ArtifactRegister
from bearings.config import Settings
from bearings.db import store

# Per-session CRUD. Scoped under a session so list/delete naturally
# 404 on cross-session access, mirroring routes_checkpoints.py.
session_router = APIRouter(
    prefix="/sessions/{session_id}/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)

# Global read surface. The browser hits `/api/artifacts/{id}` from
# markdown `<img src>` without knowing the session id; keeping this
# router flat avoids pushing session ids into every artifact URL.
serve_router = APIRouter(
    prefix="/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(require_auth)],
)

# Streaming chunk size for the hash loop. Matches routes_uploads'
# chunk — large enough to amortize syscall overhead, small enough to
# keep peak memory bounded when an agent registers a 100 MB file.
_HASH_CHUNK_BYTES = 1 << 20

# Last-resort MIME when detection fails. Browsers will still render
# images/PDFs correctly when served as `octet-stream` if the markdown
# is an `<img>` / `<embed>`, but the download filename preserves the
# extension so the user-agent can re-detect locally.
_DEFAULT_MIME = "application/octet-stream"

# Extension overrides where mimetypes.guess_type is unreliable or too
# generic. Intentionally narrow — add only types we care about rendering
# inline. The detector runs first; this map wins only on a miss.
_EXT_MIME_OVERRIDES: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".avif": "image/avif",
}


def _resolve_serve_roots(settings: Settings) -> list[Path]:
    """Expand the configured serve roots to resolved absolute paths.

    Resolving here — not at config load — keeps the behaviour tied to
    the filesystem at the moment of the check, so a symlink that flips
    after settings were loaded doesn't grant access to the wrong tree.
    `strict=False` lets us accept not-yet-created roots (the artifacts
    dir is auto-created on first register)."""
    return [Path(root).resolve(strict=False) for root in settings.artifacts.serve_roots]


def _path_under_allowlist(candidate: Path, roots: list[Path]) -> bool:
    """True iff `candidate` (already resolved) lives under at least one
    resolved root. `is_relative_to` returns False on mismatch rather
    than raising, which is what we want."""
    return any(candidate.is_relative_to(root) for root in roots)


def _detect_mime(path: Path, override: str | None) -> str:
    """Pick a Content-Type for `path`.

    Order:
      1. mimetypes.guess_type — fastest, catches the common cases.
      2. `_EXT_MIME_OVERRIDES` — narrow map for the types the stdlib
         guesser misses or gets wrong (markdown, svg variants).
      3. Caller-supplied `override` — only used when detection fails.
      4. `_DEFAULT_MIME` — the safe fallback; a consumer can still
         render the bytes, it just won't auto-preview."""
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed:
        return guessed
    ext = path.suffix.lower()
    if ext in _EXT_MIME_OVERRIDES:
        return _EXT_MIME_OVERRIDES[ext]
    if override:
        return override
    return _DEFAULT_MIME


def _hash_file(path: Path) -> tuple[str, int]:
    """Stream `path` through SHA-256 and count bytes. One pass over
    the file — the stat-based size would be racy against concurrent
    writers, and a content hash pins the row to the exact bytes that
    were present at register time."""
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


async def _require_session(request: Request, session_id: str) -> dict[str, Any]:
    """Resolve the session row or raise 404. Matches the pattern in
    routes_checkpoints.py so delete/list semantics are uniform."""
    session = await store.get_session(request.app.state.db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _to_out(row: dict[str, Any]) -> ArtifactOut:
    """Project a DB row to the wire DTO, attaching the serve URL. Done
    here rather than in Pydantic so the URL stays a server-controlled
    concern (change the mount prefix once, no client scramble)."""
    return ArtifactOut(
        id=row["id"],
        session_id=row["session_id"],
        filename=row["filename"],
        mime_type=row["mime_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        created_at=row["created_at"],
        url=f"/api/artifacts/{row['id']}",
    )


@session_router.post("", response_model=ArtifactOut, status_code=201)
async def register_artifact(
    session_id: str, body: ArtifactRegister, request: Request
) -> ArtifactOut:
    """Validate `body.path`, hash it, and insert an artifact row.

    Errors:
      400 — path is not absolute OR not under `serve_roots`.
      404 — session doesn't exist, or the path doesn't exist on disk.
      413 — file exceeds `max_register_size_mb`.
    """
    await _require_session(request, session_id)
    settings: Settings = request.app.state.settings
    cfg = settings.artifacts

    candidate = Path(body.path)
    if not candidate.is_absolute():
        raise HTTPException(status_code=400, detail="path must be absolute")

    resolved = candidate.resolve(strict=False)
    roots = _resolve_serve_roots(settings)
    if not _path_under_allowlist(resolved, roots):
        raise HTTPException(
            status_code=400,
            detail="path is not under any configured artifacts serve root",
        )

    if not resolved.is_file():
        # Covers missing file + "exists but is a directory / symlink to
        # nowhere / socket". Hashing a non-file would raise downstream;
        # catching it here gives Claude a clear 404.
        raise HTTPException(status_code=404, detail="file not found on disk")

    max_bytes = cfg.max_register_size_mb * 1024 * 1024
    try:
        stat_size = resolved.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=404, detail="file not found on disk") from exc
    if stat_size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"file exceeds {cfg.max_register_size_mb} MB artifact limit",
        )

    digest, hashed_size = _hash_file(resolved)
    # `hashed_size` is authoritative — the stat-based check above is
    # just a cheap early reject. Keep the two in sync when persisting
    # so consumers reading size from the DB match the bytes the hash
    # covers.
    filename = body.filename or resolved.name or "artifact"
    mime_type = _detect_mime(resolved, body.mime_type)

    row = await store.create_artifact(
        request.app.state.db,
        session_id,
        path=str(resolved),
        filename=filename,
        mime_type=mime_type,
        size_bytes=hashed_size,
        sha256=digest,
    )
    return _to_out(row)


@session_router.get("", response_model=list[ArtifactOut])
async def list_session_artifacts(session_id: str, request: Request) -> list[ArtifactOut]:
    """Every artifact the agent registered for this session, newest
    first. 404 on unknown session; empty list means "session exists,
    nothing registered yet"."""
    await _require_session(request, session_id)
    rows = await store.list_artifacts(request.app.state.db, session_id)
    return [_to_out(row) for row in rows]


@session_router.delete("/{artifact_id}", status_code=204)
async def delete_artifact(session_id: str, artifact_id: str, request: Request) -> Response:
    """Drop the row. Bytes on disk are untouched — retention sweep
    cleans those up (shared with uploads). Scoping by `session_id` in
    the URL prevents a caller from deleting an artifact that belongs
    to a different session by guessing its id."""
    row = await store.get_artifact(request.app.state.db, artifact_id)
    if row is None or row["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="artifact not found")
    ok = await store.delete_artifact(request.app.state.db, artifact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="artifact not found")
    return Response(status_code=204)


@serve_router.get("/{artifact_id}")
async def serve_artifact(artifact_id: str, request: Request, download: int = 0) -> FileResponse:
    """Stream the artifact bytes back. Inline disposition by default so
    `<img src="/api/artifacts/..."/>` and `<iframe>` preview work
    without the browser forcing a download dialog. Pass `?download=1`
    to flip to attachment disposition for a real "save as" link.

    Re-runs the path allowlist check against current config. A
    previously-valid artifact whose path is no longer served (config
    narrowed, file moved outside the roots) yields 404 with the same
    detail as a missing row, so narrowing settings is equivalent to
    revocation from the browser's point of view.
    """
    settings: Settings = request.app.state.settings
    row = await store.get_artifact(request.app.state.db, artifact_id)
    if row is None:
        raise HTTPException(status_code=404, detail="artifact not found")

    path = Path(row["path"])
    resolved = path.resolve(strict=False)
    roots = _resolve_serve_roots(settings)
    if not _path_under_allowlist(resolved, roots):
        raise HTTPException(status_code=404, detail="artifact not found")

    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")

    disposition = "attachment" if download else "inline"
    headers = {
        "Content-Disposition": f'{disposition}; filename="{row["filename"]}"',
    }
    return FileResponse(
        path=str(resolved),
        media_type=row["mime_type"],
        headers=headers,
    )


# Backwards-compatible export names — server.py imports `router` for
# each routes module, but this file has two. Expose both explicitly
# so the server wiring is unambiguous.
__all__ = ["session_router", "serve_router"]
