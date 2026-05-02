# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/sessions.py``.

Per ``docs/architecture-v1.md`` §1.1.5 the wire DTOs live alongside
the route module. The shapes mirror :class:`bearings.db.sessions.Session`
plus the prompt-endpoint request/ack envelopes per
``docs/behavior/prompt-endpoint.md``.

The ``mypy: disable-error-code=explicit-any`` pragma matches the
narrow carve-out other ``web/models/*`` modules make for Pydantic's
metaclass-exposed ``Any`` surface.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bearings.config.constants import (
    PROMPT_CONTENT_MAX_CHARS,
    SESSION_DESCRIPTION_MAX_LENGTH,
    SESSION_TITLE_MAX_LENGTH,
)


class PromptIn(BaseModel):
    """Request shape for ``POST /api/sessions/{id}/prompt``.

    Per ``docs/behavior/prompt-endpoint.md`` §"Request shape" only
    ``content`` is read; additional fields are ignored at the boundary.
    Pydantic's ``extra="ignore"`` realises that — clients can send a
    body with ``role`` / ``attachments`` keys (defensive against future
    additions) without rejection, but the values are dropped.

    The ``min_length=1`` guard is on the Pydantic shape; the deeper
    "non-empty after stripping whitespace" rule lives in
    :func:`bearings.agent.prompt_dispatch.dispatch_prompt` so a client
    sending a string of pure whitespace surfaces the doc-mandated
    detail message rather than a Pydantic validation error.
    """

    model_config = ConfigDict(extra="ignore")

    content: str = Field(min_length=1, max_length=PROMPT_CONTENT_MAX_CHARS)


class PromptAck(BaseModel):
    """Response shape for the 202 Accepted ack.

    Per behavior doc §"202 semantics" — ``{ "queued": true,
    "session_id": "<id>" }``. The two fields are pinned by the doc;
    keeping them on a Pydantic model gives the FastAPI OpenAPI surface
    automatic discovery.
    """

    model_config = ConfigDict(extra="forbid")

    queued: bool
    session_id: str


class SessionOut(BaseModel):
    """Response shape for ``GET /api/sessions/{id}`` and the row list."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    title: str
    description: str | None
    session_instructions: str | None
    working_dir: str
    model: str
    permission_mode: str | None
    max_budget_usd: float | None
    total_cost_usd: float
    message_count: int
    last_context_pct: float | None
    last_context_tokens: int | None
    last_context_max: int | None
    pinned: bool
    error_pending: bool
    checklist_item_id: int | None
    created_at: str
    updated_at: str
    last_viewed_at: str | None
    last_completed_at: str | None
    closed_at: str | None
    closing_summary: str | None


class SessionTitleUpdate(BaseModel):
    """Request shape for ``PATCH /api/sessions/{id}`` — title-only."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=SESSION_TITLE_MAX_LENGTH)


class SessionDescriptionUpdate(BaseModel):  # pragma: no cover — reserved for v1 PATCH expansion
    """Reserved request shape for the description (plug) PATCH path.

    Item 1.7 ships title-only PATCH; the description editor lands with
    item 2.x's session-edit dialog. Pinned here so the wire shape's
    declared bound matches the schema cap from day 1.
    """

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=SESSION_DESCRIPTION_MAX_LENGTH)


__all__ = [
    "PromptAck",
    "PromptIn",
    "SessionDescriptionUpdate",
    "SessionOut",
    "SessionTitleUpdate",
]
