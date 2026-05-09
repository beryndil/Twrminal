# mypy: disable-error-code=explicit-any
"""Request model for POST /api/import/bearings."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class BearingsImportRequest(BaseModel):
    """Request body for the POST /api/import/bearings endpoint.

    The ``confirm`` flag is an explicit acknowledgement that a potentially
    destructive mass-import will run.  Omitting it or passing ``False``
    causes the route to return 400 without touching any data.
    """

    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    """Must be ``True`` to proceed.  Defaults to ``False`` so a bare POST
    without a body is safely rejected with 400."""

    source_dir: Path | None = None
    """Optional path to the source Bearings data directory.  When supplied,
    the route reads ``<source_dir>/db.sqlite``; when ``None`` the default
    location (``~/.local/share/bearings/``) is used."""


__all__ = ["BearingsImportRequest"]
