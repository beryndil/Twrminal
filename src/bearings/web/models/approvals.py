# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/approvals.py`` (Slice A4)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApprovalResolution(BaseModel):
    """Request body for ``POST /api/sessions/{id}/approvals/{request_id}``.

    A single boolean carrying the user's choice. The route resolves
    the matching broker future with this value; the SDK callback
    translates it into a ``PermissionResultAllow`` /
    ``PermissionResultDeny`` SDK return.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool


__all__ = ["ApprovalResolution"]
