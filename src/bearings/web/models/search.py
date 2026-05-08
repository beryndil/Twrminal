# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/search.py`` (item 2.4 — DB full-text search)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HistorySearchResult(BaseModel):
    """One search hit returned by ``GET /api/history/search``."""

    model_config = ConfigDict(extra="forbid")

    #: ``"session"`` when the match is in the session title/description;
    #: ``"message"`` when the match is in message content.
    kind: Literal["session", "message"]
    session_id: str
    session_title: str
    #: ``None`` for session-level hits; the message row id for message hits.
    message_id: str | None
    #: Context snippet extracted around the first match occurrence.
    snippet: str


__all__ = ["HistorySearchResult"]
