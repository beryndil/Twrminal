"""Bridge from the SvelteKit UI to `.bearings/pending.toml` ops.

Phase 4a.1 of docs/context-menu-plan.md. Thin wrapper around
`bearings.bearings_dir.pending`; no new file format, no new locking,
no new validation — the module already owns flock'd read-modify-write
semantics and Pydantic-validated row shapes. The route layer just
translates HTTP requests into directory-scoped function calls and
coerces the return value to the shared `PendingOperation` schema.

Directory scope: every endpoint takes a `directory` query parameter
so the same `bearings` server can serve pending lists for multiple
checked-out project trees. The working-dir of the active session is
the natural source for this param, but the route itself is directory-
agnostic — it takes whatever absolute path the caller sends.

Consume-side note: the frontend UI that reads this endpoint is Phase
16 (out of scope for Phase 4a.1). We ship the routes now so the
backend surface is stable when the menu work catches up.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from bearings.api.auth import require_auth
from bearings.bearings_dir import pending as pending_ops
from bearings.bearings_dir.schema import PendingOperation

router = APIRouter(
    prefix="/pending",
    tags=["pending"],
    dependencies=[Depends(require_auth)],
)


# PATH_MAX-ish cap. A pending-op path exceeding this length is almost
# certainly garbage — real filesystem paths cap at 4096 on Linux, and
# refusing the occasional pathological input here keeps the route from
# feeding a ridiculous string into `Path(...).resolve()` downstream.
_MAX_DIR_CHARS = 4096


def _resolve_directory(raw: str) -> Path:
    """Coerce the `directory` query param into an absolute `Path`.

    Relative paths are rejected with 400 — the frontend always sends
    an absolute path (session.working_dir is absolute), and accepting
    relatives would resolve against whatever cwd `bearings serve` was
    launched with, which is surprising behavior the caller rarely
    wants. Non-existent paths are allowed: `list_ops` on a missing
    directory returns an empty list, and the frontend uses that for
    the "no `.bearings/` here yet" empty state."""
    if not raw:
        raise HTTPException(status_code=400, detail="directory is required")
    if len(raw) > _MAX_DIR_CHARS:
        raise HTTPException(status_code=400, detail="directory path too long")
    path = Path(raw)
    if not path.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="directory must be an absolute path",
        )
    return path


@router.get("", response_model=list[PendingOperation])
async def list_pending(
    directory: str = Query(..., description="Absolute path of the project directory"),
) -> list[PendingOperation]:
    """List every pending op under `.bearings/pending.toml` for the
    given directory, oldest-first. Empty list on a directory with no
    `.bearings/` — that's a meaningful "nothing pending here" signal,
    not an error."""
    return pending_ops.list_ops(_resolve_directory(directory))


@router.post("/{name}/resolve", response_model=PendingOperation)
async def resolve_pending(
    name: str,
    directory: str = Query(..., description="Absolute path of the project directory"),
) -> PendingOperation:
    """Clear the named pending op. 404 when no op with that name
    exists — unlike the underlying primitive (which returns `None`
    for idempotent retries), the HTTP shape needs a distinguishable
    "did you really mean that op?" signal so the UI can refresh the
    list rather than silently appearing to succeed on a stale id."""
    result = pending_ops.resolve(_resolve_directory(directory), name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"pending op not found: {name!r}")
    return result


@router.delete("/{name}", status_code=204)
async def delete_pending(
    name: str,
    directory: str = Query(..., description="Absolute path of the project directory"),
) -> Response:
    """Alias of `POST /{name}/resolve` without a response body — the
    semantic "remove this pending op" verb the frontend reaches for
    when the user clicks a delete icon rather than a resolve button.
    Also 404 on unknown name so bulk-delete UIs can surface a
    per-row failure."""
    result = pending_ops.resolve(_resolve_directory(directory), name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"pending op not found: {name!r}")
    return Response(status_code=204)
