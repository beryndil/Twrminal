"""Unit tests — :mod:`bearings.web.serialize` round-trip + edge cases.

Covers:

* Every :class:`AgentEvent` variant round-trips ``event_frame`` →
  ``parse_frame`` losslessly.
* Heartbeat frames round-trip ``heartbeat_frame`` → ``parse_frame``.
* Malformed input raises the documented exceptions
  (:class:`ValueError` for envelope shape; :class:`pydantic.ValidationError`
  for event-object shape).
* Edge cases per behavior doc: large payloads, unicode, control
  characters, optional fields, nested fields.

Per arch §4.7 there are 16 :class:`AgentEvent` variants; one
parametrised case exercises a representative payload for each.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bearings.agent.events import (
    AgentEvent,
    ApprovalRequest,
    ApprovalResolved,
    ContextUsage,
    ErrorEvent,
    MessageComplete,
    MessageStart,
    RoutingBadge,
    RunnerStatusEvent,
    Thinking,
    TodoWriteUpdate,
    Token,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
    ToolProgress,
    TurnReplayed,
    UserMessage,
)
from bearings.web.serialize import (
    FRAME_KIND_EVENT,
    FRAME_KIND_HEARTBEAT,
    event_frame,
    heartbeat_frame,
    parse_frame,
)

# ---------------------------------------------------------------------------
# Round-trip parametrised across every AgentEvent variant
# ---------------------------------------------------------------------------


def _every_event() -> list[AgentEvent]:
    """One representative instance per :class:`AgentEvent` variant."""
    return [
        UserMessage(session_id="s1", message_id="m1", content="hello"),
        Token(session_id="s1", message_id="m1", delta="lo"),
        Thinking(session_id="s1", message_id="m1", delta="thinking..."),
        ToolCallStart(
            session_id="s1",
            message_id="m1",
            tool_call_id="tc1",
            tool_name="Bash",
            tool_input_json='{"command": "ls"}',
        ),
        ToolOutputDelta(session_id="s1", tool_call_id="tc1", delta="line1\n"),
        ToolCallEnd(
            session_id="s1",
            message_id="m1",
            tool_call_id="tc1",
            ok=True,
            duration_ms=42,
            output_summary="ok",
        ),
        ToolCallEnd(
            session_id="s1",
            message_id="m1",
            tool_call_id="tc2",
            ok=False,
            duration_ms=99,
            output_summary="fail",
            error_message="boom",
        ),
        ToolProgress(session_id="s1", tool_call_id="tc1", elapsed_ms=2000),
        MessageStart(session_id="s1", message_id="m1"),
        MessageComplete(
            session_id="s1",
            message_id="m1",
            content="done",
            executor_input_tokens=10,
            executor_output_tokens=5,
            advisor_input_tokens=2,
            advisor_output_tokens=1,
            advisor_calls_count=1,
            cache_read_tokens=100,
        ),
        MessageComplete(session_id="s1", message_id="m2", content="legacy"),
        ContextUsage(session_id="s1", percentage=42.0, total_tokens=1000, max_tokens=200_000),
        ErrorEvent(session_id="s1", message="oops", fatal=True),
        TurnReplayed(session_id="s1", message_id="m1"),
        ApprovalRequest(
            session_id="s1",
            request_id="req1",
            tool_name="Bash",
            tool_input_json='{"command": "rm -rf /"}',
        ),
        ApprovalResolved(session_id="s1", request_id="req1", approved=False),
        TodoWriteUpdate(session_id="s1", todos_json='[{"content": "do thing"}]'),
        RoutingBadge(
            session_id="s1",
            message_id="m1",
            executor_model="sonnet",
            advisor_model="opus",
            advisor_calls_count=2,
            effort_level="auto",
            routing_source="tag_rule",
            routing_reason="matched bearings/architect",
        ),
        RunnerStatusEvent(session_id="s1", streaming_active=True, current_turn_id="m1"),
        RunnerStatusEvent(session_id="s1", streaming_active=False, current_turn_id=None),
    ]


@pytest.mark.parametrize("event", _every_event())
def test_event_frame_roundtrip(event: AgentEvent) -> None:
    """Every event variant survives the wire format unchanged."""
    seq = 7
    text = event_frame(seq, event)
    kind, parsed_seq, parsed_event = parse_frame(text)  # type: ignore[misc]
    assert kind == "event"
    assert parsed_seq == seq
    assert parsed_event == event


def test_event_frame_is_single_line_json() -> None:
    event = Token(session_id="s1", message_id="m1", delta="x")
    text = event_frame(1, event)
    # Single-line JSON-Lines compatible (no embedded newlines).
    assert "\n" not in text
    payload = json.loads(text)
    assert payload["kind"] == FRAME_KIND_EVENT
    assert payload["seq"] == 1
    assert payload["event"]["type"] == "token"


# ---------------------------------------------------------------------------
# Heartbeat frame
# ---------------------------------------------------------------------------


def test_heartbeat_frame_roundtrip_with_explicit_ts() -> None:
    text = heartbeat_frame(ts=1700000000.5)
    kind, ts = parse_frame(text)  # type: ignore[misc]
    assert kind == "heartbeat"
    assert ts == 1700000000.5


def test_heartbeat_frame_default_ts_uses_current_time() -> None:
    text = heartbeat_frame()
    payload = json.loads(text)
    assert payload["kind"] == FRAME_KIND_HEARTBEAT
    assert isinstance(payload["ts"], (int, float))


# ---------------------------------------------------------------------------
# Edge cases — unicode, control chars, large payload
# ---------------------------------------------------------------------------


def test_event_frame_preserves_unicode() -> None:
    event = ToolOutputDelta(
        session_id="s1",
        tool_call_id="tc1",
        delta="日本語🦀​zero-width",
    )
    text = event_frame(1, event)
    _, _, parsed = parse_frame(text)  # type: ignore[misc]
    assert isinstance(parsed, ToolOutputDelta)
    assert parsed.delta == "日本語🦀​zero-width"


def test_event_frame_preserves_control_chars() -> None:
    # ANSI escape sequence + tab + null. Per behavior doc the streamed
    # bytes survive verbatim.
    delta = "\x1b[31mred\x1b[0m\ttab\x00null"
    event = ToolOutputDelta(session_id="s1", tool_call_id="tc1", delta=delta)
    text = event_frame(1, event)
    _, _, parsed = parse_frame(text)  # type: ignore[misc]
    assert isinstance(parsed, ToolOutputDelta)
    assert parsed.delta == delta


def test_event_frame_preserves_large_payload() -> None:
    delta = "x" * 100_000  # 100 KiB
    event = ToolOutputDelta(session_id="s1", tool_call_id="tc1", delta=delta)
    text = event_frame(1, event)
    _, _, parsed = parse_frame(text)  # type: ignore[misc]
    assert isinstance(parsed, ToolOutputDelta)
    assert len(parsed.delta) == 100_000


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------


def test_parse_frame_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_frame("not-json{")


def test_parse_frame_rejects_non_object_root() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_frame("[1, 2, 3]")


def test_parse_frame_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown frame kind"):
        parse_frame('{"kind": "mystery"}')


def test_parse_frame_rejects_event_with_bad_seq_type() -> None:
    payload = json.dumps({"kind": "event", "seq": "not-int", "event": {}})
    with pytest.raises(ValueError, match="must be int"):
        parse_frame(payload)


def test_parse_frame_rejects_event_with_negative_seq() -> None:
    payload = json.dumps({"kind": "event", "seq": -1, "event": {}})
    with pytest.raises(ValueError, match=">= 0"):
        parse_frame(payload)


def test_parse_frame_rejects_heartbeat_with_bad_ts_type() -> None:
    payload = json.dumps({"kind": "heartbeat", "ts": "not-a-number"})
    with pytest.raises(ValueError, match="must be number"):
        parse_frame(payload)


def test_parse_frame_rejects_event_with_bool_seq() -> None:
    """Python's ``bool`` is a subclass of ``int``; the validator
    explicitly rejects to avoid ``True == 1`` / ``False == 0``
    silently slipping through as a seq."""
    payload = json.dumps({"kind": "event", "seq": True, "event": {}})
    with pytest.raises(ValueError, match="must be int"):
        parse_frame(payload)


def test_parse_frame_rejects_event_with_malformed_event_object() -> None:
    """Wire-shape OK, but the event-object fails Pydantic
    discriminated-union validation — distinct exception class so the
    test can target the right failure mode."""
    payload = json.dumps(
        {
            "kind": "event",
            "seq": 1,
            "event": {"type": "token"},  # missing session_id, message_id, delta
        }
    )
    with pytest.raises(ValidationError):
        parse_frame(payload)


def test_event_frame_rejects_negative_seq() -> None:
    event = Token(session_id="s1", message_id="m1", delta="x")
    with pytest.raises(ValueError, match=">= 0"):
        event_frame(-1, event)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_exports_match_arch() -> None:
    from bearings.web import serialize as serialize_mod

    assert set(serialize_mod.__all__) == {
        "FRAME_KIND_EVENT",
        "FRAME_KIND_HEARTBEAT",
        "event_frame",
        "heartbeat_frame",
        "parse_frame",
    }
