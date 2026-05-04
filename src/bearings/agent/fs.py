"""Filesystem walker — list + read with realpath allow-roots enforcement.

Per ``docs/architecture-v1.md`` §1.1.5 ``web/routes/fs.py`` is the
general-purpose FS-picker walker (distinct from the plan/todo-only
vault index per ``docs/behavior/vault.md``). This agent module owns
the path-validation and stat/read helpers; the route layer is a thin
boundary that maps the dataclass return shapes to wire DTOs.

Path-safety contract
--------------------

Every input absolute path is resolved via ``Path.resolve(strict=False)``
(``os.path.realpath`` semantics — ``..``, symlinks, ``//`` are all
collapsed in one pass). The resolved path's string representation
must start with one of the allow-roots' resolved string
representations, with a path separator boundary check so
``/safe/root`` does not match ``/safe/rooted-evil``.

The validator returns the resolved :class:`pathlib.Path`. The route
layer consumes the resolved path for ``os.stat`` / ``open`` calls so
TOCTOU windows are minimised — there is no second resolve between
validate and use.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from bearings.config.constants import (
    FS_ENTRY_KIND_DIR,
    FS_ENTRY_KIND_FILE,
    FS_ENTRY_KIND_OTHER,
    FS_ENTRY_KIND_SYMLINK,
    KNOWN_FS_ENTRY_KINDS,
)


class FsValidationError(ValueError):
    """Raised when the validator rejects a path.

    Carries a ``status_code`` hint the route layer uses to map the
    error to an HTTP status — 400 for malformed input, 403 for
    outside-roots, 404 for missing.
    """

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class FsEntry:
    """One directory entry returned by :func:`list_dir`."""

    name: str
    kind: str
    size: int
    mtime: float
    is_readable: bool

    def __post_init__(self) -> None:
        if self.kind not in KNOWN_FS_ENTRY_KINDS:
            raise ValueError(f"FsEntry.kind {self.kind!r} not in {sorted(KNOWN_FS_ENTRY_KINDS)}")


@dataclass(frozen=True)
class FsListing:
    """Directory listing + capped flag."""

    path: str
    entries: tuple[FsEntry, ...]
    capped: bool


@dataclass(frozen=True)
class FsRead:
    """File-read result with truncation flag."""

    path: str
    content: str
    size: int
    truncated: bool


def _kind_for(path: Path) -> str:
    """Classify a path into the kind alphabet."""
    if path.is_symlink():
        # ``is_symlink`` is checked first so a broken symlink doesn't
        # fall through to ``is_dir`` / ``is_file`` (which follow
        # symlinks and would report ``False`` on a broken link).
        return FS_ENTRY_KIND_SYMLINK
    if path.is_dir():
        return FS_ENTRY_KIND_DIR
    if path.is_file():
        return FS_ENTRY_KIND_FILE
    return FS_ENTRY_KIND_OTHER


def validate_path(raw: str, allow_roots: Iterable[Path]) -> Path:
    """Resolve ``raw`` and enforce it lives under one of ``allow_roots``.

    The resolution is unconditional: every input is normalised
    through :meth:`Path.resolve` so ``..`` and symlink escapes are
    collapsed before the allow-roots check.

    Raises :class:`FsValidationError` with ``status_code``:

    * 400 when ``raw`` is empty or not absolute.
    * 403 when the resolved path is outside every allow-root, OR when
      ``allow_roots`` is empty (no FS surface configured).
    """
    if not raw:
        raise FsValidationError("path must be non-empty", status_code=400)
    if not raw.startswith("/"):
        # Reject relative paths at the boundary — no implicit
        # "relative to what?" guess. A user who wants the cwd should
        # supply the absolute form.
        raise FsValidationError(f"path must be absolute (got {raw!r})", status_code=400)
    resolved = Path(raw).resolve(strict=False)
    resolved_str = str(resolved)
    roots = tuple(allow_roots)
    if not roots:
        raise FsValidationError("no fs allow-roots configured", status_code=403)
    for root in roots:
        root_resolved = root.resolve(strict=False)
        root_str = str(root_resolved)
        # Filesystem root (``/``) is the explicit "allow every absolute
        # path" sentinel — used by the picker fallback when no TOML
        # config narrows the surface. Special-cased because the
        # ``root_str + os.sep`` boundary check below would compare to
        # ``"//"`` and reject every real path.
        if root_str == os.sep:
            return resolved
        # Boundary check: either equal, or starts with ``root_str + os.sep``
        # so ``/safe/root`` does not match ``/safe/rooted-evil``.
        if resolved_str == root_str:
            return resolved
        if resolved_str.startswith(root_str + os.sep):
            return resolved
    raise FsValidationError(
        f"path {raw!r} is outside the configured fs allow-roots",
        status_code=403,
    )


def list_dir(resolved: Path, max_entries: int) -> FsListing:
    """List ``resolved`` as a directory, capped at ``max_entries``.

    Raises :class:`FsValidationError` with status 404 if ``resolved``
    does not exist, 422 if it is not a directory.
    """
    if not resolved.exists():
        raise FsValidationError(f"path {str(resolved)!r} not found", status_code=404)
    if not resolved.is_dir():
        raise FsValidationError(f"path {str(resolved)!r} is not a directory", status_code=422)
    entries: list[FsEntry] = []
    capped = False
    # ``iterdir`` is stable enough; sort by name so the wire shape is
    # deterministic across calls.
    children = sorted(resolved.iterdir(), key=lambda p: p.name)
    for child in children:
        if len(entries) >= max_entries:
            capped = True
            break
        try:
            stat = child.lstat()
            size = int(stat.st_size)
            mtime = float(stat.st_mtime)
        except OSError:
            # Unreadable child — surface as an "other" entry rather
            # than crashing the listing. Mirrors vault.md's
            # "doesn't crash the index" tolerance.
            entries.append(
                FsEntry(
                    name=child.name,
                    kind=FS_ENTRY_KIND_OTHER,
                    size=0,
                    mtime=0.0,
                    is_readable=False,
                )
            )
            continue
        is_readable = os.access(child, os.R_OK)
        entries.append(
            FsEntry(
                name=child.name,
                kind=_kind_for(child),
                size=size,
                mtime=mtime,
                is_readable=is_readable,
            )
        )
    return FsListing(
        path=str(resolved),
        entries=tuple(entries),
        capped=capped,
    )


def read_text(resolved: Path, max_bytes: int) -> FsRead:
    """Read ``resolved`` as utf-8 text, capped at ``max_bytes``.

    Raises :class:`FsValidationError` with status 404 if missing, 422
    if not a regular file, 413 if the file is larger than
    ``max_bytes``.
    """
    if not resolved.exists():
        raise FsValidationError(f"path {str(resolved)!r} not found", status_code=404)
    if not resolved.is_file():
        raise FsValidationError(f"path {str(resolved)!r} is not a regular file", status_code=422)
    size = int(resolved.stat().st_size)
    if size > max_bytes:
        raise FsValidationError(
            f"path {str(resolved)!r} is {size} bytes (cap {max_bytes})",
            status_code=413,
        )
    body = resolved.read_bytes()
    # ``errors="replace"`` so a stray non-utf-8 byte does not crash
    # the decoder; the caller can detect a binary file from the
    # presence of replacement chars.
    text = body.decode("utf-8", errors="replace")
    return FsRead(
        path=str(resolved),
        content=text,
        size=size,
        truncated=False,
    )


__all__ = [
    "FsEntry",
    "FsListing",
    "FsRead",
    "FsValidationError",
    "list_dir",
    "read_text",
    "validate_path",
]
