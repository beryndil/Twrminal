# mypy: disable-error-code=explicit-any
"""Pydantic wire shapes for ``routes/messages.py`` (item 1.9).

Mirrors :class:`bearings.db.messages.Message` plus the spec §5
per-message routing/usage columns + the spec §App A
``matched_rule_id`` projection (item 1.8 + 1.9). Used by:

* ``GET /api/sessions/{session_id}/messages`` — full transcript list.
* ``GET /api/messages/{message_id}`` — single-row fetch.

The ``mypy: disable-error-code=explicit-any`` pragma matches the
narrow carve-out other ``web/models/*`` modules make for Pydantic's
metaclass-exposed ``Any`` surface.

Per ``docs/model-routing-v1-spec.md`` §7 ("Inspector Usage breakdown
— which fields the API surfaces") the response includes every
column the spec §5 schema declares so the InspectorRouting +
InspectorUsage panels (item 2.6) can render the per-message badge
+ tooltip without further DB calls.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MessageOut(BaseModel):
    """Response shape for ``GET /api/sessions/{id}/messages`` rows.

    Field order mirrors :class:`bearings.db.messages.Message` so the
    auditor can grep both files against the spec §5 column list.
    Routing/usage fields are nullable across all rows: assistant
    rows persisted by item 1.9's
    :func:`bearings.agent.persistence.persist_assistant_turn` carry
    real values; user / system rows + legacy
    ``routing_source = 'unknown_legacy'`` rows carry ``None`` per
    spec §5 "Backfill for legacy data".
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    session_id: str
    role: str
    content: str
    created_at: str
    # Spec §5 routing-decision projection.
    executor_model: str | None
    advisor_model: str | None
    effort_level: str | None
    routing_source: str | None
    routing_reason: str | None
    # Spec §App A ``RoutingDecision.matched_rule_id`` projection (item
    # 1.8 schema column + item 1.9 wire surface).
    matched_rule_id: int | None
    # Spec §App A ``RoutingDecision.evaluated_rules`` projection — ordered
    # rule ids tested by the routing engine (up to and including the
    # matched rule). Empty list for manual/legacy rows or rows that predate
    # this column. Exposed so the Inspector Routing eval-chain widget can
    # render "rule A → rule B → rule C (matched)" without a second fetch.
    evaluated_rules: list[int] = Field(default_factory=list)
    # Spec §5 per-model usage projection (from
    # ``ResultMessage.model_usage`` via item 1.9
    # :func:`bearings.agent.persistence.extract_model_usage`).
    executor_input_tokens: int | None
    executor_output_tokens: int | None
    advisor_input_tokens: int | None
    advisor_output_tokens: int | None
    advisor_calls_count: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    # Legacy flat carriers for ``unknown_legacy`` migrated rows per
    # spec §5 "Backfill for legacy data". The migration in item 3.2
    # populates these from v0.17.x ``messages.input_tokens`` /
    # ``messages.output_tokens`` so analytics that pre-date the
    # routing layer still have *something* to report.
    input_tokens: int | None
    output_tokens: int | None
    # SQLite rowid — monotonically increasing cursor for backward
    # pagination (item 1.3 ``before=`` query param). Frontend passes
    # the lowest ``seq`` it currently holds to walk further into the
    # past via ``loadOlder()``.
    seq: int
    # G3 context-menu state columns.
    pinned: bool = False
    hidden_from_context: bool = False
    # feature-2-004: [stopped] annotation — True when the turn was
    # interrupted via the Stop control; False for normally-completed turns
    # and all pre-feature rows (which default to False per schema migration).
    stopped: bool = False


class MessagePinnedUpdate(BaseModel):
    """Request body for ``PATCH /api/messages/{id}/pinned`` (G3)."""

    model_config = ConfigDict(extra="forbid")

    pinned: bool


class MessageHiddenUpdate(BaseModel):
    """Request body for ``PATCH /api/messages/{id}/hidden`` (G3)."""

    model_config = ConfigDict(extra="forbid")

    hidden: bool


class MessageMoveRequest(BaseModel):
    """Request body for ``POST /api/messages/{id}/move`` (G3)."""

    model_config = ConfigDict(extra="forbid")

    target_session_id: str


class MessagePage(BaseModel):
    """Paginated response for ``GET /api/sessions/{id}/messages`` (item 1.3).

    Wraps the per-page item list with a ``has_more`` flag so the
    frontend knows whether to show the "Load older" affordance.
    ``has_more`` is ``False`` when the backend returned fewer rows than
    the requested ``limit``, or when no ``limit`` was given (full
    transcript fetch).
    """

    model_config = ConfigDict(extra="forbid")

    items: list[MessageOut]
    has_more: bool


__all__ = [
    "MessageHiddenUpdate",
    "MessageMoveRequest",
    "MessageOut",
    "MessagePage",
    "MessagePinnedUpdate",
]
