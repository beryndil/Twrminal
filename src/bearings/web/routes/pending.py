# mypy: disable-error-code=explicit-any
"""Pending-operations REST endpoints (gap-cycle-03-010).

The ``mypy: disable-error-code=explicit-any`` pragma covers the
``dict[str, Any]`` surface exposed by ``tomllib.load()`` — the TOML
value type is structurally ``object`` but the stdlib stubs annotate
the return as ``dict[str, Any]``, and the parsed ops sub-table cannot
be narrowed further without a Pydantic round-trip that would duplicate
the frontend's TOML parser logic.

Manages ``.bearings/pending.toml`` for a project directory:

* ``POST /api/pending/{name}/resolve?directory=<abs>`` — removes the
  named entry from ``.bearings/pending.toml`` and persists the file.
  Returns 204 on success; 404 when the name is absent.

* ``DELETE /api/pending/{name}?directory=<abs>`` — behaviorally
  identical to resolve.  v0.17.x distinguished "resolved" from
  "dismissed" via a flag; v1 does not (both semantics write to the
  same store and the flag is not surfaced in the UI or the CLI).

Neither endpoint requires a DB connection — they operate on the
project-local ``.bearings/pending.toml`` file directly using the
Python 3.12 stdlib ``tomllib`` reader and the ``tomli-w`` writer.

Error responses:

* 404 — the named op is not present (or the file does not exist).
* 500 — OS-level write failure.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter()

_PENDING_TOML = ".bearings/pending.toml"


def _load_ops(directory: str) -> tuple[Path, dict[str, Any]]:
    """Read and parse ``.bearings/pending.toml``.

    Returns ``(path, ops_dict)`` where ``ops_dict`` is the ``ops``
    sub-table (an empty dict when the file does not exist or has no
    ``[ops]`` table).
    """
    path = Path(directory) / _PENDING_TOML
    if not path.exists():
        return path, {}
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    ops: dict[str, Any] = dict(data.get("ops", {}))
    return path, ops


def _save_ops(path: Path, ops: dict[str, Any]) -> None:
    """Write ``ops`` back to ``path`` as a TOML ``[ops.*]`` structure.

    When ``ops`` is empty the file is left as empty bytes so the
    frontend's 200-with-empty-content path returns ``[]`` without
    needing a 404 sentinel.
    """
    payload: dict[str, Any] = {"ops": ops} if ops else {}
    with path.open("wb") as fh:
        tomli_w.dump(payload, fh)


def _remove_op(directory: str, name: str) -> None:
    """Remove ``name`` from ``.bearings/pending.toml`` and persist.

    Raises :exc:`KeyError` when the name is not present.
    Raises :exc:`OSError` on filesystem write failures.
    """
    path, ops = _load_ops(directory)
    if name not in ops:
        raise KeyError(name)
    del ops[name]
    _save_ops(path, ops)


@router.post(
    "/api/pending/{name}/resolve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a pending operation as resolved",
    description=(
        "Removes the named entry from ``.bearings/pending.toml`` for "
        "the given project directory and persists the file. Returns 204 "
        "on success; 404 when the name is absent."
    ),
)
async def resolve_pending_op(
    name: str,
    directory: str = Query(..., description="Absolute path to the project root."),
) -> None:
    """Remove the named pending operation (resolved semantic)."""
    try:
        _remove_op(directory, name)
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
)
async def delete_pending_op(
    name: str,
    directory: str = Query(..., description="Absolute path to the project root."),
) -> None:
    """Remove the named pending operation (dismissed semantic)."""
    try:
        _remove_op(directory, name)
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


__all__ = ["router"]
