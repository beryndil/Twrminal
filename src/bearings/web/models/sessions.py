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
    BULK_SESSION_IDS_MAX,
    DEFAULT_TEMPLATE_ADVISOR_MAX_USES,
    DEFAULT_TEMPLATE_EFFORT_LEVEL,
    PROMPT_CONTENT_MAX_CHARS,
    SESSION_DESCRIPTION_MAX_LENGTH,
    SESSION_TITLE_MAX_LENGTH,
)
from bearings.web.models.tags import TagOut


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
    # Spawn-from-reply back-pointers (gap-cycle-03-007). Null on every
    # session that was not created via spawn_from_reply.
    pivot_message_id: str | None = None
    parent_session_id: str | None = None
    # Embedded tag list (PERF-NET-01). Populated by GET /api/sessions via a
    # single batch JOIN; empty list for sessions with no tags. Callers should
    # treat an absent field the same as an empty list for back-compat; the
    # dedicated GET /api/sessions/{id}/tags endpoint remains authoritative for
    # single-session refresh-after-edit.
    tags: list[TagOut] = Field(default_factory=list)


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

    ``working_dir`` is optional. If omitted, the route handler derives it
    from the first tag in ``tag_ids`` (in order) that has a non-null
    ``working_dir`` set. Returns 422 if both ``working_dir`` is omitted
    and no tag provides a directory.

    ``tag_ids`` defaults to the empty list — the new-session form
    enforces "≥1 tag" at the UI layer; the API accepts zero so a CLI
    or test caller can create an untagged session without first
    creating a tag. When multiple tags are supplied, their order in the
    list determines priority: index 0 = highest priority.

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
    working_dir: str | None = Field(default=None, min_length=1)
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


class SessionUpdate(BaseModel):
    """Request shape for the full ``PATCH /api/sessions/{id}`` surface.

    All fields are optional; omitted fields are not written (true PATCH
    semantics, gated by ``model_fields_set``).  Nullable fields (
    ``description``, ``max_budget_usd``, ``session_instructions``) may
    be sent as ``null`` to clear the column.  ``title`` must be a
    non-empty string when present.

    ``tag_ids`` when present replaces the session's tag set wholesale via
    :func:`bearings.db.tags.set_for_session`. Omitting ``tag_ids``
    leaves existing tags unchanged.

    Supersedes :class:`SessionTitleUpdate` — existing callers that send
    only ``{"title": "…"}`` are still served correctly because ``title``
    is the only field in their ``model_fields_set``.

    Gap: gap-cycle-10-001 (SessionEdit modal — full PATCH surface).
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=SESSION_TITLE_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=SESSION_DESCRIPTION_MAX_LENGTH)
    max_budget_usd: float | None = None
    session_instructions: str | None = Field(
        default=None, max_length=SESSION_DESCRIPTION_MAX_LENGTH
    )
    tag_ids: list[int] | None = None


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


class SystemPromptLayerOut(BaseModel):
    """One layer of the assembled system prompt.

    Per ``docs/behavior/chat.md`` §"System-prompt layers contract"
    (gap-cycle-13-004).  Each layer carries its ``kind``, the text
    ``body``, an approximate ``token_count`` (``len(body) // 4``), and
    an optional ``source_path`` for filesystem-sourced layers
    (``project_claude_md``, ``tag_claude_md``).  ``tag_memory`` layers
    are DB-resident and always have ``source_path: null``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    body: str
    token_count: int
    source_path: str | None = None


class SystemPromptLayersOut(BaseModel):
    """Response shape for ``GET /api/sessions/{id}/system_prompt``.

    Per ``docs/behavior/chat.md`` §"System-prompt layers contract"
    (gap-cycle-13-004).

    ``layers`` is ordered in the same splice order the SDK executor
    sees: ``session_instructions`` → ``baseline`` →
    ``project_claude_md`` (walk-up) → ``tag_claude_md`` (per-tag
    CLAUDE.md) → ``tag_memory`` (DB memory rows).  Layers with no
    content are omitted from the list; the frontend renders per-kind
    empty-state rows when a kind is absent.

    ``token_count_approximate`` is always ``true`` — counts are
    computed as ``len(body) // 4`` with no tokenizer.
    """

    model_config = ConfigDict(extra="forbid")

    layers: list[SystemPromptLayerOut]
    total_tokens: int
    token_count_approximate: bool = True


class TokenTotalsOut(BaseModel):
    """Response shape for ``GET /api/sessions/{id}/tokens`` (gap-cycle-13-003).

    Aggregated lifetime token totals from persisted ``message_complete``
    rows for the session.  All fields are non-negative integers; NULLs in
    the token columns are treated as 0 by the ``COALESCE(SUM(...), 0)``
    aggregate.

    """

    model_config = ConfigDict(extra="forbid")

    input: int
    output: int
    cache_read: int
    cache_creation: int


class SessionTodosOut(BaseModel):
    """Response shape for ``GET /api/sessions/{id}/todos`` (gap-cycle-03-013).

    ``todos_json`` is the serialised ``todos`` array extracted from the
    most-recent ``TodoWrite`` tool-call input — identical in shape to the
    ``todos_json`` field on the ``todo_write_update`` WebSocket event so
    the frontend can use the same ``JSON.parse`` path for both the hydration
    seed and live updates.
    """

    model_config = ConfigDict(extra="forbid")

    todos_json: str


class ToolCallOut(BaseModel):
    """Response shape for ``GET /api/sessions/{id}/tool_calls`` (gap-cycle-03-012).

    One row per tool invocation attached to an assistant message. The
    ``message_id`` field lets the frontend group tool calls by their
    owning assistant turn without a separate join request.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    message_id: str
    tool_name: str
    input_json: str
    output: str
    ok: bool | None
    duration_ms: int | None
    error_message: str | None
    created_at: str


class MessageExport(BaseModel):
    """Full-fidelity row mirror for the ``messages`` table in an export.

    All columns are included so the export is self-contained. Nullable
    fields mirror the dataclass — only assistant rows carry the routing
    and token columns; user/system/tool rows leave them ``None``.

    Per ``docs/behavior/sessions.md`` §"Export schema".
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    role: str
    content: str
    created_at: str
    executor_model: str | None
    advisor_model: str | None
    effort_level: str | None
    routing_source: str | None
    routing_reason: str | None
    matched_rule_id: int | None
    executor_input_tokens: int | None
    executor_output_tokens: int | None
    advisor_input_tokens: int | None
    advisor_output_tokens: int | None
    advisor_calls_count: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    seq: int
    pinned: bool
    hidden_from_context: bool


class CheckpointExport(BaseModel):
    """Full-fidelity row mirror for the ``checkpoints`` table in an export.

    Per ``docs/behavior/sessions.md`` §"Export schema".
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    message_id: str
    label: str
    created_at: str


class SessionExport(BaseModel):
    """Response shape for ``GET /api/sessions/{id}/export``.

    Contains a full snapshot of the session's DB state at the time the
    request is made. Per ``docs/behavior/sessions.md`` §"Export schema":

    * ``session`` — the session row (same shape as ``GET /api/sessions/{id}``).
    * ``messages`` — every message in chronological order (all roles:
      ``user``, ``assistant``, ``system``, ``tool``).
    * ``tool_calls`` — raw SDK transcript entries (opaque JSON blobs
      stored by :mod:`bearings.db.sdk_entries`) in write order. These
      are the structured tool-input / tool-output records produced by
      the Claude Code CLI during execution.
    * ``checkpoints`` — every checkpoint attached to the session,
      chronological order.
    * ``attachments`` — always ``[]`` in v0.18.x: uploads are content-
      addressed and shared globally; there is no per-session attachment
      linking table yet.

    Closed sessions are exportable — this endpoint returns 200 for any
    session that exists, regardless of ``closed_at``.
    """

    # mypy: disable-error-code=explicit-any (tool_calls is list[dict] — opaque SDK blobs)
    model_config = ConfigDict(extra="forbid")

    session: SessionOut
    messages: list[MessageExport]
    tool_calls: list[dict]  # type: ignore[type-arg]
    checkpoints: list[CheckpointExport]
    attachments: list[dict]  # type: ignore[type-arg]


class BulkSessionsIn(BaseModel):
    """Request shape for ``POST /api/sessions/bulk`` (gap-cycle-13-001).

    ``op`` selects the operation: ``close``, ``delete``, ``export``, ``tag``,
    or ``untag``. ``session_ids`` carries the IDs to act on; the list must be
    non-empty. ``tag_id`` is required for ``tag`` and ``untag`` ops and ignored
    for the others.

    Extra fields are ignored (defensive against future client additions).
    The :data:`bearings.config.constants.KNOWN_BULK_OPS` validator in the
    route rejects unknown ``op`` values before the DB layer is touched.
    """

    model_config = ConfigDict(extra="ignore")

    op: str
    session_ids: list[str] = Field(min_length=1, max_length=BULK_SESSION_IDS_MAX)
    tag_id: int | None = None


class BulkResultItem(BaseModel):
    """Per-ID result entry returned by ``POST /api/sessions/bulk``.

    ``ok=True`` means the operation succeeded for this ID. ``ok=False``
    means it failed; ``detail`` carries the human-readable reason (e.g.
    ``"no session matches 'bad-id'"``, ``"tag not found"``).
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    ok: bool
    detail: str | None = None


class BulkSessionsOut(BaseModel):
    """Response shape for ``POST /api/sessions/bulk`` non-export ops.

    ``op`` echoes the requested operation. ``results`` is a per-ID list in
    the same order as the request's ``session_ids``. The HTTP status is
    always 200 — the caller must inspect each ``BulkResultItem.ok`` to
    detect partial failures.
    """

    model_config = ConfigDict(extra="forbid")

    op: str
    results: list[BulkResultItem]


class BulkExportOut(BaseModel):
    """Response shape for ``POST /api/sessions/bulk`` with ``op="export"``.

    ``sessions`` is an array of full :class:`SessionExport` objects — one per
    ID in the request, in the same order. IDs that were not found produce a
    ``None`` entry so the array length always equals ``len(session_ids)``.
    Missing entries are omitted client-side (the downloader skips ``null``).

    Per ``docs/behavior/sessions.md`` §"Bulk export contract".
    """

    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionExport | None]


__all__ = [
    "BulkExportOut",
    "BulkResultItem",
    "BulkSessionsIn",
    "BulkSessionsOut",
    "CheckpointExport",
    "MessageExport",
    "PairedChatInfo",
    "PromptAck",
    "PromptIn",
    "SessionCreate",
    "SessionDescriptionUpdate",
    "SessionExport",
    "SessionModelUpdate",
    "SessionOut",
    "SessionPermissionModeUpdate",
    "SessionPinnedUpdate",
    "SessionTitleUpdate",
    "SessionTodosOut",
    "SessionUpdate",
    "SystemPromptLayerOut",
    "SystemPromptLayersOut",
    "TokenTotalsOut",
    "ToolCallOut",
]
