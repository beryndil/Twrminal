# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/reorg.py`` (gap-cycle-03-008).

Mirrors :class:`bearings.db.reorg.ReorgAudit`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReorgAuditOut(BaseModel):
    """Response body for a successful merge operation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    dst_session_id: str
    src_session_id: str
    merged_at: str
    src_title: str
    boundary_msg_id: str | None
