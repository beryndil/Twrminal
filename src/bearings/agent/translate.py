# mypy: disable-error-code=explicit-any
"""SDK-message → AgentEvent stream translator.

Per Slice A1 of ``~/.claude/plans/wiring-agent-loop.md``: this module
takes the SDK's per-turn message stream
(``UserMessage`` / ``AssistantMessage`` / ``SystemMessage`` /
``ResultMessage`` / ``StreamEvent``) and yields the wire-side
``AgentEvent`` types the runner's ring buffer + WS subscribers
already consume.

Three shape decisions worth naming:

* **Stateful per-turn translator.** A pure
  ``Message → Iterable[AgentEvent]`` mapping is not enough because
  Token / Thinking / ToolCallStart deltas need the assistant's
  ``message_id``, and that id arrives on the SDK's first
  ``message_start`` partial frame. The translator captures it and
  forwards it onto every event for the rest of the turn.

* **Body accumulation comes from ``AssistantMessage.content``, not
  from rolled-up Token deltas.** The SDK's final ``AssistantMessage``
  carries the canonical post-streaming body in its ``TextBlock``
  list. Per arch §4.7 ``MessageComplete.content`` is the canonical
  body the persistence layer writes; the per-token deltas drive the
  in-flight bubble fill but are not the source of truth.

* **Tool-call lifecycle bridges two SDK messages.** ``ToolUseBlock``
  on an ``AssistantMessage`` opens the call (we emit
  :class:`ToolCallStart` and remember the start clock). The matching
  ``ToolResultBlock`` arrives on a *subsequent* ``UserMessage``
  (the SDK echo of the tool's reply back to the model); we emit
  :class:`ToolCallEnd` then. Tool-output streaming via
  :class:`ToolOutputDelta` is the SDK's
  ``content_block_delta.type=='input_json_delta'`` partial frame —
  not currently emitted by Anthropic for tool *outputs*; the
  v1 surface treats tool output as a single end-of-call payload
  carried on the ``ToolResultBlock`` content.

``Any`` carve-out at file scope: the SDK's ``StreamEvent.event`` is
``dict[str, Any]`` (the raw Anthropic wire frame). Same architectural
pressure as :mod:`bearings.agent.events` and
:mod:`bearings.agent.bearings_mcp`; pragma is narrowed to this file.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from bearings.agent.events import (
    AgentEvent,
    ContextUsage,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    Thinking,
    Token,
    ToolCallEnd,
    ToolCallStart,
)
from bearings.agent.routing import RoutingDecision

# SDK ``StreamEvent.event`` keys — extracted to module scope so a
# spec-version drift surfaces here as a single rename rather than
# scattered string literals.
_EVENT_TYPE_KEY = "type"
_EVENT_MESSAGE_KEY = "message"
_EVENT_DELTA_KEY = "delta"
_EVENT_INDEX_KEY = "index"
_EVENT_CONTENT_BLOCK_KEY = "content_block"

_TYPE_MESSAGE_START = "message_start"
_TYPE_CONTENT_BLOCK_START = "content_block_start"
_TYPE_CONTENT_BLOCK_DELTA = "content_block_delta"
_TYPE_TEXT_DELTA = "text_delta"
_TYPE_THINKING_DELTA = "thinking_delta"


class SDKEventTranslator:
    """Per-session stateful translator from SDK messages to AgentEvent.

    Lifecycle:

    * :meth:`begin_turn` — call before the SDK starts producing
      output for a fresh turn. Resets per-turn state (message id,
      accumulated body, in-flight tool calls).
    * :meth:`feed` — call once per SDK message; yields the
      :class:`AgentEvent` translation. The caller (sdk_loop.py)
      runs ``await runner.emit(event)`` for each yielded event.
    * :meth:`final_body` — after the turn ends, returns the
      canonical assistant body the persistence layer writes.

    The translator does NOT call ``runner.emit`` directly — it stays
    pure-translation so unit tests can drive it with synthetic SDK
    messages and assert on the yielded :class:`AgentEvent` sequence
    without spinning up a runner.
    """

    def __init__(self, session_id: str, decision: RoutingDecision) -> None:
        if not session_id:
            raise ValueError("SDKEventTranslator.session_id must be non-empty")
        self._session_id = session_id
        self._decision = decision
        self._message_id: str | None = None
        self._body_parts: list[str] = []
        self._tool_call_started_ns: dict[str, int] = {}
        self._message_start_emitted = False

    # -- per-turn lifecycle ----------------------------------------------

    def begin_turn(self) -> None:
        """Reset per-turn state. Idempotent."""
        self._message_id = None
        self._body_parts = []
        self._tool_call_started_ns = {}
        self._message_start_emitted = False

    def final_body(self) -> str:
        """Canonical assistant body after :meth:`feed` has consumed every
        SDK message in the turn. Joined from
        :class:`claude_agent_sdk.types.TextBlock` content (which is the
        post-streaming canonical text per the SDK)."""
        return "".join(self._body_parts)

    @property
    def message_id(self) -> str | None:
        """The assistant message id learned from the SDK stream; ``None``
        until the first ``message_start`` partial frame or
        ``AssistantMessage`` arrives."""
        return self._message_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def decision(self) -> RoutingDecision:
        return self._decision

    # -- main entry point ------------------------------------------------

    def feed(
        self,
        sdk_message: AssistantMessage
        | UserMessage
        | SystemMessage
        | ResultMessage
        | StreamEvent
        | object,
    ) -> Iterable[AgentEvent]:
        """Translate one SDK message into zero or more :class:`AgentEvent`.

        Forward-compatible: unknown subclasses are ignored (no events).
        The match arms cover every documented SDK message type as of
        2026-05-01; new types added by future SDK releases pass through
        as no-ops until the translator learns them.
        """
        if isinstance(sdk_message, StreamEvent):
            yield from self._feed_stream_event(sdk_message)
        elif isinstance(sdk_message, AssistantMessage):
            yield from self._feed_assistant(sdk_message)
        elif isinstance(sdk_message, UserMessage):
            yield from self._feed_user(sdk_message)
        elif isinstance(sdk_message, ResultMessage):
            yield from self._feed_result(sdk_message)
        elif isinstance(sdk_message, SystemMessage):
            # SystemMessage carries SDK init/diagnostic frames. v1
            # ignores these on the conversation surface; the inspector
            # may surface them in a later item.
            return
        else:  # pragma: no cover — forward-compat guard
            return

    # -- stream-event partials ------------------------------------------

    def _feed_stream_event(self, frame: StreamEvent) -> Iterable[AgentEvent]:
        """Translate Anthropic-API partial frames into Token / Thinking.

        The frame's ``event`` dict is the raw Anthropic wire shape; we
        match on its ``type`` key. ``message_start`` carries the
        assistant message id; ``content_block_delta`` carries text
        and thinking deltas.
        """
        event = frame.event
        kind = _str_or_none(event.get(_EVENT_TYPE_KEY))
        if kind == _TYPE_MESSAGE_START:
            yield from self._capture_message_id_from_start(event)
            return
        if kind == _TYPE_CONTENT_BLOCK_DELTA:
            yield from self._handle_content_block_delta(event)
            return
        # Other Anthropic frame types (content_block_start /
        # content_block_stop / message_stop / message_delta) carry no
        # user-visible delta; the canonical signal is the final
        # ``AssistantMessage`` we receive after the partials.
        return

    def _capture_message_id_from_start(self, event: dict[str, Any]) -> Iterable[AgentEvent]:
        """``message_start`` partial — record the message id + emit
        :class:`MessageStart` so the conversation pane opens the
        assistant bubble immediately."""
        message_payload = event.get(_EVENT_MESSAGE_KEY)
        if not isinstance(message_payload, dict):
            return
        candidate = _str_or_none(message_payload.get("id"))
        if candidate is None:
            return
        if self._message_id is None:
            self._message_id = candidate
        if not self._message_start_emitted:
            self._message_start_emitted = True
            yield MessageStart(
                session_id=self._session_id,
                message_id=candidate,
            )

    def _handle_content_block_delta(self, event: dict[str, Any]) -> Iterable[AgentEvent]:
        """``content_block_delta`` — text or thinking delta."""
        delta = event.get(_EVENT_DELTA_KEY)
        if not isinstance(delta, dict):
            return
        delta_type = _str_or_none(delta.get(_EVENT_TYPE_KEY))
        message_id = self._message_id
        if message_id is None:
            # Defence-in-depth: a delta arrived before message_start.
            # The SDK guarantees ordering but we won't crash if it ever
            # changes; just drop the orphan delta.
            return
        if delta_type == _TYPE_TEXT_DELTA:
            text = _str_or_none(delta.get("text"))
            if text:
                yield Token(
                    session_id=self._session_id,
                    message_id=message_id,
                    delta=text,
                )
            return
        if delta_type == _TYPE_THINKING_DELTA:
            thinking = _str_or_none(delta.get("thinking"))
            if thinking:
                yield Thinking(
                    session_id=self._session_id,
                    message_id=message_id,
                    delta=thinking,
                )
            return

    # -- canonical message frames ---------------------------------------

    def _feed_assistant(self, message: AssistantMessage) -> Iterable[AgentEvent]:
        """The SDK's final canonical assistant frame.

        If partials were enabled the deltas already streamed via
        :class:`Token` / :class:`Thinking`; here we accumulate the
        canonical body for persistence + emit
        :class:`ToolCallStart` for any tool uses the assistant
        invoked. We also emit :class:`MessageStart` if it wasn't
        already (covers the no-partials path).
        """
        if message.message_id and self._message_id is None:
            self._message_id = message.message_id
        message_id = self._message_id
        if message_id is None:
            # The SDK should always set message_id on AssistantMessage;
            # if it doesn't we synthesize one so downstream events still
            # correlate. uuid4() avoids collisions with persisted ids.
            import uuid

            message_id = f"sdk_{uuid.uuid4().hex}"
            self._message_id = message_id
        if not self._message_start_emitted:
            self._message_start_emitted = True
            yield MessageStart(
                session_id=self._session_id,
                message_id=message_id,
            )
        for block in message.content:
            if isinstance(block, TextBlock):
                self._body_parts.append(block.text)
            elif isinstance(block, ThinkingBlock):
                # Thinking lives on the in-flight bubble's thinking
                # field; the canonical body excludes it.
                continue
            elif isinstance(block, ToolUseBlock):
                self._tool_call_started_ns[block.id] = time.monotonic_ns()
                yield ToolCallStart(
                    session_id=self._session_id,
                    message_id=message_id,
                    tool_call_id=block.id,
                    tool_name=block.name,
                    tool_input_json=json.dumps(block.input, sort_keys=True),
                )
            # ToolResultBlock on AssistantMessage is unusual but legal
            # (the SDK occasionally embeds tool results; ignored here).

    def _feed_user(self, message: UserMessage) -> Iterable[AgentEvent]:
        """SDK echo of the tool result back to the model.

        This frame's content carries :class:`ToolResultBlock` entries
        for every tool call that just finished. We translate each into
        a :class:`ToolCallEnd`.
        """
        message_id = self._message_id
        if message_id is None:
            # Tool-result echo arrived before any assistant frame.
            # Should never happen — surface defensively as a no-op.
            return
        content = message.content
        if isinstance(content, str):
            return
        for block in content:
            if not isinstance(block, ToolResultBlock):
                continue
            tool_call_id = block.tool_use_id
            started_ns = self._tool_call_started_ns.pop(tool_call_id, None)
            if started_ns is None:
                duration_ms = 0
            else:
                duration_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
            ok = not bool(block.is_error)
            output_summary = _summarize_tool_result_content(block.content)
            error_message = output_summary if not ok else None
            yield ToolCallEnd(
                session_id=self._session_id,
                message_id=message_id,
                tool_call_id=tool_call_id,
                ok=ok,
                duration_ms=duration_ms,
                output_summary=output_summary,
                error_message=error_message,
            )

    def _feed_result(self, message: ResultMessage) -> Iterable[AgentEvent]:
        """Terminal turn frame — emit MessageComplete + ContextUsage.

        :class:`MessageComplete` carries the per-model usage and
        routing-decision-derived columns the spec §5 ``messages``
        table writer expects. The translator does NOT itself call
        :func:`bearings.agent.persistence.persist_assistant_turn` —
        the worker loop owns that DB write so the translator stays
        pure-translation.
        """
        message_id = self._message_id
        if message_id is None:
            # The turn never produced an AssistantMessage (rare —
            # would mean the SDK fired ResultMessage with no body).
            # Surface an ErrorEvent so the bubble shows the failure.
            yield ErrorEvent(
                session_id=self._session_id,
                message=message.result or "Turn completed with no assistant message",
                fatal=False,
            )
            return
        body = self.final_body()
        executor_in, executor_out, advisor_in, advisor_out, advisor_calls, cache_read = (
            _project_usage(message.model_usage, self._decision)
        )
        yield MessageComplete(
            session_id=self._session_id,
            message_id=message_id,
            content=body,
            executor_input_tokens=executor_in,
            executor_output_tokens=executor_out,
            advisor_input_tokens=advisor_in,
            advisor_output_tokens=advisor_out,
            advisor_calls_count=advisor_calls,
            cache_read_tokens=cache_read,
        )
        # ContextUsage rides on every turn-end so the inspector's
        # pressure-bar updates without a separate poller. The SDK's
        # ``ResultMessage.usage`` carries the same shape as
        # ``get_context_usage()`` — pull from there.
        usage = message.usage
        if isinstance(usage, dict):
            ctx = _project_context_usage(usage)
            if ctx is not None:
                pct, total, max_tokens, model, is_auto_compact, threshold = ctx
                yield ContextUsage(
                    session_id=self._session_id,
                    percentage=pct,
                    total_tokens=total,
                    max_tokens=max_tokens,
                    model=model,
                    is_auto_compact_enabled=is_auto_compact,
                    auto_compact_threshold=threshold,
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _str_or_none(value: object) -> str | None:
    """Return ``value`` if it's a string, else ``None``."""
    return value if isinstance(value, str) else None


def _summarize_tool_result_content(
    content: str | list[dict[str, Any]] | None,
) -> str:
    """Project an SDK ``ToolResultBlock.content`` onto a single string.

    The SDK exposes either a string (simple tool result), a list of
    content blocks (Anthropic spec — each block has ``type`` +
    ``text``/``image``/etc.), or ``None``. We project to the joined
    text so :class:`ToolCallEnd.output_summary` carries something
    meaningful for the drawer row's tail.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _project_usage(
    model_usage: dict[str, Any] | None,
    decision: RoutingDecision,
) -> tuple[int, int, int, int, int, int]:
    """Defer to :func:`bearings.agent.persistence.extract_model_usage`.

    Lazy-imported so :mod:`bearings.agent.translate` doesn't spread
    the persistence-layer surface to every caller (the translator is
    a thin wire-level translator; it shouldn't carry the assistant-row
    persistence types).
    """
    from bearings.agent.persistence import extract_model_usage

    breakdown = extract_model_usage(model_usage, decision)
    return (
        breakdown.executor_input_tokens,
        breakdown.executor_output_tokens,
        breakdown.advisor_input_tokens,
        breakdown.advisor_output_tokens,
        breakdown.advisor_calls_count,
        breakdown.cache_read_tokens,
    )


def _project_context_usage(
    usage: dict[str, Any],
) -> tuple[float, int, int, str | None, bool | None, int | None] | None:
    """Project the SDK's ``usage`` dict onto the six-tuple the
    :class:`ContextUsage` event carries.

    Returns ``None`` if any required field (``percentage`` /
    ``totalTokens`` / ``maxTokens``) is absent so the caller can omit
    the event rather than emit a partially-populated one.

    The SDK exposes ``percentage`` / ``totalTokens`` / ``maxTokens`` /
    ``model`` / ``isAutoCompactEnabled`` / ``autoCompactThreshold`` in
    camelCase per arch §5 #10; this projection accepts either camelCase
    or snake_case for forward-compat. The three optional fields degrade
    to ``None`` when absent (older SDK builds).
    """
    pct = usage.get("percentage")
    total = usage.get("totalTokens", usage.get("total_tokens"))
    max_tokens = usage.get("maxTokens", usage.get("max_tokens"))
    if not isinstance(pct, (int, float)):
        return None
    if not isinstance(total, int) or not isinstance(max_tokens, int):
        return None
    raw_model = usage.get("model")
    model: str | None = raw_model if isinstance(raw_model, str) else None
    raw_iac = usage.get("isAutoCompactEnabled", usage.get("is_auto_compact_enabled"))
    is_auto_compact: bool | None = bool(raw_iac) if raw_iac is not None else None
    raw_thresh = usage.get("autoCompactThreshold", usage.get("auto_compact_threshold"))
    threshold: int | None = raw_thresh if isinstance(raw_thresh, int) else None
    return float(pct), total, max_tokens, model, is_auto_compact, threshold


__all__ = [
    "SDKEventTranslator",
]
