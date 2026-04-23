"""WebSocket broadcast channel for the session list.

Complements the per-session `/ws/sessions/{id}` stream: this endpoint is
sessions-list-level and carries only the frames the sidebar needs to
stay live — upserts, deletes, and runner-state transitions.

Pairs with `bearings.agent.sessions_broker.SessionsBroker`:
- Mutation points (session CRUD routes + runner state changes) call
  `publish(...)` on the broker.
- Each open `/ws/sessions` subscriber has a bounded queue; this handler
  drains its own queue and pushes frames out as text.

Auth mirrors `ws_agent`: same bearer token via `?token=` query param
when `auth.enabled` is set. Clients pass through `check_ws_auth`; a
failure closes with 4401 before any subscription is registered.

No replay window — unlike per-session runners, this broker doesn't
buffer for reconnect. The frontend's Phase-1 `softRefresh` on connect
reconciles the list from `/api/sessions`, so a freshly-connected client
doesn't miss state even though it missed intermediate events.
"""

from __future__ import annotations

import asyncio
import logging

import orjson
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from bearings import metrics
from bearings.api.auth import check_ws_auth, check_ws_origin

log = logging.getLogger(__name__)

router = APIRouter(tags=["sessions-ws"])

CODE_UNAUTHORIZED = 4401
# 2026-04-21 security audit §1: same cross-origin guard as the
# per-session agent socket. Both endpoints share the same threat model
# (attacker tab in same browser) so both enforce the same policy.
CODE_FORBIDDEN_ORIGIN = 4403


@router.websocket("/ws/sessions")
async def sessions_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    if not check_ws_origin(websocket):
        await websocket.close(code=CODE_FORBIDDEN_ORIGIN, reason="origin not allowed")
        return
    if not check_ws_auth(websocket):
        await websocket.close(code=CODE_UNAUTHORIZED)
        return

    app = websocket.app
    broker = getattr(app.state, "sessions_broker", None)
    if broker is None:
        # Lifespan didn't wire a broker. Treat as not-running rather
        # than 500 — closes cleanly so the client backoff doesn't
        # hammer a broken server.
        await websocket.close(code=CODE_UNAUTHORIZED, reason="broker unavailable")
        return

    queue = broker.subscribe()
    metrics.ws_active_connections.inc()
    app.state.active_ws.add(websocket)

    # Forwarder drains the subscriber queue onto the socket. Kept as a
    # separate task so the receive loop below can pick up any
    # client-initiated close / ping frames without starving the fanout.
    async def _forward() -> None:
        while True:
            event = await queue.get()
            try:
                await websocket.send_text(orjson.dumps(event).decode())
            except (WebSocketDisconnect, RuntimeError):
                # Socket is gone; receive loop will observe it too and
                # the finally block handles cleanup.
                return

    forwarder = asyncio.create_task(_forward(), name="ws-sessions-forward")
    try:
        # The client doesn't send anything meaningful on this channel —
        # it's a one-way broadcast. We still drain `receive()` so a
        # close frame from the peer unblocks us promptly instead of
        # sitting on the send path until the TCP keepalive fires.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws /ws/sessions: unexpected error in receive loop")
    finally:
        forwarder.cancel()
        try:
            await forwarder
        except (asyncio.CancelledError, Exception):
            pass
        broker.unsubscribe(queue)
        app.state.active_ws.discard(websocket)
        metrics.ws_active_connections.dec()
