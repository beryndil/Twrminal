# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/reorg.py`` (gap-cycle-03-008/009/13-002).

Mirrors :class:`bearings.db.reorg.ReorgAudit` and
:class:`bearings.db.reorg.SplitResult`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ReorgAuditOut(BaseModel):
    """Response body for one reorg-operation audit record.

    ``kind`` is one of ``'merge'``, ``'split'``, or ``'move'``.  See
    :mod:`bearings.db.reorg` for the ``dst_session_id`` / ``src_session_id``
    semantics across each kind.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    dst_session_id: str
    src_session_id: str
    merged_at: str
    src_title: str
    boundary_msg_id: str | None
    kind: str


class ReorgSplitOut(BaseModel):
    """Response body for ``POST /api/sessions/{src}/reorg/split``.

    ``audit`` is the committed audit row.  ``moved_message_ids`` is the
    ordered list of message ids that were re-parented to the target
    session (empty when no messages fell at or after ``from_seq``).
    """

    model_config = ConfigDict(extra="forbid")

    audit: ReorgAuditOut
    moved_message_ids: list[str]


class ReorgAuditListOut(BaseModel):
    """Response body for ``GET /api/sessions/{id}/reorg/audits``."""

    model_config = ConfigDict(extra="forbid")

    items: list[ReorgAuditOut]


class UndoReorgOut(BaseModel):
    """Response body for a successful undo (``DELETE /api/sessions/{id}/reorg/audits/{auditId}``).

    ``new_session_id`` carries the session the client should navigate to:

    * ``kind='merge'``: id of the newly re-created source session.
    * ``kind='split'`` / ``kind='move'``: id of the original source session
      (already exists; content was moved back there).
    """

    model_config = ConfigDict(extra="forbid")

    new_session_id: str


# Backward-compat alias — existing code imported UndoMergeOut.
UndoMergeOut = UndoReorgOut
