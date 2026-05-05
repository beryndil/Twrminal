"""Unit tests for ``bearings.agent.translate.SDKEventTranslator``.

Per Slice A1 of ``~/.claude/plans/wiring-agent-loop.md``: the
translator is the pure-translation layer between SDK message types
and the wire-side ``AgentEvent`` discriminated union. These tests
construct synthetic SDK messages and assert on the yielded events
directly — no SDK subprocess or runner needed.
"""

from __future__ import annotations

import json

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
from bearings.agent.translate import SDKEventTranslator


def _decision() -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="medium",
        source="default",
        reason="test",
        matched_rule_id=None,
    )


def _translator() -> SDKEventTranslator:
    return SDKEventTranslator(session_id="ses_t", decision=_decision())


# ---------------------------------------------------------------------------
# StreamEvent partials → Token / Thinking / MessageStart
# ---------------------------------------------------------------------------


def test_stream_event_message_start_emits_message_start_and_captures_id() -> None:
    t = _translator()
    frame = StreamEvent(
        uuid="u1",
        session_id="ses_t",
        event={"type": "message_start", "message": {"id": "msg_42"}},
    )
    events = list(t.feed(frame))
    assert events == [MessageStart(session_id="ses_t", message_id="msg_42")]
    assert t.message_id == "msg_42"


def test_text_delta_after_message_start_yields_token() -> None:
    t = _translator()
    list(
        t.feed(
            StreamEvent(
                uuid="u1",
                session_id="ses_t",
                event={"type": "message_start", "message": {"id": "msg_1"}},
            )
        )
    )
    delta_frame = StreamEvent(
        uuid="u2",
        session_id="ses_t",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}},
    )
    events = list(t.feed(delta_frame))
    assert events == [Token(session_id="ses_t", message_id="msg_1", delta="Hello")]


def test_thinking_delta_yields_thinking_event() -> None:
    t = _translator()
    list(
        t.feed(
            StreamEvent(
                uuid="u1",
                session_id="ses_t",
                event={"type": "message_start", "message": {"id": "msg_1"}},
            )
        )
    )
    frame = StreamEvent(
        uuid="u2",
        session_id="ses_t",
        event={
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "I should think..."},
        },
    )
    events = list(t.feed(frame))
    assert events == [Thinking(session_id="ses_t", message_id="msg_1", delta="I should think...")]


def test_text_delta_before_message_start_is_dropped() -> None:
    """Defensive: an orphan delta before message_start does not crash."""
    t = _translator()
    frame = StreamEvent(
        uuid="u1",
        session_id="ses_t",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": "x"}},
    )
    assert list(t.feed(frame)) == []


def test_empty_text_delta_emits_nothing() -> None:
    t = _translator()
    list(
        t.feed(
            StreamEvent(
                uuid="u1",
                session_id="ses_t",
                event={"type": "message_start", "message": {"id": "msg_1"}},
            )
        )
    )
    frame = StreamEvent(
        uuid="u2",
        session_id="ses_t",
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": ""}},
    )
    assert list(t.feed(frame)) == []


def test_unknown_event_type_is_no_op() -> None:
    t = _translator()
    frame = StreamEvent(
        uuid="u1",
        session_id="ses_t",
        event={"type": "content_block_stop", "index": 0},
    )
    assert list(t.feed(frame)) == []


# ---------------------------------------------------------------------------
# AssistantMessage — text accumulation + tool_use
# ---------------------------------------------------------------------------


def test_assistant_message_with_text_block_accumulates_body() -> None:
    t = _translator()
    msg = AssistantMessage(
        content=[TextBlock(text="The answer is 4.")],
        model="claude-sonnet",
        message_id="msg_a",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        stop_reason="end_turn",
        session_id="ses_t",
        uuid="u-a",
    )
    events = list(t.feed(msg))
    # First AssistantMessage emits MessageStart (no partials path).
    assert events == [MessageStart(session_id="ses_t", message_id="msg_a")]
    assert t.final_body() == "The answer is 4."


def test_assistant_message_with_partials_does_not_double_emit_message_start() -> None:
    t = _translator()
    list(
        t.feed(
            StreamEvent(
                uuid="u1",
                session_id="ses_t",
                event={"type": "message_start", "message": {"id": "msg_a"}},
            )
        )
    )
    msg = AssistantMessage(
        content=[TextBlock(text="x")],
        model="claude-sonnet",
        message_id="msg_a",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        stop_reason="end_turn",
        session_id="ses_t",
        uuid="u-a",
    )
    events = list(t.feed(msg))
    assert events == []  # no double MessageStart
    assert t.final_body() == "x"


def test_assistant_message_with_tool_use_emits_tool_call_start() -> None:
    t = _translator()
    msg = AssistantMessage(
        content=[
            TextBlock(text="Let me check."),
            ToolUseBlock(id="tool_1", name="Read", input={"file_path": "/tmp/x"}),
        ],
        model="claude-sonnet",
        message_id="msg_b",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        stop_reason="tool_use",
        session_id="ses_t",
        uuid="u-b",
    )
    events = list(t.feed(msg))
    assert events[0] == MessageStart(session_id="ses_t", message_id="msg_b")
    tool_event = events[1]
    assert isinstance(tool_event, ToolCallStart)
    assert tool_event.tool_call_id == "tool_1"
    assert tool_event.tool_name == "Read"
    assert json.loads(tool_event.tool_input_json) == {"file_path": "/tmp/x"}
    assert t.final_body() == "Let me check."


def test_thinking_block_does_not_pollute_canonical_body() -> None:
    t = _translator()
    msg = AssistantMessage(
        content=[
            ThinkingBlock(thinking="hidden", signature="sig"),
            TextBlock(text="visible"),
        ],
        model="claude-sonnet",
        message_id="msg_c",
        parent_tool_use_id=None,
        error=None,
        usage=None,
        stop_reason="end_turn",
        session_id="ses_t",
        uuid="u-c",
    )
    list(t.feed(msg))
    assert t.final_body() == "visible"


# ---------------------------------------------------------------------------
# UserMessage — tool result echo → ToolCallEnd
# ---------------------------------------------------------------------------


def test_tool_result_emits_tool_call_end_with_duration() -> None:
    t = _translator()
    list(
        t.feed(
            AssistantMessage(
                content=[ToolUseBlock(id="tool_1", name="Bash", input={"cmd": "ls"})],
                model="claude-sonnet",
                message_id="msg_x",
                parent_tool_use_id=None,
                error=None,
                usage=None,
                stop_reason="tool_use",
                session_id="ses_t",
                uuid="u-x",
            )
        )
    )
    user_echo = UserMessage(
        content=[ToolResultBlock(tool_use_id="tool_1", content="file_a\nfile_b\n", is_error=False)],
        uuid="u-y",
        parent_tool_use_id=None,
        tool_use_result=None,
    )
    events = list(t.feed(user_echo))
    assert len(events) == 1
    end = events[0]
    assert isinstance(end, ToolCallEnd)
    assert end.tool_call_id == "tool_1"
    assert end.ok is True
    assert end.output_summary == "file_a\nfile_b\n"
    assert end.error_message is None
    assert end.duration_ms >= 0


def test_tool_result_with_is_error_marks_call_failed() -> None:
    t = _translator()
    list(
        t.feed(
            AssistantMessage(
                content=[ToolUseBlock(id="tool_2", name="Bash", input={"cmd": "false"})],
                model="claude-sonnet",
                message_id="msg_x",
                parent_tool_use_id=None,
                error=None,
                usage=None,
                stop_reason="tool_use",
                session_id="ses_t",
                uuid="u-x",
            )
        )
    )
    user_echo = UserMessage(
        content=[ToolResultBlock(tool_use_id="tool_2", content="boom", is_error=True)],
        uuid="u-y",
        parent_tool_use_id=None,
        tool_use_result=None,
    )
    events = list(t.feed(user_echo))
    end = events[0]
    assert isinstance(end, ToolCallEnd)
    assert end.ok is False
    assert end.error_message == "boom"


def test_tool_result_with_block_list_content_joins_text() -> None:
    t = _translator()
    list(
        t.feed(
            AssistantMessage(
                content=[ToolUseBlock(id="tool_3", name="X", input={})],
                model="claude-sonnet",
                message_id="msg_x",
                parent_tool_use_id=None,
                error=None,
                usage=None,
                stop_reason="tool_use",
                session_id="ses_t",
                uuid="u-x",
            )
        )
    )
    user_echo = UserMessage(
        content=[
            ToolResultBlock(
                tool_use_id="tool_3",
                content=[
                    {"type": "text", "text": "line1"},
                    {"type": "text", "text": "line2"},
                ],
                is_error=False,
            )
        ],
        uuid="u-y",
        parent_tool_use_id=None,
        tool_use_result=None,
    )
    events = list(t.feed(user_echo))
    end = events[0]
    assert isinstance(end, ToolCallEnd)
    assert end.output_summary == "line1\nline2"


# ---------------------------------------------------------------------------
# ResultMessage — MessageComplete + ContextUsage + persist hook
# ---------------------------------------------------------------------------


def test_result_message_emits_message_complete_with_routing_usage() -> None:
    t = _translator()
    list(
        t.feed(
            AssistantMessage(
                content=[TextBlock(text="The answer is 4.")],
                model="claude-sonnet",
                message_id="msg_r",
                parent_tool_use_id=None,
                error=None,
                usage=None,
                stop_reason="end_turn",
                session_id="ses_t",
                uuid="u-r",
            )
        )
    )
    result = ResultMessage(
        subtype="success",
        duration_ms=1234,
        duration_api_ms=900,
        is_error=False,
        num_turns=1,
        session_id="ses_t",
        stop_reason="end_turn",
        total_cost_usd=0.001,
        usage={"percentage": 12.5, "totalTokens": 250, "maxTokens": 200_000},
        result=None,
        structured_output=None,
        model_usage={
            "claude-sonnet-4-6": {
                "inputTokens": 100,
                "outputTokens": 50,
                "cacheReadInputTokens": 25,
            }
        },
        permission_denials=None,
        errors=None,
        uuid="u-result",
    )
    events = list(t.feed(result))
    assert len(events) == 2
    complete, ctx = events
    assert isinstance(complete, MessageComplete)
    assert complete.message_id == "msg_r"
    assert complete.content == "The answer is 4."
    assert complete.executor_input_tokens == 100
    assert complete.executor_output_tokens == 50
    assert complete.cache_read_tokens == 25
    assert isinstance(ctx, ContextUsage)
    assert ctx.percentage == 12.5
    assert ctx.total_tokens == 250
    assert ctx.max_tokens == 200_000


def test_result_message_without_assistant_emits_error_event() -> None:
    """A ResultMessage with no preceding AssistantMessage surfaces as
    an ErrorEvent so the bubble shows the failure instead of silently
    completing nothing."""
    t = _translator()
    result = ResultMessage(
        subtype="error",
        duration_ms=10,
        duration_api_ms=10,
        is_error=True,
        num_turns=0,
        session_id="ses_t",
        stop_reason=None,
        total_cost_usd=None,
        usage=None,
        result="upstream rejected the request",
        structured_output=None,
        model_usage=None,
        permission_denials=None,
        errors=["rejected"],
        uuid="u-result",
    )
    events = list(t.feed(result))
    assert len(events) == 1
    err = events[0]
    assert isinstance(err, ErrorEvent)
    assert "upstream rejected" in err.message


def test_result_message_with_no_usage_omits_context_usage() -> None:
    t = _translator()
    list(
        t.feed(
            AssistantMessage(
                content=[TextBlock(text="x")],
                model="claude-sonnet",
                message_id="msg_r",
                parent_tool_use_id=None,
                error=None,
                usage=None,
                stop_reason="end_turn",
                session_id="ses_t",
                uuid="u-r",
            )
        )
    )
    result = ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=1,
        session_id="ses_t",
        stop_reason="end_turn",
        total_cost_usd=0.0,
        usage=None,
        result=None,
        structured_output=None,
        model_usage=None,
        permission_denials=None,
        errors=None,
        uuid="u-r",
    )
    events = list(t.feed(result))
    # MessageComplete only — no ContextUsage when usage is missing.
    assert len(events) == 1
    assert isinstance(events[0], MessageComplete)


# ---------------------------------------------------------------------------
# SystemMessage + unknown — no-op
# ---------------------------------------------------------------------------


def test_system_message_is_dropped() -> None:
    t = _translator()
    msg = SystemMessage(subtype="init", data={"version": "1"})
    assert list(t.feed(msg)) == []


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_begin_turn_resets_state() -> None:
    t = _translator()
    list(
        t.feed(
            AssistantMessage(
                content=[TextBlock(text="first")],
                model="claude-sonnet",
                message_id="msg_1",
                parent_tool_use_id=None,
                error=None,
                usage=None,
                stop_reason="end_turn",
                session_id="ses_t",
                uuid="u-1",
            )
        )
    )
    assert t.final_body() == "first"
    assert t.message_id == "msg_1"

    t.begin_turn()
    assert t.final_body() == ""
    assert t.message_id is None


def test_init_rejects_empty_session_id() -> None:
    import pytest

    with pytest.raises(ValueError, match="session_id must be non-empty"):
        SDKEventTranslator(session_id="", decision=_decision())
