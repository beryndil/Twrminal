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
    DEFAULT_TEMPLATE_ADVISOR_MAX_USES,
    DEFAULT_TEMPLATE_EFFORT_LEVEL,
    PROMPT_CONTENT_MAX_CHARS,
    SESSION_DESCRIPTION_MAX_LENGTH,
    SESSION_TITLE_MAX_LENGTH,
)


class PromptIn(BaseModel):
    """Request shape for ``POST /api/sessions/{id}/prompt``.

    Per ``docs/behavior/prompt-endpoint.md`` §"Request shape" only
    ``content`` is read by default; additional unknown fields are
    ignored at the boundary.  Pydantic's ``extra="ignore"`` realises
    that — clients can send a body with ``role`` / ``attachments``
    keys (defensive against future additions) without rejection, but
    the values are dropped.

    ``force_advisor`` is the G9 per-turn advisor override: when
    ``true``, the SDK loop prepends
    :data:`bearings.config.constants.FORCE_ADVISOR_INSTRUCTION` to the
    content it sends to ``client.query``, directing the executor to
    call the advisor tool for this turn only.  Sessions without an
    advisor model configured treat the flag as a no-op (graceful
    degradation — the advisor tool is not registered in those SDK
    sessions).  The ``/advisor`` composer slash-command sets this flag
    automatically after stripping the command token from the draft.

    The ``min_length=1`` guard is on the Pydantic shape; the deeper
    "non-empty after stripping whitespace" rule lives in
    :func:`bearings.agent.prompt_dispatch.dispatch_prompt` so a client
    sending a string of pure whitespace surfaces the doc-mandated
    detail message rather than a Pydantic validation error.
    """

    model_config = ConfigDict(extra="ignore")

    content: str = Field(min_length=1, max_length=PROMPT_CONTENT_MAX_CHARS)
    force_advisor: bool = False


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
    paired_parent_title: str | None = None


class SessionTitleUpdate(BaseModel):
    """Request shape for ``PATCH /api/sessions/{id}`` — title-only."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=SESSION_TITLE_MAX_LENGTH)


class SessionCreate(BaseModel):
    """Request shape for ``POST /api/sessions``.

    Per arch §1.1.5 the v1 session-create surface. The Pydantic shape
    enforces field shape; the route handler enforces ``kind`` membership
    in :data:`KNOWN_SESSION_KINDS`, that ``tag_ids`` references existing
    rows, and the deeper dataclass invariants (model name format,
    permission-mode enum, etc.) via :class:`Session.__post_init__`.

    ``tag_ids`` defaults to the empty list — the new-session form
    enforces "≥1 tag" at the UI layer; the API accepts zero so a CLI
    or test caller can create an untagged session without first
    creating a tag.

    The three ``routing_*`` fields carry the routing-decision projection
    so the supervisor respawn path can reconstruct the full
    :class:`bearings.agent.routing.RoutingDecision` without falling
    back to template defaults. ``routing_advisor_model=None`` means "no
    advisor"; omitting these fields uses the same defaults as the
    session-bootstrap fallback.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    title: str = Field(min_length=1, max_length=SESSION_TITLE_MAX_LENGTH)
    working_dir: str = Field(min_length=1)
    model: str = Field(min_length=1)
    description: str | None = Field(default=None, max_length=SESSION_DESCRIPTION_MAX_LENGTH)
    session_instructions: str | None = None
    permission_mode: str | None = None
    max_budget_usd: float | None = None
    tag_ids: list[int] = Field(default_factory=list)
    routing_advisor_model: str | None = None
    routing_advisor_max_uses: int = Field(default=DEFAULT_TEMPLATE_ADVISOR_MAX_USES, ge=0)
    routing_effort_level: str = DEFAULT_TEMPLATE_EFFORT_LEVEL


class SessionModelUpdate(BaseModel):
    """Request shape for ``PATCH /api/sessions/{id}/model`` (spec §7
    mid-session model swap; arch §1.1.5).

    The wire field name matches the column name (``model``). The route
    persists the new value AND recycles the live SDK supervisor for
    the session so the next prompt respawns the subprocess with
    ``--model <new>``; full transcript replay is handled by the
    standard spawn path (``--resume <uuid>``).
    """

    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)


class SessionPermissionModeUpdate(BaseModel):
    """Request shape for ``PATCH /api/sessions/{id}/permission_mode`` (item 3.3).

    ``None`` clears the column — the runner falls back to the profile default
    on the next boot. Non-``None`` values are validated by the DB layer against
    :data:`KNOWN_SDK_PERMISSION_MODES`.
    """

    model_config = ConfigDict(extra="forbid")

    permission_mode: str | None = None


class SessionPinnedUpdate(BaseModel):
    """Request shape for ``PATCH /api/sessions/{id}/pinned``.

    ``pinned=true`` pins the session row; ``pinned=false`` unpins it.
    """

    model_config = ConfigDict(extra="forbid")

    pinned: bool


class SessionDescriptionUpdate(BaseModel):  # pragma: no cover — reserved for v1 PATCH expansion
    """Reserved request shape for the description (plug) PATCH path.

    Item 1.7 ships title-only PATCH; the description editor lands with
    item 2.x's session-edit dialog. Pinned here so the wire shape's
    declared bound matches the schema cap from day 1.
    """

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=SESSION_DESCRIPTION_MAX_LENGTH)


class PairedChatInfo(BaseModel):
    """Response shape for ``GET /api/sessions/{id}/paired-chat-info``.

    Per ``docs/behavior/paired-chats.md`` §"From the chat side" — when a
    chat session is paired to a checklist item, the breadcrumb shows
    ``<parent checklist title> > <item label>``. This endpoint returns
    those two fields when a pairing exists, or ``None`` when the chat is
    unpaired.
    """

    model_config = ConfigDict(extra="forbid")

    parent_title: str
    item_label: str


__all__ = [
    "PairedChatInfo",
    "PromptAck",
    "PromptIn",
    "SessionCreate",
    "SessionDescriptionUpdate",
    "SessionModelUpdate",
    "SessionOut",
    "SessionPermissionModeUpdate",
    "SessionPinnedUpdate",
    "SessionTitleUpdate",
]
