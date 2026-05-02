"""DTO surface for the spawn-from-reply Wave 3 classifier
(`~/.claude/plans/classifying-spawn-reply-wave-3.md`).

``SpawnClassifyResult`` is returned by
``POST /sessions/{id}/spawn_from_reply/{message_id}/classify`` and
consumed by the ``SpawnClassifiedCard`` frontend component.

Design notes:
- The three ``suggested_*`` fields are mutually exclusive: exactly one
  is non-null, matching ``shape``. Separate typed fields rather than a
  discriminated union keeps mypy happy without a Union[...] import and
  keeps the JSON serialisation flat (no nested ``__root__``/``root``
  wrapper Pydantic v2 would insert on a RootModel).
- ``SpawnShape`` is a ``str`` enum so it round-trips through JSON as a
  plain string ("single_chat") rather than an integer — the frontend
  matches on the string value.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class SpawnShape(StrEnum):
    single_chat = "single_chat"
    multi_chat = "multi_chat"
    checklist = "checklist"


class SingleChatPayload(BaseModel):
    """Suggested content for the single-chat spawn path. ``title`` is
    the sidebar label (≤60 chars); ``description`` is the session plug
    (≤200 chars). Both are LLM-derived; the user can edit them after
    spawning via the normal PATCH endpoint."""

    title: str
    description: str


class MultiChatPayload(BaseModel):
    """One suggested chat in a multi-chat fan-out (2–5 items). Each
    item maps to one ``POST /spawn_from_reply`` call in the apply
    path."""

    title: str
    description: str


class ChecklistPayload(BaseModel):
    """One suggested checklist item. ``label`` is the action summary
    (≤80 chars); ``notes`` carries context / done-when hints (≤200
    chars). Maps to one ``POST /sessions/{id}/checklist/items`` call
    in the apply path."""

    label: str
    notes: str


class SpawnClassifyResult(BaseModel):
    """Response from the ``/classify`` endpoint. ``shape`` names the
    recommended spawn kind; ``reason`` is a one-sentence LLM
    justification; exactly one ``suggested_*`` field is non-null.

    The endpoint is guaranteed to return 200 even when the classifier
    is disabled or fails — in that case ``shape`` is ``single_chat``
    and ``reason`` is ``"classifier disabled or failed"``."""

    shape: SpawnShape
    reason: str
    suggested_single: SingleChatPayload | None = None
    suggested_multi: list[MultiChatPayload] | None = None
    suggested_checklist: list[ChecklistPayload] | None = None
