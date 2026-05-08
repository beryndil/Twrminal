"""Sessions-broadcast WebSocket — ``/ws/sessions``.

Every time a session row is created, mutated, or deleted via any REST
route handler, the handler calls :meth:`SessionsBroadcaster.publish_*`.
The broadcaster fans the JSON frame to every connected ``/ws/sessions``
subscriber so all open browser tabs update without a full re-fetch.

Five message types (JSON objects sent as WebSocket text frames):

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

``tag_upsert``
    A tag row was created or updated. The full
    :class:`bearings.web.models.tags.TagOut` JSON is embedded.
    Filter panels in all open tabs can update without a round-trip.

``tag_delete``
    A tag row was deleted. Only ``tag_id`` (int) is carried.

The broadcaster lives on ``app.state.sessions_broadcaster`` so any
route module can reach it without a circular import.

Subscriber queue overflow policy (CCW-3 / feature-5-011):
    Each subscriber queue is bounded at
    :data:`bearings.config.constants.SESSIONS_BROADCAST_QUEUE_MAX`
    frames. A subscriber that stops draining (hung browser tab) will
    fill its queue and trigger ``QueueFull`` on the next
    :meth:`SessionsBroadcaster._fan_out` call. The broadcaster then:

    1. Removes the subscriber from the fan-out set so healthy
       subscribers are never blocked.
    2. Calls the subscriber's registered ``on_overflow`` callback,
       which schedules ``websocket.close(code=4000)`` via
       ``asyncio.create_task``. The WS handler exits on the next
       send attempt.
    3. Logs a structured warning with the queue depth at overflow time.

References:

* ``docs/architecture-v1.md`` §1.1.5 — web-layer route group.
* ``wiring-v1-daily-driver.md`` §2.6 — done-when: open two tabs; create
  session in A; B's sidebar updates without reload or polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Final

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from bearings.agent.runner import RunnerStatus
from bearings.config.constants import SESSIONS_BROADCAST_QUEUE_MAX, STREAM_HEARTBEAT_INTERVAL_S
from bearings.web.models.sessions import SessionOut
from bearings.web.models.tags import TagOut

_LOG = logging.getLogger(__name__)

router = APIRouter()

# Wire-shape type discriminators — single source of truth so a typo
# at the call site fails comparison rather than silently routing wrong.
_MSG_SESSION_UPSERT: Final[str] = "session_upsert"
_MSG_SESSION_DELETE: Final[str] = "session_delete"
_MSG_RUNNER_STATE: Final[str] = "runner_state"
_MSG_TAG_UPSERT: Final[str] = "tag_upsert"
_MSG_TAG_DELETE: Final[str] = "tag_delete"

# WS close code used when a subscriber queue overflows (4000 = application-
# defined; means "dropped for slow consumption").
_WS_CLOSE_OVERFLOW: Final[int] = 4000


class SessionsBroadcaster:
    """Fan-out hub for sessions-level and tag-level change events.

    Subscribers are :class:`asyncio.Queue[str]` instances carrying
    pre-serialised JSON frames. ``publish_*`` methods are synchronous
    so route handlers call them without an extra ``await`` inside a
    thin handler body (per arch §1.1.5 "handler bodies are thin").

    Subscriber queue safety (CCW-3):
        * Queues are bounded at
          :data:`~bearings.config.constants.SESSIONS_BROADCAST_QUEUE_MAX`
          frames. When ``put_nowait`` raises :class:`asyncio.QueueFull`
          the slow subscriber is dropped immediately and its
          ``on_overflow`` callback is called so the owning WS handler
          can schedule a close (see :meth:`subscribe`).
        * :meth:`_fan_out` snapshots ``self._subscribers`` with
          ``list(self._subscribers.items())`` before iterating so a
          concurrent ``subscribe`` / ``unsubscribe`` call cannot mutate
          the set mid-loop and raise :class:`RuntimeError`.
    """

    def __init__(self) -> None:
        # Maps each subscriber queue to its optional overflow callback.
        # Using a dict instead of a bare set lets us store the callback
        # alongside the queue without a separate parallel structure.
        self._subscribers: dict[asyncio.Queue[str], Callable[[], None] | None] = {}

    def subscribe(
        self,
        *,
        on_overflow: Callable[[], None] | None = None,
    ) -> asyncio.Queue[str]:
        """Register a new bounded subscriber queue and return it.

        Parameters
        ----------
        on_overflow:
            Optional synchronous zero-arg callable invoked when this
            subscriber's queue overflows (``QueueFull``). The WS handler
            typically passes ``lambda: asyncio.create_task(ws.close(code=4000))``
            here so the hung connection is torn down without blocking the
            fan-out loop.
        """
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=SESSIONS_BROADCAST_QUEUE_MAX)
        self._subscribers[q] = on_overflow
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        """Remove ``q`` from the subscriber map; idempotent."""
        self._subscribers.pop(q, None)

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
                "is_error": status.is_error,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._fan_out(frame)

    def publish_tag_upsert(self, tag: TagOut) -> None:
        """Fan out a ``tag_upsert`` frame for ``tag``.

        Called by every tag-mutation route (POST /api/tags,
        PATCH /api/tags/{id}, PATCH /api/tags/{id}/pinned,
        PUT /api/tags/sort-order) after the DB write commits so all
        open tabs can update their filter panels without polling.
        """
        frame = json.dumps(
            {
                "type": _MSG_TAG_UPSERT,
                "tag": tag.model_dump(mode="json"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._fan_out(frame)

    def publish_tag_delete(self, tag_id: int) -> None:
        """Fan out a ``tag_delete`` frame carrying ``tag_id``.

        Called by DELETE /api/tags/{id} after the row is removed so
        all open tabs can drop the tag from their local caches.
        """
        frame = json.dumps(
            {"type": _MSG_TAG_DELETE, "tag_id": tag_id},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        self._fan_out(frame)

    def _fan_out(self, frame: str) -> None:
        """``put_nowait`` to every subscriber.

        Iterates a snapshot (``list(self._subscribers.items())``) so a
        concurrent ``subscribe`` / ``unsubscribe`` call cannot mutate
        the underlying dict mid-loop and raise :class:`RuntimeError`.
        This is the reentrant-caller-safety snapshot required by
        CCW-3 / feature-5-010.

        When a subscriber's queue is full (hung / slow client):

        1. The subscriber is removed from the map immediately so it no
           longer blocks future fan-outs.
        2. Its ``on_overflow`` callback (if any) is invoked
           synchronously — the WS handler's callback schedules an async
           websocket close via ``asyncio.create_task`` so the hung
           connection is eventually torn down.
        3. A structured warning is emitted with the configured cap.
        """
        for q, on_overflow in list(self._subscribers.items()):
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                _LOG.warning(
                    "sessions_broadcaster: subscriber queue full at cap=%d; "
                    "dropping slow subscriber",
                    SESSIONS_BROADCAST_QUEUE_MAX,
                )
                self._subscribers.pop(q, None)
                if on_overflow is not None:
                    on_overflow()


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
    2. Subscribe to the :class:`SessionsBroadcaster` on ``app.state``,
       passing an overflow callback that schedules ``websocket.close``
       via ``asyncio.create_task`` if the queue overflows (CCW-3
       / feature-5-011 overflow policy).
    3. Loop: ``await queue.get()`` with a heartbeat timeout; send a
       heartbeat on idle, or the JSON frame on event.
    4. On any disconnect (or when the overflow callback fires and the
       next send raises), unsubscribe and return.

    When no broadcaster is wired on ``app.state`` (e.g. in a test that
    constructs a minimal app without DB), the endpoint accepts the
    connection and sends only heartbeats — it degrades gracefully rather
    than rejecting the WS handshake.
    """
    await websocket.accept()
    broadcaster = _broadcaster_from_ws(websocket)
    q: asyncio.Queue[str] | None
    if broadcaster is not None:

        def _on_overflow() -> None:
            # Called synchronously from _fan_out when this subscriber's
            # queue is full. Schedule the close asynchronously so we
            # don't block the fan-out loop with an await.
            asyncio.create_task(  # noqa: RUF006
                websocket.close(code=_WS_CLOSE_OVERFLOW),
                name="ws_overflow_close",
            )

        q = broadcaster.subscribe(on_overflow=_on_overflow)
    else:
        q = None
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
