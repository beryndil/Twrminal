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
import time
from typing import Any

import orjson
from claude_agent_sdk import ThinkingConfig
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from bearings import metrics
from bearings.agent.runner import SessionRunner, _Envelope
from bearings.agent.session import AgentSession
from bearings.api.auth import check_ws_auth, check_ws_origin, ws_accept_subprotocol
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
# 2026-04-21 security audit §1: rejects cross-origin attachment so a
# malicious tab in the same browser can't drive the agent. Paired with
# `check_ws_origin` in `bearings.api.auth`.
CODE_FORBIDDEN_ORIGIN = 4403
# v0.4.0: a client tried to attach the agent loop to a non-chat
# session. Originally every non-chat kind (checklist, etc.) rejected
# here; v0.5.2 opened checklist sessions to the agent loop so the
# ChecklistView can host an embedded chat about the whole list. This
# code stays in the protocol for future session kinds that genuinely
# can't run an agent. 4400 = generic bad protocol input; paired with an
# explicit `reason` string.
CODE_SESSION_KIND_UNSUPPORTED = 4400

# Session kinds that can spawn an agent runner. Checklist sessions
# joined this set in v0.5.2 — the prompt assembler injects a
# `checklist_overview` layer so the agent sees the list's structure on
# every turn, and the ChecklistView frontend renders a compact chat
# panel above the list body.
_RUNNABLE_KINDS = {"chat", "checklist"}


async def _build_runner(app: Any, session_id: str) -> SessionRunner:
    """Construct a SessionRunner wired to app-scoped state. Used as
    the factory passed into `RunnerRegistry.get_or_create`
    (`bearings.agent.registry`) — keeps all the FastAPI-specific wiring
    out of the runner module."""
    conn = app.state.db
    row = await store.get_session(conn, session_id)
    assert row is not None, "caller must verify the session exists first"
    # Defense in depth: the WS handler already rejects unrunnable
    # session kinds before reaching the runner factory. If a future
    # caller (imports, migrations, tests) skips that gate, fail loudly
    # here rather than spawning an SDK subprocess that has nothing to
    # do.
    if row.get("kind", "chat") not in _RUNNABLE_KINDS:
        raise ValueError(
            f"cannot build runner for session kind={row.get('kind')!r}; "
            f"runnable kinds: {sorted(_RUNNABLE_KINDS)!r}"
        )
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
    runner = SessionRunner(
        session_id,
        agent,
        conn,
        # Pull the broker off app.state so runner publishes reach every
        # `/ws/sessions` subscriber. Absent on tests that skip the full
        # app wiring — `getattr` keeps the factory usable there.
        sessions_broker=getattr(app.state, "sessions_broker", None),
    )
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


async def _send_frame(websocket: WebSocket, frame: dict[str, Any]) -> None:
    """Serialize `frame` with orjson and push it as a text frame.

    Used for ad-hoc frames the runner ring buffer doesn't own (the
    `runner_status` snapshot emitted on connect). Hot-path envelope
    sends bypass this helper and use the pre-encoded `env.wire` string
    built in `_Envelope.__init__`, which saves one `orjson.dumps(...)
    .decode()` per subscriber per event. Starlette's stock `send_json`
    routes through the stdlib `json` encoder, which dominates CPU on
    event-heavy turns; orjson is ~2-3x faster on the dict/str/int
    payloads we send. We decode to str because the frontend contract
    is text frames — switching to `send_bytes` would flip the opcode
    and break the client."""
    await websocket.send_text(orjson.dumps(frame).decode())


# Idle ping cadence. When no envelope arrives for this long, the
# forwarder emits a `{type:"ping"}` frame. Two jobs: (1) surface TCP
# corpse sockets that `WebSocketDisconnect` missed — a dead half-open
# connection accepts a few queued writes before the kernel raises, so
# a failed send here breaks us out of the subscription and the finally
# block cleans up. (2) Complement `tool_progress`: progress ticks only
# fire while a tool call is live, so a completely idle session (no
# running turn, no tool work) would otherwise hold the socket silent
# forever. 15s is chosen to be well under the 60s Nginx default
# `proxy_read_timeout` so a reverse-proxy deployment won't drop the
# socket mid-idle; anyone fronting Bearings with a stricter proxy can
# still lose the socket but at least the diagnostic will appear in
# server logs rather than as a "why did my tab die" mystery.
WS_IDLE_PING_INTERVAL_S = 15.0


async def _forward_events(websocket: WebSocket, queue: asyncio.Queue[_Envelope]) -> None:
    """Pull envelopes off the runner's subscriber queue and write them
    to the socket. Each frame carries `_seq` so the client can advance
    its replay cursor. The envelope arrives with its wire form already
    encoded (see `_Envelope.__init__`), so the fan-out cost is a single
    `send_text` per subscriber — no per-send JSON serialization. Exits
    on send failure (disconnect).

    On idle (no envelope for `WS_IDLE_PING_INTERVAL_S`), emits a ping
    frame — see the constant's docstring for the two jobs it does.
    Pings carry no `_seq` (not in the ring buffer, not persisted) so a
    reconnecting client's replay cursor stays on real events only; the
    frontend reducer's `_seq` guard reads `typeof event._seq ===
    'number'` and skips the bump when absent."""
    while True:
        try:
            env = await asyncio.wait_for(queue.get(), timeout=WS_IDLE_PING_INTERVAL_S)
        except TimeoutError:
            try:
                # `ts` is server wall-clock in ms. Frontend doesn't need
                # it for anything structural — the reducer skips unknown
                # types — but logging / debugging a latency issue is
                # easier with a timestamp already on the frame.
                await websocket.send_text(
                    orjson.dumps({"type": "ping", "ts": int(time.time() * 1000)}).decode()
                )
            except (WebSocketDisconnect, RuntimeError):
                return
            continue
        try:
            await websocket.send_text(env.wire)
        except (WebSocketDisconnect, RuntimeError):
            # Socket died under us — normal at navigation. The outer
            # handler's finally block will clean up the subscription.
            return


@router.websocket("/ws/sessions/{session_id}")
async def agent_ws(websocket: WebSocket, session_id: str) -> None:
    # Echo the bearer-subprotocol marker when the client offered it so
    # browsers can deliver the token off-URL. `None` keeps today's
    # behavior for CLI (`bearings send`, query-string token) and for
    # clients that don't opt in. Never echoes `bearer.<tok>`; see
    # `ws_accept_subprotocol` in `bearings.api.auth`.
    await websocket.accept(subprotocol=ws_accept_subprotocol(websocket))
    # Origin check runs before auth so a cross-origin attacker can't
    # probe the auth error to distinguish configured-vs-unconfigured
    # servers. Both close before any subscription is registered.
    if not check_ws_origin(websocket):
        await websocket.close(code=CODE_FORBIDDEN_ORIGIN, reason="origin not allowed")
        return
    if not check_ws_auth(websocket):
        await websocket.close(code=CODE_UNAUTHORIZED)
        return
    app = websocket.app
    conn = app.state.db
    row = await store.get_session(conn, session_id)
    if row is None:
        await websocket.close(code=CODE_SESSION_NOT_FOUND)
        return
    if row.get("kind", "chat") not in _RUNNABLE_KINDS:
        # Future non-runnable kinds land here. Close loud so the bug
        # is obvious if a frontend ever tries to connect to a kind
        # whose UI should be local-only.
        await websocket.close(
            code=CODE_SESSION_KIND_UNSUPPORTED,
            reason="session kind does not support agent attachment",
        )
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
        await _send_frame(
            websocket,
            {
                "type": "runner_status",
                "session_id": session_id,
                "is_running": runner.is_running,
            },
        )
    except (WebSocketDisconnect, RuntimeError):
        runner.unsubscribe(queue)
        app.state.active_ws.discard(websocket)
        metrics.ws_active_connections.dec()
        return

    # Replay next so the client sees missed events in order before any
    # live frame arrives. Use the envelope's pre-encoded wire form so
    # a reconnecting tab doesn't pay N × orjson encode for the replay
    # window.
    for env in replay:
        try:
            await websocket.send_text(env.wire)
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
                # Optional sidecar from the composer's `[File N]`
                # attachment flow. The client sends raw dicts — we
                # filter to well-formed entries so a malformed payload
                # can't crash the runner, and a missing key just means
                # "plain-text prompt, no attachments."
                raw_attachments = payload.get("attachments")
                attachments: list[dict[str, Any]] = []
                if isinstance(raw_attachments, list):
                    for entry in raw_attachments:
                        if (
                            isinstance(entry, dict)
                            and isinstance(entry.get("n"), int)
                            and isinstance(entry.get("path"), str)
                        ):
                            attachments.append(
                                {
                                    "n": entry["n"],
                                    "path": entry["path"],
                                    "filename": str(entry.get("filename", "")),
                                    "size_bytes": int(entry.get("size_bytes", 0)),
                                }
                            )
                await runner.submit_prompt(prompt, attachments=attachments or None)
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
                # `updated_input` is the UI-collected override the SDK
                # will hand to the tool (AskUserQuestion answers ride
                # here). Non-dict values are dropped — we never want a
                # malformed payload to clobber the tool's actual input.
                request_id = payload.get("request_id")
                decision = payload.get("decision")
                reason = payload.get("reason")
                updated_input = payload.get("updated_input")
                if isinstance(request_id, str) and decision in ("allow", "deny"):
                    await runner.resolve_approval(
                        request_id,
                        decision,
                        reason if isinstance(reason, str) else None,
                        updated_input if isinstance(updated_input, dict) else None,
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
        # TEMP 2026-04-23: session-switch interrupt probe — capture WS
        # disconnect timing so it can be correlated with any interrupt
        # that fires around it. See bearings.agent._interrupt_probe.
        from bearings.agent._interrupt_probe import probe

        probe(
            "ws_agent.disconnect",
            session_id,
            running=runner.is_running,
            status=runner.status,
        )
        forwarder.cancel()
        try:
            await forwarder
        except (asyncio.CancelledError, Exception):
            pass
        runner.unsubscribe(queue)
        app.state.active_ws.discard(websocket)
        metrics.ws_active_connections.dec()
