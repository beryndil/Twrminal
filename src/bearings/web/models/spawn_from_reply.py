# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/spawn_from_reply.py``.

Per ``docs/architecture-v1.md`` §1.1.5 the wire DTOs live alongside
the route module.  The spawn-from-reply endpoint (gap-cycle-03-007)
creates a fresh paired chat seeded with a blockquote of the clicked
assistant message.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SpawnFromReplyOut(BaseModel):
    """Response shape for ``POST /api/sessions/{parent_id}/spawn_from_reply/{message_id}``.

    ``created`` is ``True`` on first spawn (HTTP 201) and ``False``
    when the idempotent path returned an existing open session that
    was already spawned for this ``message_id`` (HTTP 200).
    """

    model_config = ConfigDict(extra="forbid")

    chat_session_id: str
    parent_session_id: str
    pivot_message_id: str
    title: str
    working_dir: str
    model: str
    created: bool


__all__ = ["SpawnFromReplyOut"]
