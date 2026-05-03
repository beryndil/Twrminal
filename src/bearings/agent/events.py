# mypy: disable-error-code=explicit-any
"""``AgentEvent`` discriminated union — wire shapes for the streaming
protocol.

The ``mypy: disable-error-code=explicit-any`` pragma above is the same
narrow carve-out :mod:`bearings.config.settings` makes for the
:class:`pydantic_settings.BaseSettings` subclass: every Pydantic
:class:`pydantic.BaseModel` exposes ``Any`` in its metaclass surface,
which ``disallow_any_explicit = true`` (``pyproject.toml`` ``[tool.mypy]``
section) flags on every subclass declaration. Restricting the disable
to this file keeps the carve-out narrow — every field below is fully
typed.

Per ``docs/architecture-v1.md`` §4.7, every event a per-session agent
emits over the WebSocket is one of sixteen Pydantic models keyed off a
``type`` literal. Item 1.1 lays the type surface; item 1.2 plumbs the
WebSocket fan-out + per-event translation in ``agent/translate.py``.

Every event carries ``session_id`` (so a multi-session UI client can
route the frame). Events that follow ``MessageComplete`` semantics
also carry the spec §5 routing/usage fields per the
:class:`MessageComplete` and :class:`RoutingBadge` shapes — the
auditor on item 1.9 verifies these columns round-trip the spec §5
``messages`` table columns ``executor_*_tokens`` /
``advisor_*_tokens`` / ``advisor_calls_count`` / ``cache_read_tokens``
without loss.

References:

* ``docs/architecture-v1.md`` §4.7 — discriminated union.
* ``docs/model-routing-v1-spec.md`` §5 — per-message routing badge +
  per-model usage columns.
* ``docs/behavior/tool-output-streaming.md`` — what the user sees for
  every ``ToolCallStart`` / ``ToolOutputDelta`` / ``ToolCallEnd``.
* ``docs/behavior/chat.md`` — what the user sees for every
  ``MessageStart`` / ``MessageComplete`` / ``ErrorEvent`` /
  ``ApprovalRequest`` etc.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class _BaseEvent(BaseModel):
    """Common base for every wire event — frozen + extra=forbid.

    ``frozen=True`` matches the discriminated-union convention (events
    are immutable once emitted; the WS fan-out broadcasts the same
    instance to every subscriber). ``extra="forbid"`` makes the wire
    schema strict — a forward-compat field has to be added here, not
    sneaked in via a kwarg.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str


class UserMessage(_BaseEvent):
    """The user-typed prompt for the in-flight turn."""

    type: Literal["user_message"] = "user_message"
    message_id: str
    content: str


class Token(_BaseEvent):
    """Per-token text delta from the assistant (``text_delta`` partials)."""

    type: Literal["token"] = "token"
    message_id: str
    delta: str


class Thinking(_BaseEvent):
    """Per-token thinking delta (where the model emits ``thinking_delta``)."""

    type: Literal["thinking"] = "thinking"
    message_id: str
    delta: str


class ToolCallStart(_BaseEvent):
    """A tool invocation began — opens a row in the tool-work drawer."""

    type: Literal["tool_call_start"] = "tool_call_start"
    message_id: str
    tool_call_id: str
    tool_name: str
    # Tool-input is a JSON-serialisable map; we carry it as a JSON
    # string because the wire shape stays trivially typeable under
    # ``mypy --strict`` + ``disallow_any_explicit``. Item 1.2 may
    # widen this to a ``JsonValue`` recursive alias if a downstream
    # consumer needs structured access.
    tool_input_json: str


class ToolOutputDelta(_BaseEvent):
    """A streaming chunk of tool output — appended to the row's body."""

    type: Literal["tool_output_delta"] = "tool_output_delta"
    tool_call_id: str
    delta: str


class ToolCallEnd(_BaseEvent):
    """Tool call completed (or failed) — finalises the drawer row."""

    type: Literal["tool_call_end"] = "tool_call_end"
    message_id: str
    tool_call_id: str
    ok: bool
    duration_ms: int
    output_summary: str
    error_message: str | None = None


class ToolProgress(_BaseEvent):
    """Keepalive heartbeat for a long-running tool (per
    ``docs/behavior/tool-output-streaming.md`` §"Long-tool keepalive").
    Not persisted; fan-out only."""

    type: Literal["tool_progress"] = "tool_progress"
    tool_call_id: str
    elapsed_ms: int


class MessageStart(_BaseEvent):
    """Beginning of an assistant turn — the bubble appears."""

    type: Literal["message_start"] = "message_start"
    message_id: str


class MessageComplete(_BaseEvent):
    """End of an assistant turn — finalises the bubble.

    Per spec §5 the per-model usage and routing columns ride on this
    event so the persistence layer (item 1.9) can write the ``messages``
    row in one pass. Legacy ``input_tokens`` / ``output_tokens`` are
    kept as ``Optional[int]`` per arch §4.7 to carry forward the
    ``unknown_legacy`` data shape from spec §5 "Backfill for legacy
    data".
    """

    type: Literal["message_complete"] = "message_complete"
    message_id: str
    content: str
    # Per-model usage (spec §5)
    executor_input_tokens: int | None = None
    executor_output_tokens: int | None = None
    advisor_input_tokens: int | None = None
    advisor_output_tokens: int | None = None
    advisor_calls_count: int = 0
    cache_read_tokens: int | None = None
    # Legacy flat columns (arch §4.7 — Optional[int] for
    # routing-source = unknown_legacy migration carriers).
    input_tokens: int | None = None
    output_tokens: int | None = None


class RoutingBadge(_BaseEvent):
    """Per-message routing badge (spec §5 — e.g. ``Sonnet → Opus x2``).

    Emitted alongside :class:`MessageComplete`; carries the routing
    decision the badge tooltip surfaces. Item 1.2 fans this out as a
    standalone WS frame so the badge can render before the full
    message body has been persisted.
    """

    type: Literal["routing_badge"] = "routing_badge"
    message_id: str
    executor_model: str
    advisor_model: str | None
    advisor_calls_count: int
    effort_level: str
    routing_source: str
    routing_reason: str


class ContextUsage(_BaseEvent):
    """Context-window meter tick — drives the inspector's pressure bar.

    Field names mirror :func:`ClaudeSDKClient.get_context_usage`'s
    snake-cased shape after ``agent/translate.py`` adapts the SDK's
    camelCase keys ``percentage`` / ``totalTokens`` / ``maxTokens``
    (arch §5 #10).

    The three optional fields (``model``, ``is_auto_compact_enabled``,
    ``auto_compact_threshold``) are re-added in item 2.2 so the header
    :class:`ContextMeter` can paint the auto-compact warn band and the
    model badge without a separate fetch. All three are ``None`` when the
    SDK omits them from the usage dict (e.g. older SDK builds that
    pre-date the ``autoCompactThreshold`` field).
    """

    type: Literal["context_usage"] = "context_usage"
    percentage: float
    total_tokens: int
    max_tokens: int
    model: str | None = None
    is_auto_compact_enabled: bool | None = None
    # Absolute-token threshold at which the SDK triggers auto-compact.
    # Present only when ``is_auto_compact_enabled`` is ``True`` and the
    # SDK version exposes the field.
    auto_compact_threshold: int | None = None


class ErrorEvent(_BaseEvent):
    """Mid-turn error — closes the in-flight bubble in red."""

    type: Literal["error"] = "error"
    message: str
    fatal: bool = False


class TurnReplayed(_BaseEvent):
    """Server-restart marker — "resuming prompt from previous session"
    annotation per ``docs/behavior/chat.md`` §"Reconnect / resume"."""

    type: Literal["turn_replayed"] = "turn_replayed"
    message_id: str


class ApprovalRequest(_BaseEvent):
    """``can_use_tool`` callback open — opens the approval modal."""

    type: Literal["approval_request"] = "approval_request"
    request_id: str
    tool_name: str
    tool_input_json: str


class ApprovalResolved(_BaseEvent):
    """``can_use_tool`` resolved — modal closes with the user's choice."""

    type: Literal["approval_resolved"] = "approval_resolved"
    request_id: str
    approved: bool


class TodoWriteUpdate(_BaseEvent):
    """``TodoWrite`` tool fired — sidebar live-todos row updates."""

    type: Literal["todo_write_update"] = "todo_write_update"
    todos_json: str


class RunnerStatusEvent(_BaseEvent):
    """Post-replay status frame — sent once on WS connect after replay.

    The client uses this to reconcile ``streamingActive`` on reconnect.
    Without it a reconnect mid-turn shows an indefinite spinner if the
    runner died while a ``MessageStart`` was still open in the ring
    buffer. ``streaming_active`` is the authoritative flag;
    ``current_turn_id`` (the assistant ``message_id`` for the live
    turn) lets the UI highlight the right bubble.

    Emitted by :meth:`bearings.agent.runner.SessionRunner.get_status_event`
    and sent by :func:`bearings.web.streaming.serve_session_stream`
    right after the replay drain.
    """

    type: Literal["runner_status"] = "runner_status"
    streaming_active: bool
    current_turn_id: str | None = None


# Discriminated-union alias — arch §4.7 lists 16 events. Pydantic
# resolves the right variant from the ``type`` field at parse time.
# PEP 695 ``type`` keyword form per ruff UP040; equivalent to a
# ``TypeAlias``-annotated assignment but advertises the alias as
# transparent to type checkers.
type AgentEvent = Annotated[
    UserMessage
    | Token
    | Thinking
    | ToolCallStart
    | ToolCallEnd
    | ToolOutputDelta
    | ToolProgress
    | MessageStart
    | MessageComplete
    | ContextUsage
    | ErrorEvent
    | TurnReplayed
    | ApprovalRequest
    | ApprovalResolved
    | TodoWriteUpdate
    | RoutingBadge
    | RunnerStatusEvent,
    Field(discriminator="type"),
]


__all__ = [
    "AgentEvent",
    "ApprovalRequest",
    "ApprovalResolved",
    "ContextUsage",
    "ErrorEvent",
    "MessageComplete",
    "MessageStart",
    "RoutingBadge",
    "RunnerStatusEvent",
    "Thinking",
    "TodoWriteUpdate",
    "Token",
    "ToolCallEnd",
    "ToolCallStart",
    "ToolOutputDelta",
    "ToolProgress",
    "TurnReplayed",
    "UserMessage",
]
