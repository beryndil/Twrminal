# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/health.py`` (item 1.10)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HealthOut(BaseModel):
    """Response shape for ``GET /api/health``."""

    model_config = ConfigDict(extra="forbid")

    status: str
    version: str
    uptime_s: float
    db_ok: bool
    data_dir: str


__all__ = ["HealthOut"]
