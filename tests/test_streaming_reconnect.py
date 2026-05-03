"""Reconnect / replay tests — :mod:`bearings.agent.runner` + streaming.

Per ``docs/behavior/tool-output-streaming.md`` §"Reconnect / replay":
"any chunks the agent emitted while the client was away are replayed
in order — the user sees the tool row's body fill in retroactively,
then live streaming resumes from where it left off."

The chosen reconnect semantic is **resume-with-replay** (the rebuild's
ring-buffer surface), not commit-on-disconnect. Reasoning trail per
``CLAUDE.md`` §autonomy contract:

* Behavior doc explicitly prescribes the user-visible behavior:
  "tool row's body fills in retroactively." That requires replaying
  buffered events, not discarding them.
* Implementation: per-runner ring buffer (cap
  :data:`bearings.config.constants.RING_BUFFER_MAX`) keeps every event
  emitted in the buffer's window; new subscribers' ``since_seq``
  cursor selects the suffix to replay.

Covered surfaces:

* Subscribing on a fresh runner with default cursor (replay everything).
* Subscribing with ``since_seq=N`` skips events with seq ≤ N.
* Multiple subscribers receive identical streams.
* Late-attaching subscriber receives buffered events emitted before
  the subscribe call.
* Ring buffer eviction — subscriber with ``since_seq < oldest`` gets
  only what's left in the buffer (no replay of evicted events).
* Unsubscribe is idempotent.
* The runner's status snapshot survives subscribe/unsubscribe cycles
  so the WS first frame can paint the badge after reconnect.
"""

from __future__ import annotations

import asyncio

import pytest

from bearings.agent.events import (
    AgentEvent,
    MessageComplete,
    MessageStart,
    RunnerStatusEvent,
    Token,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
)
from bearings.agent.routing import RoutingDecision
from bearings.agent.runner import RunnerStatus, SessionRunner

# ---------------------------------------------------------------------------
# Replay path — since_seq=0 (full buffer) and since_seq=N (suffix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_replays_all_buffered_events_when_since_seq_zero() -> None:
    runner = SessionRunner("s1")
    events = _three_events()
    for event in events:
        await runner.emit(event)
    replay, queue = runner.subscribe(since_seq=0)
    assert [event for _seq, event in replay] == events
    assert queue.empty()


@pytest.mark.asyncio
async def test_subscribe_with_since_seq_skips_already_seen() -> None:
    runner = SessionRunner("s1")
    events = _three_events()
    for event in events:
        await runner.emit(event)
    # since_seq=2 → expect only event with seq=3
    replay, _queue = runner.subscribe(since_seq=2)
    assert len(replay) == 1
    seq, event = replay[0]
    assert seq == 3
    assert event == events[2]


@pytest.mark.asyncio
async def test_subscribe_with_since_seq_at_or_above_last_returns_empty() -> None:
    runner = SessionRunner("s1")
    for event in _three_events():
        await runner.emit(event)
    replay, _queue = runner.subscribe(since_seq=runner.last_seq)
    assert replay == []


@pytest.mark.asyncio
async def test_subscribe_rejects_negative_since_seq() -> None:
    runner = SessionRunner("s1")
    with pytest.raises(ValueError, match=">= 0"):
        runner.subscribe(since_seq=-1)


# ---------------------------------------------------------------------------
# Live path — events emitted after subscribe land in queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_events_after_subscribe_arrive_in_queue() -> None:
    runner = SessionRunner("s1")
    replay, queue = runner.subscribe()
    assert replay == []
    events = _three_events()
    for event in events:
        await runner.emit(event)
    received: list[AgentEvent] = []
    for _ in events:
        _seq, event = await asyncio.wait_for(queue.get(), timeout=1.0)
        received.append(event)
    assert received == events


@pytest.mark.asyncio
async def test_subscribe_atomicity_no_lost_events_between_replay_and_live() -> None:
    """Buffer pre-loaded with N events; subscribe; emit M more; expect
    replay + live = N + M, no duplicates, no drops, contiguous seqs."""
    runner = SessionRunner("s1")
    pre = _three_events()
    for event in pre:
        await runner.emit(event)
    replay, queue = runner.subscribe(since_seq=0)
    post = [
        Token(session_id="s1", message_id="m2", delta="a"),
        Token(session_id="s1", message_id="m2", delta="b"),
    ]
    for event in post:
        await runner.emit(event)
    received: list[tuple[int, AgentEvent]] = list(replay)
    for _ in post:
        received.append(await asyncio.wait_for(queue.get(), timeout=1.0))
    assert [event for _seq, event in received] == [*pre, *post]
    seqs = [seq for seq, _e in received]
    assert seqs == list(range(1, 1 + len(pre) + len(post)))


# ---------------------------------------------------------------------------
# Multiple subscribers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_subscribers_receive_same_event_stream() -> None:
    runner = SessionRunner("s1")
    _replay_a, queue_a = runner.subscribe()
    _replay_b, queue_b = runner.subscribe()
    assert runner.subscriber_count == 2

    event = MessageStart(session_id="s1", message_id="m1")
    await runner.emit(event)

    seq_a, event_a = await asyncio.wait_for(queue_a.get(), timeout=1.0)
    seq_b, event_b = await asyncio.wait_for(queue_b.get(), timeout=1.0)
    assert seq_a == seq_b
    assert event_a == event_b == event


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving_live_events() -> None:
    runner = SessionRunner("s1")
    _replay, queue = runner.subscribe()
    runner.unsubscribe(queue)
    assert runner.subscriber_count == 0

    await runner.emit(MessageStart(session_id="s1", message_id="m1"))
    # Queue is empty — the unsubscribed handler doesn't get the event.
    assert queue.empty()


@pytest.mark.asyncio
async def test_unsubscribe_is_idempotent() -> None:
    runner = SessionRunner("s1")
    _replay, queue = runner.subscribe()
    runner.unsubscribe(queue)
    # Calling again is a no-op (no exception).
    runner.unsubscribe(queue)
    assert runner.subscriber_count == 0


# ---------------------------------------------------------------------------
# Ring buffer eviction — old events drop on overflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ring_buffer_caps_at_max() -> None:
    """The ring buffer never exceeds its cap; oldest events drop."""
    runner = SessionRunner("s1", ring_buffer_max=3)
    events = [Token(session_id="s1", message_id="m1", delta=str(i)) for i in range(5)]
    for event in events:
        await runner.emit(event)
    assert runner.ring_buffer_size == 3
    # Subscribe replays only what's still in the buffer.
    replay, _queue = runner.subscribe()
    assert len(replay) == 3
    # The replayed events are the most recent three (deltas "2", "3", "4").
    deltas = [e.delta for _seq, e in replay if isinstance(e, Token)]
    assert deltas == ["2", "3", "4"]


@pytest.mark.asyncio
async def test_ring_buffer_replay_after_eviction_preserves_seq_order() -> None:
    runner = SessionRunner("s1", ring_buffer_max=2)
    for i in range(4):
        await runner.emit(Token(session_id="s1", message_id="m1", delta=str(i)))
    replay, _queue = runner.subscribe(since_seq=0)
    seqs = [seq for seq, _e in replay]
    assert seqs == [3, 4]


# ---------------------------------------------------------------------------
# Status snapshot — survives subscribe/unsubscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_survives_resubscribe_cycle() -> None:
    """The runner's :class:`RunnerStatus` snapshot is independent of
    subscriber lifecycle so the WS first frame after reconnect can
    paint the routing badge."""
    runner = SessionRunner("s1")
    decision = RoutingDecision(
        executor_model="opus",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="high",
        source="manual",
        reason="set by user",
        matched_rule_id=None,
    )
    runner.set_status(
        RunnerStatus(
            is_running=True,
            is_awaiting_user=False,
            routing_decision=decision,
        )
    )
    _replay_a, queue_a = runner.subscribe()
    runner.unsubscribe(queue_a)
    _replay_b, _queue_b = runner.subscribe()
    # Status snapshot unchanged across the resubscribe cycle.
    assert runner.status.is_running is True
    assert runner.status.routing_decision == decision


# ---------------------------------------------------------------------------
# get_status_event — post-replay RunnerStatusEvent synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status_event_idle_runner() -> None:
    """Idle runner (is_running=False) → streaming_active=False, current_turn_id=None."""
    runner = SessionRunner("s1")
    # Status defaults to is_running=False on construction.
    event = runner.get_status_event()
    assert isinstance(event, RunnerStatusEvent)
    assert event.session_id == "s1"
    assert event.streaming_active is False
    assert event.current_turn_id is None


@pytest.mark.asyncio
async def test_get_status_event_running_with_message_start_in_buffer() -> None:
    """Running runner with a MessageStart in the ring buffer → current_turn_id set."""
    from bearings.agent.routing import RoutingDecision

    runner = SessionRunner("s1")
    runner.set_status(
        RunnerStatus(
            is_running=True,
            is_awaiting_user=False,
            routing_decision=RoutingDecision(
                executor_model="sonnet",
                advisor_model=None,
                advisor_max_uses=0,
                effort_level="auto",
                source="default",
                reason="default",
                matched_rule_id=None,
            ),
        )
    )
    await runner.emit(MessageStart(session_id="s1", message_id="msg-42"))
    event = runner.get_status_event()
    assert event.streaming_active is True
    assert event.current_turn_id == "msg-42"


@pytest.mark.asyncio
async def test_get_status_event_returns_most_recent_message_start_in_buffer() -> None:
    """When multiple MessageStart events are in the buffer, current_turn_id
    reflects the most recent one (reverse-scan semantics)."""
    from bearings.agent.routing import RoutingDecision

    runner = SessionRunner("s1")
    runner.set_status(
        RunnerStatus(
            is_running=True,
            is_awaiting_user=False,
            routing_decision=RoutingDecision(
                executor_model="sonnet",
                advisor_model=None,
                advisor_max_uses=0,
                effort_level="auto",
                source="default",
                reason="default",
                matched_rule_id=None,
            ),
        )
    )
    # First turn — complete.
    await runner.emit(MessageStart(session_id="s1", message_id="msg-first"))
    await runner.emit(MessageComplete(session_id="s1", message_id="msg-first", content="done"))
    # Second turn — in flight.
    await runner.emit(MessageStart(session_id="s1", message_id="msg-live"))
    event = runner.get_status_event()
    # Reverse scan should find the in-flight MessageStart first.
    assert event.streaming_active is True
    assert event.current_turn_id == "msg-live"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_session_runner_rejects_empty_session_id() -> None:
    with pytest.raises(ValueError, match="session_id"):
        SessionRunner("")


def test_session_runner_rejects_zero_or_negative_buffer_max() -> None:
    with pytest.raises(ValueError, match="ring_buffer_max"):
        SessionRunner("s1", ring_buffer_max=0)
    with pytest.raises(ValueError, match="ring_buffer_max"):
        SessionRunner("s1", ring_buffer_max=-1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _three_events() -> list[AgentEvent]:
    sid = "s1"
    return [
        ToolCallStart(
            session_id=sid,
            message_id="m1",
            tool_call_id="tc1",
            tool_name="Bash",
            tool_input_json='{"command": "echo hi"}',
        ),
        ToolOutputDelta(session_id=sid, tool_call_id="tc1", delta="hi\n"),
        ToolCallEnd(
            session_id=sid,
            message_id="m1",
            tool_call_id="tc1",
            ok=True,
            duration_ms=1,
            output_summary="ok",
        ),
    ]
