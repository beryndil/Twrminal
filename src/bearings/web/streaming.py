"""Per-session streaming WebSocket handler.

Item 1.2 — implements the WebSocket route ``/ws/sessions/{session_id}``
the SvelteKit frontend (item 2.x) connects to. Two responsibilities:

1. Replay buffered events from the runner's ring buffer (the
   ``since_seq=N`` query parameter resumes from a known point per
   ``docs/behavior/tool-output-streaming.md`` §"Reconnect / replay").
2. Stream live events as the runner emits them, with a heartbeat ping
   when no event has arrived in
   :data:`bearings.config.constants.STREAM_HEARTBEAT_INTERVAL_S`
   seconds (per behavior doc §"Long-tool keepalive").

Frame format is owned by :mod:`bearings.web.serialize`; this module
only orchestrates timing + subscriber bookkeeping.

Backpressure decision (behavior doc is silent — reasoning trail per
``CLAUDE.md`` §autonomy contract):

* Subscriber queues are unbounded by construction (see
  :class:`bearings.agent.runner.SessionRunner`). On a slow client the
  queue grows in process memory; the cost is bounded by per-runner
  ring buffer cap (RING_BUFFER_MAX events) plus whatever is in flight.
* This is acceptable because Bearings is localhost-only — the slow
  client is the SvelteKit tab's render loop, not a network. A future
  network-deployment surface would impose a queue ceiling here; the
  TODO is the next reasonable change point.

Reconnect-semantics decision (behavior doc explicit):

* On WS close (any cause), :func:`serve_session_stream` unsubscribes
  the queue. The runner's ring buffer keeps every event, capped at
  :data:`bearings.config.constants.RING_BUFFER_MAX`.
* On reconnect with ``since_seq=N``, the next handler call replays
  events from the buffer with seq > N, then live-streams. Per
  behavior doc the user observes "any chunks the agent emitted while
  the client was away are replayed in order — the user sees the tool
  row's body fill in retroactively, then live streaming resumes from
  where it left off."

References:

* ``docs/behavior/tool-output-streaming.md`` — load-bearing.
* ``docs/architecture-v1.md`` §1.1.5 — streaming-handler responsibility.
* ``docs/architecture-v1.md`` §1.1.2 — heartbeat / ring-buffer constants.
"""

from __future__ import annotations

import asyncio
from typing import Final

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from bearings.agent.runner import SessionRunner, StreamEntry
from bearings.config.constants import STREAM_HEARTBEAT_INTERVAL_S
from bearings.web.serialize import event_frame, heartbeat_frame

# Query-parameter name the frontend uses to resume from a known seq
# per behavior doc §"Reconnect / replay". Kept here as a Final so a
# rename at the call site fails type-check rather than silently
# breaking the contract.
SINCE_SEQ_QUERY_PARAM: Final[str] = "since_seq"


async def serve_session_stream(
    websocket: WebSocket,
    runner: SessionRunner,
    *,
    since_seq: int = 0,
    heartbeat_interval_s: float = STREAM_HEARTBEAT_INTERVAL_S,
) -> None:
    """Drive one WebSocket subscriber to ``runner`` until disconnect.

    Sequence:

    1. ``await websocket.accept()`` to complete the handshake.
    2. Atomic snapshot + queue registration via
       :meth:`SessionRunner.subscribe`.
    3. Send each replay entry as a separate event frame (oldest first).
    4. Send a :class:`bearings.agent.events.RunnerStatusEvent` frame
       (seq=0) so the client can reconcile ``streamingActive`` after
       replay — fixes the indefinite spinner on reconnect mid-turn.
    5. Loop: ``await queue.get()`` with a
       ``heartbeat_interval_s`` timeout; on timeout, send a heartbeat
       frame; on event, send an event frame.
    6. On any disconnect (client close, server shutdown), unsubscribe
       and return cleanly. Runner survives the WS close — the next
       reconnect resumes from the ring buffer.

    The function does not raise on :class:`WebSocketDisconnect` — that
    is the normal termination for the WS subscriber lifecycle. Other
    exceptions propagate so the FastAPI app can log + return 1011.

    ``heartbeat_interval_s`` is kwarg-overridable so tests can use a
    short interval (≪ 15s default) without sleeping.
    """
    if since_seq < 0:
        raise ValueError(f"since_seq must be >= 0 (got {since_seq})")
    if heartbeat_interval_s <= 0:
        raise ValueError(f"heartbeat_interval_s must be > 0 (got {heartbeat_interval_s})")
    await websocket.accept()
    replay, queue = runner.subscribe(since_seq=since_seq)
    try:
        await _send_replay(websocket, replay)
        # Seq=0 is intentional: RunnerStatusEvent is synthetic (never
        # stored in the ring buffer) so it has no real seq. The frontend
        # handles it before the seq-dedup filter, so seq=0 is safe even
        # when the client's lastSeq is already > 0.
        await websocket.send_text(event_frame(0, runner.get_status_event()))
        await _stream_live(websocket, queue, heartbeat_interval_s)
    except WebSocketDisconnect:
        # Normal client-initiated close.
        return
    finally:
        runner.unsubscribe(queue)


async def _send_replay(
    websocket: WebSocket,
    replay: list[StreamEntry],
) -> None:
    """Push replay entries to the client as event frames, oldest first."""
    for seq, event in replay:
        await websocket.send_text(event_frame(seq, event))


async def _stream_live(
    websocket: WebSocket,
    queue: asyncio.Queue[StreamEntry],
    heartbeat_interval_s: float,
) -> None:
    """Drain ``queue`` to ``websocket``, heartbeating on idle.

    Loops until :class:`WebSocketDisconnect` propagates (the caller's
    ``except`` clause catches it) — the WS layer's read side is what
    detects client close in FastAPI/Starlette; on detection
    :meth:`websocket.send_text` raises :class:`WebSocketDisconnect`.
    """
    while True:
        try:
            seq, event = await asyncio.wait_for(queue.get(), heartbeat_interval_s)
        except TimeoutError:
            # ``asyncio.wait_for`` raises the builtin ``TimeoutError``
            # in Python 3.11+. Heartbeat-on-idle path per behavior doc
            # §"Long-tool keepalive".
            await websocket.send_text(heartbeat_frame())
            continue
        await websocket.send_text(event_frame(seq, event))


__all__ = ["SINCE_SEQ_QUERY_PARAM", "serve_session_stream"]
