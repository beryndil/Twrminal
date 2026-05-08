# mypy: disable-error-code=explicit-any
"""Pending-operations backing logic for ``web/routes/pending.py`` (arch §1.1.6).

This module owns all ``.bearings/pending.toml`` I/O.  The web route is a
thin HTTP adapter that calls :func:`remove_op` and maps the domain
exceptions to HTTP status codes.

All writes go through :func:`~bearings.bearings_dir.io.write_toml` which
uses ``tempfile.NamedTemporaryFile`` + ``os.replace()`` (POSIX-atomic), so
a crash mid-write cannot corrupt the pending file.

Pydantic carve-out
------------------
``tomllib`` returns ``dict[str, Any]``; the pragma is needed at this
boundary.

Layer isolation
---------------
No imports from ``bearings.agent.*``, ``bearings.web.*``, or
``bearings.cli.*`` per arch §3 line 549.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bearings.bearings_dir import io as bdir_io
from bearings.config.constants import (
    BEARINGS_DIR_PENDING_FILENAME,
    BEARINGS_DIR_SUBDIR,
)


def _pending_path(directory: Path) -> Path:
    """Return the canonical path for ``pending.toml`` under *directory*."""
    return directory / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_PENDING_FILENAME


def load_ops(directory: Path) -> tuple[Path, dict[str, Any]]:
    """Read ``.bearings/pending.toml`` and return ``(path, ops_dict)``.

    *ops_dict* is the ``ops`` sub-table (empty dict when the file does not
    exist or has no ``[ops]`` table).  The returned *path* is the canonical
    ``pending.toml`` location; callers that need to write back use
    :func:`save_ops` rather than opening the path themselves.
    """
    path = _pending_path(directory)
    data = bdir_io.read_toml(path)
    ops: dict[str, Any] = dict(data.get("ops", {}))
    return path, ops


def save_ops(path: Path, ops: dict[str, Any]) -> None:
    """Atomically write *ops* back to *path* as a TOML ``[ops.*]`` structure.

    When *ops* is empty the file is written as an empty TOML document so
    that a subsequent :func:`load_ops` call returns an empty dict (rather
    than a 404 sentinel).

    Raises :exc:`OSError` on filesystem write failures.
    """
    payload: dict[str, Any] = {"ops": ops} if ops else {}
    bdir_io.write_toml(path, payload)


def remove_op(directory: Path, name: str) -> None:
    """Remove the named op from ``.bearings/pending.toml`` and persist.

    Raises :exc:`KeyError` when *name* is not present (including when
    the file does not exist — an absent file is treated identically to
    an empty ``[ops]`` table).

    Raises :exc:`OSError` on filesystem write failures.
    """
    path, ops = load_ops(directory)
    if name not in ops:
        raise KeyError(name)
    del ops[name]
    save_ops(path, ops)


__all__ = [
    "load_ops",
    "remove_op",
    "save_ops",
]
