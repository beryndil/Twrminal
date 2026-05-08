"""Pending-operations REST endpoints (gap-cycle-03-010).

Thin HTTP adapter over :mod:`bearings.bearings_dir.pending`.  All
``.bearings/pending.toml`` I/O — including the POSIX-atomic write — lives
in the domain layer; this module maps domain exceptions to HTTP status
codes and nothing else.

Routes:

* ``POST /api/pending/{name}/resolve`` — remove the named entry (resolved
  semantic).  Returns 204 on success; 404 when the name is absent.

* ``DELETE /api/pending/{name}`` — remove the named entry (dismissed
  semantic).  Behaviorally identical to the resolve endpoint; v0.17.x
  distinguished resolved vs dismissed via a flag, v1 does not.

Error responses:

* 404 — the named op is not present (or the file does not exist).
* 500 — OS-level write failure.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status

from bearings.bearings_dir import pending as bdir_pending

router = APIRouter()


def _remove(directory: str, name: str) -> None:
    """Delegate op removal to the domain layer, mapping exceptions to HTTP."""
    try:
        bdir_pending.remove_op(Path(directory), name)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no pending op named {name!r}",
        ) from None
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"could not update pending.toml: {exc}",
        ) from exc


@router.post(
    "/api/pending/{name}/resolve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a pending operation as resolved",
    description=(
        "Removes the named entry from ``.bearings/pending.toml`` for "
        "the given project directory and persists the file. Returns 204 "
        "on success; 404 when the name is absent."
    ),
    operation_id="resolve-pending-op",
)
async def resolve_pending_op(
    name: str,
    directory: str = Query(..., description="Absolute path to the project root."),
) -> None:
    """Remove the named pending operation (resolved semantic)."""
    _remove(directory, name)


@router.delete(
    "/api/pending/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dismiss a pending operation",
    description=(
        "Removes the named entry from ``.bearings/pending.toml`` for "
        "the given project directory and persists the file. Behaviorally "
        "identical to the resolve endpoint. Returns 204 on success; 404 "
        "when the name is absent."
    ),
    operation_id="delete-pending-op",
)
async def delete_pending_op(
    name: str,
    directory: str = Query(..., description="Absolute path to the project root."),
) -> None:
    """Remove the named pending operation (dismissed semantic)."""
    _remove(directory, name)


__all__ = ["router"]
