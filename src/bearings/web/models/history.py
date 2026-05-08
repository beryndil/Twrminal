# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/history.py`` (history.jsonl reader, arch §1.1.5)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DirectoryHistoryEntry(BaseModel):
    """One event entry from ``<directory>/.bearings/history.jsonl``.

    Fields match what :func:`bearings.bearings_dir.lifecycle.note_directory_context_start`
    writes.  Unknown fields from future event types are silently ignored so
    older clients remain forward-compatible when new event kinds land.
    """

    model_config = ConfigDict(extra="ignore")

    #: Event kind — e.g. ``"context_start"``.
    event: str
    #: Session that triggered the event.  ``None`` for events that are not
    #: session-scoped (reserved for future event types).
    session_id: str | None = None
    #: ISO-8601 timestamp of the event.
    timestamp: str


__all__ = ["DirectoryHistoryEntry"]
