# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/reorg.py`` (gap-cycle-03-008/009).

Mirrors :class:`bearings.db.reorg.ReorgAudit`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReorgAuditOut(BaseModel):
    """Response body for one merge-operation audit record."""

    model_config = ConfigDict(extra="forbid")

    id: str
    dst_session_id: str
    src_session_id: str
    merged_at: str
    src_title: str
    boundary_msg_id: str | None


class ReorgAuditListOut(BaseModel):
    """Response body for ``GET /api/sessions/{id}/reorg/audits``."""

    model_config = ConfigDict(extra="forbid")

    items: list[ReorgAuditOut]


class UndoMergeOut(BaseModel):
    """Response body for a successful undo (``DELETE /api/sessions/{id}/reorg/audits/{auditId}``).

    ``new_session_id`` is the id of the newly created session that
    holds the re-parented messages from the reversed merge.
    """

    model_config = ConfigDict(extra="forbid")

    new_session_id: str
