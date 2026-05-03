"""Integration tests — full streaming roundtrip with tool output deltas.

Done-when criterion #4 from master item 1.2: "Integration test:
roundtrip tool call with streamed output." Two complementary surfaces
exercised:

1. **FastAPI TestClient + replay** — boots the real ASGI app via
   :class:`fastapi.testclient.TestClient`, connects a real
   :class:`starlette.testclient.WebSocketTestSession`, verifies the
   WebSocket handshake + query-param parsing + replay path. Events
   are emitted into the runner's ring buffer *before* the WS connects;
   the handler delivers them via the replay path on subscribe.

2. **In-loop fake WebSocket + live emit** — runs
   :func:`bearings.web.streaming.serve_session_stream` directly with a
   :class:`_FakeWebSocket` recording every sent frame, while a
   concurrent producer task calls :meth:`SessionRunner.emit` to drive
   the live-stream path. This exercises intra-call tool output
   streaming end-to-end (``ToolCallStart`` → ``ToolOutputDeltaxN`` →
   ``ToolCallEnd``) without booting an HTTP server.

Both tests verify event ORDER + per-event content fidelity (the wire
frame round-trips back to the original :class:`AgentEvent` via
:func:`bearings.web.serialize.parse_frame`).
"""

from __future__ import annotations

import asyncio
import json
from typing import Final

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bearings.agent.events import (
    AgentEvent,
    MessageComplete,
    MessageStart,
    ToolCallEnd,
    ToolCallStart,
    ToolOutputDelta,
)
from bearings.agent.runner import RunnerFactory, SessionRunner
from bearings.web.app import create_app
from bearings.web.serialize import parse_frame
from bearings.web.streaming import serve_session_stream

# Heartbeat interval for tests — short so a missed event surfaces fast,
# but long enough that no heartbeat fires in a sub-second test path.
_TEST_HEARTBEAT_S: Final[float] = 5.0


# ---------------------------------------------------------------------------
# Fake WebSocket — captures send_text calls + raises WebSocketDisconnect
# after a configured number of frames so the handler exits cleanly.
# ---------------------------------------------------------------------------


class _FakeWebSocket:
    """Minimal :class:`fastapi.WebSocket` substitute for in-loop tests.

    Records every :meth:`send_text` call to :attr:`sent`. When the count
    reaches :attr:`close_after`, the next :meth:`send_text` raises
    :class:`WebSocketDisconnect` to terminate the handler loop the same
    way a real client close would.
    """

    def __init__(self, *, close_after: int) -> None:
        self.accepted: bool = False
        self.sent: list[str] = []
        self.close_after: int = close_after
        self.closed: bool = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        if len(self.sent) >= self.close_after:
            raise WebSocketDisconnect()
        self.sent.append(text)

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        del code, reason
        self.closed = True


# ---------------------------------------------------------------------------
# Surface 1 — FastAPI TestClient + replay path
# ---------------------------------------------------------------------------


def _capturing_factory() -> tuple[RunnerFactory, dict[str, SessionRunner]]:
    """Return a :class:`RunnerFactory` and a dict of created runners.

    The factory creates a fresh runner per ``session_id`` on first call
    and stores it in the dict so the test can manipulate the runner
    (emit events, inspect the ring buffer) before / after the WS opens.
    """
    runners: dict[str, SessionRunner] = {}

    async def factory(session_id: str) -> SessionRunner:
        if session_id not in runners:
            runners[session_id] = SessionRunner(session_id)
        return runners[session_id]

    return factory, runners


def test_websocket_handshake_and_replay_path() -> None:
    """A WS connect with pre-buffered events delivers them via replay.

    Order of operations:

    1. Build app with a capturing factory.
    2. Pre-create the runner; emit a tool-call sequence.
    3. Connect the WS (the runner's ring buffer holds the events).
    4. Receive frames in order; verify each frame round-trips back to
       the original :class:`AgentEvent`.
    5. Close the WS; the handler exits cleanly.
    """
    factory, runners = _capturing_factory()
    app = create_app(runner_factory=factory, heartbeat_interval_s=_TEST_HEARTBEAT_S)

    # Pre-populate the runner.
    runner = SessionRunner("sess-roundtrip")
    runners["sess-roundtrip"] = runner
    events = _tool_roundtrip_events()
    asyncio.run(_emit_all(runner, events))

    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/sessions/sess-roundtrip") as ws,
    ):
        received: list[AgentEvent] = []
        seqs: list[int] = []
        for _ in events:
            text = ws.receive_text()
            kind, seq, event = parse_frame(text)  # type: ignore[misc]
            assert kind == "event"
            received.append(event)
            seqs.append(seq)
        ws.close()

    assert received == events
    # Seqs are monotonic and contiguous from the first emitted event.
    assert seqs == list(range(1, 1 + len(events)))


def test_websocket_resume_with_since_seq() -> None:
    """``since_seq=N`` skips events with seq ≤ N on replay."""
    factory, runners = _capturing_factory()
    app = create_app(runner_factory=factory, heartbeat_interval_s=_TEST_HEARTBEAT_S)
    runner = SessionRunner("sess-resume")
    runners["sess-resume"] = runner
    events = _tool_roundtrip_events()
    asyncio.run(_emit_all(runner, events))

    # Resume from seq=2 → expect only events with seq > 2 (3..N).
    with (
        TestClient(app) as client,
        client.websocket_connect("/ws/sessions/sess-resume?since_seq=2") as ws,
    ):
        for expected_seq in range(3, 1 + len(events)):
            text = ws.receive_text()
            kind, seq, _event = parse_frame(text)  # type: ignore[misc]
            assert kind == "event"
            assert seq == expected_seq
        ws.close()


def test_websocket_invalid_since_seq_closes_with_1003() -> None:
    """Non-integer ``since_seq`` query param triggers a 1003 close."""
    factory, _runners = _capturing_factory()
    app = create_app(runner_factory=factory, heartbeat_interval_s=_TEST_HEARTBEAT_S)

    with (
        TestClient(app) as client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/sessions/s1?since_seq=not-int") as ws,
    ):
        ws.receive_text()
    assert exc_info.value.code == 1003


# ---------------------------------------------------------------------------
# Surface 2 — In-loop fake WebSocket + live emit path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_tool_output_streaming_roundtrip() -> None:
    """``ToolCallStart`` → ``ToolOutputDeltax3`` → ``ToolCallEnd`` arrive
    in order on a live WS subscriber, all via the in-loop fake.

    ``close_after`` is set to ``len(events) + 1`` because
    :func:`serve_session_stream` now emits one synthetic
    ``runner_status`` frame (seq=0) after the replay drain and before
    any live events arrive. The frame budget is: 1 (runner_status) +
    len(events), then the next idle heartbeat attempt triggers the
    fake's disconnect.
    """
    runner = SessionRunner("sess-live")
    events = _tool_roundtrip_events()
    fake_ws = _FakeWebSocket(close_after=len(events) + 1)

    async def producer() -> None:
        # Yield first so the handler enters its drain loop before any
        # event arrives. Tests both the wait-for-event path and the
        # event-arrives-while-waiting path (each emit wakes the queue).
        await asyncio.sleep(0)
        for event in events:
            await runner.emit(event)
            # Yield to let the handler send before the next emit; not
            # strictly required (queue is unbounded) but exercises the
            # real intra-call streaming pattern where events arrive
            # interleaved with sends.
            await asyncio.sleep(0)

    handler_task = asyncio.create_task(
        serve_session_stream(
            fake_ws,  # type: ignore[arg-type]
            runner,
            # Short heartbeat so the post-events idle wait triggers a
            # heartbeat send-attempt fast — the fake_ws raises
            # ``WebSocketDisconnect`` on that next send because the
            # ``close_after`` budget is already used up.
            heartbeat_interval_s=0.05,
        )
    )
    await producer()
    await asyncio.wait_for(handler_task, timeout=2.0)

    assert fake_ws.accepted is True
    # One extra runner_status frame precedes the actual events.
    assert len(fake_ws.sent) == len(events) + 1
    # First frame must be runner_status (seq=0, synthetic).
    first_kind, first_seq, first_event = parse_frame(fake_ws.sent[0])  # type: ignore[misc]
    assert first_kind == "event"
    assert first_seq == 0
    assert first_event.type == "runner_status"
    # Remaining frames are the live events in order.
    received: list[AgentEvent] = []
    seqs: list[int] = []
    for text in fake_ws.sent[1:]:
        kind, seq, event = parse_frame(text)  # type: ignore[misc]
        assert kind == "event"
        received.append(event)
        seqs.append(seq)
    assert received == events
    # Live path assigns contiguous monotonic seqs starting at 1.
    assert seqs == list(range(1, 1 + len(events)))


@pytest.mark.asyncio
async def test_live_streaming_preserves_tool_output_byte_order() -> None:
    """Many small deltas arriving in order are delivered in that order.

    Emulates a tool that produces stdout in many small writes (e.g. a
    streaming bash command) — every delta must reach the client with
    the same payload and in the same order.
    """
    runner = SessionRunner("sess-bytes")
    deltas = [f"chunk-{i:03d}\n" for i in range(20)]
    events: list[AgentEvent] = [
        ToolCallStart(
            session_id="sess-bytes",
            message_id="m1",
            tool_call_id="tc1",
            tool_name="Bash",
            tool_input_json='{"command": "stream"}',
        ),
        *[ToolOutputDelta(session_id="sess-bytes", tool_call_id="tc1", delta=d) for d in deltas],
        ToolCallEnd(
            session_id="sess-bytes",
            message_id="m1",
            tool_call_id="tc1",
            ok=True,
            duration_ms=10,
            output_summary="20 chunks",
        ),
    ]
    fake_ws = _FakeWebSocket(close_after=len(events))

    async def producer() -> None:
        await asyncio.sleep(0)
        for event in events:
            await runner.emit(event)
            await asyncio.sleep(0)

    handler_task = asyncio.create_task(
        serve_session_stream(
            fake_ws,  # type: ignore[arg-type]
            runner,
            heartbeat_interval_s=0.05,
        )
    )
    await producer()
    await asyncio.wait_for(handler_task, timeout=2.0)

    received: list[AgentEvent] = []
    for text in fake_ws.sent:
        _kind, _seq, event = parse_frame(text)  # type: ignore[misc]
        received.append(event)
    received_deltas = [e.delta for e in received if isinstance(e, ToolOutputDelta)]
    assert received_deltas == deltas


@pytest.mark.asyncio
async def test_heartbeat_fires_when_idle() -> None:
    """When no event arrives within heartbeat interval, a heartbeat
    frame is sent. Tests the long-tool keepalive surface per behavior
    doc §"Long-tool keepalive".

    ``close_after=3``: the handler now sends one ``runner_status`` frame
    (seq=0) right after the replay drain, then heartbeats on idle.
    Budget: 1 (runner_status) + 2 (heartbeats), then disconnect.
    """
    runner = SessionRunner("sess-idle")
    fake_ws = _FakeWebSocket(close_after=3)
    handler_task = asyncio.create_task(
        serve_session_stream(
            fake_ws,  # type: ignore[arg-type]
            runner,
            heartbeat_interval_s=0.05,  # short — fire fast
        )
    )
    # No producer — handler sends runner_status then heartbeats only.
    await asyncio.wait_for(handler_task, timeout=2.0)
    assert len(fake_ws.sent) == 3
    # First frame is the synthetic runner_status.
    first = json.loads(fake_ws.sent[0])
    assert first["kind"] == "event"
    assert first["event"]["type"] == "runner_status"
    # Remaining frames are heartbeats.
    for text in fake_ws.sent[1:]:
        payload = json.loads(text)
        assert payload["kind"] == "heartbeat"
        assert isinstance(payload["ts"], (int, float))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_roundtrip_events() -> list[AgentEvent]:
    """A canonical tool-call sequence the integration tests assert against.

    Per behavior doc §"When output begins streaming" the user observes:
    MessageStart → ToolCallStart → ToolOutputDeltaxN → ToolCallEnd →
    MessageComplete.
    """
    sid = "sess-roundtrip"
    return [
        MessageStart(session_id=sid, message_id="m1"),
        ToolCallStart(
            session_id=sid,
            message_id="m1",
            tool_call_id="tc1",
            tool_name="Bash",
            tool_input_json='{"command": "echo hi"}',
        ),
        ToolOutputDelta(session_id=sid, tool_call_id="tc1", delta="hi\n"),
        ToolOutputDelta(session_id=sid, tool_call_id="tc1", delta="more\n"),
        ToolCallEnd(
            session_id=sid,
            message_id="m1",
            tool_call_id="tc1",
            ok=True,
            duration_ms=12,
            output_summary="ok",
        ),
        MessageComplete(
            session_id=sid,
            message_id="m1",
            content="done",
            executor_input_tokens=10,
            executor_output_tokens=5,
        ),
    ]


async def _emit_all(runner: SessionRunner, events: list[AgentEvent]) -> None:
    for event in events:
        await runner.emit(event)
