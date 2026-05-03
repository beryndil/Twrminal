# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/fs.py`` (item 1.10)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FsEntryOut(BaseModel):
    """One directory entry."""

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    size: int
    mtime: float
    is_readable: bool


class FsListOut(BaseModel):
    """Response shape for ``GET /api/fs/list``."""

    model_config = ConfigDict(extra="forbid")

    path: str
    entries: list[FsEntryOut]
    capped: bool


class FsReadOut(BaseModel):
    """Response shape for ``GET /api/fs/read``."""

    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    size: int
    truncated: bool


class FsPickIn(BaseModel):
    """Request body for ``POST /api/fs/pick``."""

    model_config = ConfigDict(extra="forbid")

    root: str = ""
    """Absolute path to list.  Empty string → server defaults to home dir."""


class FsPickOut(BaseModel):
    """Response shape for ``POST /api/fs/pick``."""

    model_config = ConfigDict(extra="forbid")

    token: str
    """Opaque UUID identifying this picker session (reserved for future
    server-side state; clients may ignore it for now)."""
    path: str
    entries: list[FsEntryOut]
    capped: bool


__all__ = ["FsEntryOut", "FsListOut", "FsPickIn", "FsPickOut", "FsReadOut"]
