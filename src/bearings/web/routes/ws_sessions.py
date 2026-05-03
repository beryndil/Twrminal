"""Sessions-broadcast WebSocket — ``/ws/sessions``.

Every time a session row is created, mutated, or deleted via any REST
route handler, the handler calls :meth:`SessionsBroadcaster.publish_*`.
The broadcaster fans the JSON frame to every connected ``/ws/sessions``
subscriber so all open browser tabs update without a full re-fetch.

Three message types (JSON objects sent as WebSocket text frames):

``session_upsert``
    A session row was created or updated. The full
    :class:`bearings.web.models.sessions.SessionOut` JSON is embedded
    so subscribers can replace-or-insert the row without a follow-up
    ``GET``.

``session_delete``
    A session row was deleted. Only ``session_id`` is carried (the row
    no longer exists so embedding a full object would be meaningless).

``runner_state``
    The per-session :class:`bearings.agent.runner.RunnerStatus`
    changed (idle → running or running → idle). The sidebar can render
    a "live" badge without subscribing to the heavier per-session
    ``/ws/sessions/{id}`` stream.

The broadcaster lives on ``app.state.sessions_broadcaster`` so any
route module can reach it without a circular import.

References:

* ``docs/architecture-v1.md`` §1.1.5 — web-layer route group.
* ``wiring-v1-daily-driver.md`` §2.6 — done-when: open two tabs; create
  session in A; B's sidebar updates without reload or polling.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Final

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from bearings.agent.runner import RunnerStatus
from bearings.config.constants import STREAM_HEARTBEAT_INTERVAL_S
from bearings.web.models.sessions import SessionOut

router = APIRouter()

# Wire-shape type discriminators — single source of truth so a typo
# at the call site fails comparison rather than silently routing wrong.
_MSG_SESSION_UPSERT: Final[str] = "session_upsert"
_MSG_SESSION_DELETE: Final[str] = "session_delete"
_MSG_RUNNER_STATE: Final[str] = "runner_state"


class SessionsBroadcaster:
    """Fan-out hub for sessions-level change events.

    Lightweight: all subscribers are unbounded
    :class:`asyncio.Queue[str]` instances carrying pre-serialised JSON
    frames. ``publish_*`` methods are synchronous so route handlers can
    call them without an extra ``await`` inside a thin handler body
    (per arch §1.1.5 "handler bodies are thin").

    Single-threaded asyncio: ``publish_*`` and ``subscribe`` are both
    synchronous and contain no awaits, so they are effectively atomic
    w.r.t. each other on the same event loop.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()

    def subscribe(self) -> asyncio.Queue[str]:
        """Register a new subscriber queue and return it."""
        q: asyncio.Queue[str] = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        """Remove ``q`` from the subscriber set; idempotent."""
        self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        """Number of currently connected subscribers."""
        return len(self._subscribers)

    def publish_upsert(self, session: SessionOut) -> None:
        """Fan out a ``session_upsert`` frame for ``session``."""
        frame = json.dumps(
            {
                "type": _MSG_SESSION_UPSERT,
                "session": session.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._fan_out(frame)

    def publish_delete(self, session_id: str) -> None:
        """Fan out a ``session_delete`` frame for ``session_id``."""
        frame = json.dumps(
            {"type": _MSG_SESSION_DELETE, "session_id": session_id},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._fan_out(frame)

    def publish_runner_state(self, session_id: str, status: RunnerStatus) -> None:
        """Fan out a ``runner_state`` frame for ``session_id``."""
        frame = json.dumps(
            {
                "type": _MSG_RUNNER_STATE,
                "session_id": session_id,
                "is_running": status.is_running,
                "is_awaiting_user": status.is_awaiting_user,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._fan_out(frame)

    def _fan_out(self, frame: str) -> None:
        """``put_nowait`` to every subscriber.

        Queues are unbounded (matching the per-session runner's
        subscriber-queue convention in :class:`SessionRunner`);
        ``put_nowait`` never raises :class:`asyncio.QueueFull` here.
        """
        for q in self._subscribers:
            q.put_nowait(frame)


def _broadcaster_from_ws(websocket: WebSocket) -> SessionsBroadcaster | None:
    """Pull the optional broadcaster off the app state carried in
    the WebSocket's ASGI scope.

    FastAPI/Starlette sets ``scope["app"]`` to the ``FastAPI`` instance
    for every request; ``app.state`` is the same ``State`` object that
    ``create_app`` writes ``sessions_broadcaster`` to.
    """
    app = websocket.scope.get("app")
    if app is None:
        return None
    return getattr(getattr(app, "state", None), "sessions_broadcaster", None)


@router.websocket("/ws/sessions")
async def sessions_broadcast_ws(websocket: WebSocket) -> None:
    """Broadcast sessions-channel events to one connected subscriber.

    Protocol:

    1. Accept the WebSocket.
    2. Subscribe to the :class:`SessionsBroadcaster` on ``app.state``.
    3. Loop: ``await queue.get()`` with a heartbeat timeout; send a
       heartbeat on idle, or the JSON frame on event.
    4. On any disconnect, unsubscribe and return.

    When no broadcaster is wired on ``app.state`` (e.g. in a test that
    constructs a minimal app without DB), the endpoint accepts the
    connection and sends only heartbeats — it degrades gracefully rather
    than rejecting the WS handshake.
    """
    await websocket.accept()
    broadcaster = _broadcaster_from_ws(websocket)
    q: asyncio.Queue[str] | None = broadcaster.subscribe() if broadcaster is not None else None
    try:
        while True:
            try:
                if q is None:
                    # No broadcaster wired — just heartbeat
                    await asyncio.sleep(STREAM_HEARTBEAT_INTERVAL_S)
                    await _send_heartbeat(websocket)
                    continue
                frame = await asyncio.wait_for(q.get(), STREAM_HEARTBEAT_INTERVAL_S)
                await websocket.send_text(frame)
            except TimeoutError:
                await _send_heartbeat(websocket)
    except WebSocketDisconnect:
        return
    finally:
        if broadcaster is not None and q is not None:
            broadcaster.unsubscribe(q)


async def _send_heartbeat(websocket: WebSocket) -> None:
    """Send a ``{"kind":"heartbeat","ts":<float>}`` ping frame."""
    await websocket.send_text(
        json.dumps(
            {"kind": "heartbeat", "ts": time.time()},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


__all__ = [
    "SessionsBroadcaster",
    "router",
]
