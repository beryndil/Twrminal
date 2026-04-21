"""WebSocket handler for agent sessions.

This is now a thin subscriber on top of `SessionRunner`. The runner
owns the `AgentSession`, the stream loop, and event persistence; the
handler just forwards incoming control frames (`prompt`, `stop`,
`set_permission_mode`) and pushes outbound events to the socket.

Disconnect no longer stops the agent — the runner keeps going, and a
reconnect (optionally with `?since_seq=N`) replays any buffered events
that arrived while the client was away. That's what makes sessions
independent: you can walk away from a question mid-stream, do work in
another session, and come back to the finished result.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from claude_agent_sdk import ThinkingConfig
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from bearings import metrics
from bearings.agent.runner import SessionRunner, _Envelope
from bearings.agent.session import AgentSession
from bearings.api.auth import check_ws_auth
from bearings.config import ThinkingMode
from bearings.db import store

log = logging.getLogger(__name__)


def _thinking_config(mode: ThinkingMode | None) -> ThinkingConfig | None:
    """Translate the `agent.thinking` config knob into the SDK's
    ThinkingConfig TypedDict. Kept in the session wiring layer so the
    SDK type stays an implementation detail of ws_agent."""
    if mode == "adaptive":
        return {"type": "adaptive"}
    if mode == "disabled":
        return {"type": "disabled"}
    return None


router = APIRouter(tags=["agent-ws"])

CODE_UNAUTHORIZED = 4401
CODE_SESSION_NOT_FOUND = 4404


async def _build_runner(app: Any, session_id: str) -> SessionRunner:
    """Construct a SessionRunner wired to app-scoped state. Used as
    the factory passed into `RunnerRegistry.get_or_create`
    (`bearings.agent.registry`) — keeps all the FastAPI-specific wiring
    out of the runner module."""
    conn = app.state.db
    row = await store.get_session(conn, session_id)
    assert row is not None, "caller must verify the session exists first"
    agent = AgentSession(
        session_id,
        row["working_dir"],
        row["model"],
        max_budget_usd=row.get("max_budget_usd"),
        db=conn,
        sdk_session_id=row.get("sdk_session_id"),
        # Restore the user's last PermissionMode (migration 0012) so a
        # browser reload or socket drop doesn't silently roll them back
        # to 'default'. NULL in the DB → None here → 'default' behavior
        # in the SDK.
        permission_mode=row.get("permission_mode"),
        thinking=_thinking_config(app.state.settings.agent.thinking),
    )
    runner = SessionRunner(session_id, agent, conn)
    # Late-bind the approval callback: the SDK's `can_use_tool` hook
    # parks futures on the runner, but the runner only exists after
    # the agent is constructed. Binding here keeps the agent ignorant
    # of the runner (circular import otherwise) while giving the SDK
    # a real coroutine to call when a gated tool wants permission.
    agent.can_use_tool = runner.can_use_tool
    return runner


def _parse_since_seq(websocket: WebSocket) -> int:
    """Read the client's replay cursor from the query string. Clients
    track the last seq they've rendered per session; on reconnect they
    pass it so the runner replays only events newer than that. Missing
    or malformed values fall back to 0 (replay whatever's in the
    buffer) — the frontend dedupes completed messages by id, so
    double-replay is harmless."""
    raw = websocket.query_params.get("since_seq")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


async def _forward_events(websocket: WebSocket, queue: asyncio.Queue[_Envelope]) -> None:
    """Pull envelopes off the runner's subscriber queue and write them
    to the socket. Each frame carries `_seq` so the client can advance
    its replay cursor. Exits on send failure (disconnect)."""
    while True:
        env = await queue.get()
        frame = {**env.payload, "_seq": env.seq}
        try:
            await websocket.send_json(frame)
        except (WebSocketDisconnect, RuntimeError):
            # Socket died under us — normal at navigation. The outer
            # handler's finally block will clean up the subscription.
            return


@router.websocket("/ws/sessions/{session_id}")
async def agent_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    if not check_ws_auth(websocket):
        await websocket.close(code=CODE_UNAUTHORIZED)
        return
    app = websocket.app
    conn = app.state.db
    row = await store.get_session(conn, session_id)
    if row is None:
        await websocket.close(code=CODE_SESSION_NOT_FOUND)
        return

    since_seq = _parse_since_seq(websocket)
    registry = app.state.runners
    runner = await registry.get_or_create(session_id, factory=lambda sid: _build_runner(app, sid))
    queue, replay = await runner.subscribe(since_seq)

    metrics.ws_active_connections.inc()
    app.state.active_ws.add(websocket)

    # Ground-truth status snapshot sent as the first frame on every
    # connection. After a server restart the new runner's ring buffer
    # is empty, so a client that disconnected mid-turn never receives
    # a `message_complete` — `streamingActive` would stay true forever.
    # This frame lets the client reconcile: if it thought a turn was
    # live but the runner is idle, it's safe to clear the streaming
    # fringe and refresh from DB (the old runner's shutdown path
    # persisted the partial). Sent before replay so the client has a
    # known starting point before the event stream resumes.
    try:
        await websocket.send_json(
            {
                "type": "runner_status",
                "session_id": session_id,
                "is_running": runner.is_running,
            }
        )
    except (WebSocketDisconnect, RuntimeError):
        runner.unsubscribe(queue)
        app.state.active_ws.discard(websocket)
        metrics.ws_active_connections.dec()
        return

    # Replay next so the client sees missed events in order before any
    # live frame arrives.
    for env in replay:
        try:
            await websocket.send_json({**env.payload, "_seq": env.seq})
        except (WebSocketDisconnect, RuntimeError):
            runner.unsubscribe(queue)
            app.state.active_ws.discard(websocket)
            metrics.ws_active_connections.dec()
            return

    forwarder = asyncio.create_task(
        _forward_events(websocket, queue), name=f"ws-forward:{session_id}"
    )
    try:
        while True:
            payload = await websocket.receive_json()
            msg_type = payload.get("type")
            if msg_type == "prompt":
                prompt = str(payload.get("content", ""))
                await runner.submit_prompt(prompt)
            elif msg_type == "stop":
                await runner.request_stop()
            elif msg_type == "set_permission_mode":
                mode = payload.get("mode")
                # Async now because the runner also retro-applies the
                # new mode to any parked approval (see the broker's
                # `resolve_for_mode` matrix). Await so an
                # `approval_resolved` fan-out gets on the wire before we
                # consider ourselves ready for the next frame.
                await runner.set_permission_mode(mode or None)
            elif msg_type == "approval_response":
                # Resolves a pending `can_use_tool` future. Unknown /
                # already-resolved ids are no-ops inside the runner, so
                # two tabs racing to answer the same modal is safe.
                request_id = payload.get("request_id")
                decision = payload.get("decision")
                reason = payload.get("reason")
                if isinstance(request_id, str) and decision in ("allow", "deny"):
                    await runner.resolve_approval(
                        request_id,
                        decision,
                        reason if isinstance(reason, str) else None,
                    )
            # Unknown message types are ignored — keeps the protocol
            # forward-compatible the same way it was pre-refactor.
    except WebSocketDisconnect:
        # Normal disconnect. The runner keeps running; that's the
        # point of this whole refactor.
        pass
    except Exception:
        log.exception("ws %s: unexpected error in receive loop", session_id)
    finally:
        forwarder.cancel()
        try:
            await forwarder
        except (asyncio.CancelledError, Exception):
            pass
        runner.unsubscribe(queue)
        app.state.active_ws.discard(websocket)
        metrics.ws_active_connections.dec()
