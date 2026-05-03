# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/approvals.py`` (Slice A4)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApprovalResolution(BaseModel):
    """Request body for ``POST /api/sessions/{id}/approvals/{request_id}``.

    ``approved`` carries the user's allow/deny choice. ``answer`` is an
    optional text payload used exclusively for ``AskUserQuestion`` tool
    approvals — the frontend sends the user's typed answer and the
    broker threads it back to the SDK callback as
    ``PermissionResultAllow.updated_input``, giving the agent the text
    it asked for.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool
    answer: str | None = None


__all__ = ["ApprovalResolution"]
