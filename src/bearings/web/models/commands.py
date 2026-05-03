# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/commands.py`` (item 2.3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CommandOut(BaseModel):
    """One slash-command entry returned by ``GET /api/commands``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    source: str


__all__ = ["CommandOut"]
