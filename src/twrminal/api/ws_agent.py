from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from twrminal import metrics
from twrminal.agent.events import (
    MessageComplete,
    MessageStart,
    Thinking,
    Token,
    ToolCallEnd,
    ToolCallStart,
)
from twrminal.agent.session import AgentSession
from twrminal.api.auth import check_ws_auth
from twrminal.db import store

router = APIRouter(tags=["agent-ws"])

CODE_UNAUTHORIZED = 4401
CODE_SESSION_NOT_FOUND = 4404


async def _ws_reader(websocket: WebSocket, incoming: asyncio.Queue[dict[str, Any] | None]) -> None:
    """Drain inbound WS frames into a queue. Puts None on disconnect so
    the consumer can break cleanly. Running this as a dedicated task
    lets the outer streaming loop peek for stop signals without racing
    itself on `receive_json`."""
    try:
        while True:
            payload = await websocket.receive_json()
            await incoming.put(payload)
    except WebSocketDisconnect:
        await incoming.put(None)
    except Exception:
        await incoming.put(None)


def _drain_stop(incoming: asyncio.Queue[dict[str, Any] | None]) -> bool:
    """Non-blocking: pop any queued stop frames. Returns True if one
    was seen. Other message types are discarded (we don't expect them
    mid-stream)."""
    saw_stop = False
    while not incoming.empty():
        payload = incoming.get_nowait()
        if payload is None:
            # Disconnect marker — treat as implicit stop so the caller
            # can wind down cleanly. The outer loop also sees None.
            saw_stop = True
            # Put the marker back so the outer loop sees it too.
            incoming.put_nowait(None)
            break
        if payload.get("type") == "stop":
            saw_stop = True
    return saw_stop


async def _persist_assistant_turn(
    conn: Any,
    *,
    session_id: str,
    message_id: str,
    content: str,
    thinking: str | None,
    tool_call_ids: list[str],
    cost_usd: float | None,
) -> None:
    await store.insert_message(
        conn,
        session_id=session_id,
        id=message_id,
        role="assistant",
        content=content,
        thinking=thinking,
    )
    metrics.messages_persisted.labels(role="assistant").inc()
    await store.attach_tool_calls_to_message(
        conn,
        message_id=message_id,
        tool_call_ids=tool_call_ids,
    )
    if cost_usd is not None:
        await store.add_session_cost(conn, session_id, cost_usd)


@router.websocket("/ws/sessions/{session_id}")
async def agent_ws(websocket: WebSocket, session_id: str) -> None:  # noqa: C901
    await websocket.accept()
    if not check_ws_auth(websocket):
        await websocket.close(code=CODE_UNAUTHORIZED)
        return
    conn = websocket.app.state.db
    row = await store.get_session(conn, session_id)
    if row is None:
        await websocket.close(code=CODE_SESSION_NOT_FOUND)
        return

    metrics.ws_active_connections.inc()
    websocket.app.state.active_ws.add(websocket)
    agent = AgentSession(
        session_id,
        row["working_dir"],
        row["model"],
        max_budget_usd=row.get("max_budget_usd"),
    )
    incoming: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    reader = asyncio.create_task(_ws_reader(websocket, incoming))
    try:
        while True:
            payload = await incoming.get()
            if payload is None:
                break  # disconnect
            if payload.get("type") != "prompt":
                # Stop-without-an-active-stream is a no-op.
                continue
            prompt = str(payload.get("content", ""))
            await store.insert_message(conn, session_id=session_id, role="user", content=prompt)
            metrics.messages_persisted.labels(role="user").inc()

            buf: list[str] = []
            thinking_buf: list[str] = []
            tool_call_ids: list[str] = []
            current_message_id: str | None = None
            persisted = False
            stopped = False
            async for event in agent.stream(prompt):
                await websocket.send_text(event.model_dump_json())
                metrics.ws_events_sent.labels(type=event.type).inc()
                if isinstance(event, MessageStart):
                    current_message_id = event.message_id
                elif isinstance(event, Token):
                    buf.append(event.text)
                elif isinstance(event, Thinking):
                    thinking_buf.append(event.text)
                elif isinstance(event, ToolCallStart):
                    await store.insert_tool_call_start(
                        conn,
                        session_id=session_id,
                        tool_call_id=event.tool_call_id,
                        name=event.name,
                        input_json=json.dumps(event.input),
                    )
                    tool_call_ids.append(event.tool_call_id)
                    metrics.tool_calls_started.inc()
                elif isinstance(event, ToolCallEnd):
                    await store.finish_tool_call(
                        conn,
                        tool_call_id=event.tool_call_id,
                        output=event.output,
                        error=event.error,
                    )
                    metrics.tool_calls_finished.labels(ok=str(event.ok).lower()).inc()
                elif isinstance(event, MessageComplete):
                    await _persist_assistant_turn(
                        conn,
                        session_id=session_id,
                        message_id=event.message_id,
                        content="".join(buf),
                        thinking="".join(thinking_buf) or None,
                        tool_call_ids=tool_call_ids,
                        cost_usd=event.cost_usd,
                    )
                    persisted = True
                    break  # turn finished naturally
                # Check for client stop between events. Break out early
                # and synthesise a MessageComplete so the assistant turn
                # still persists.
                if _drain_stop(incoming):
                    stopped = True
                    break

            if stopped and not persisted:
                msg_id = current_message_id or uuid4().hex
                synthetic = MessageComplete(session_id=session_id, message_id=msg_id, cost_usd=None)
                await websocket.send_text(synthetic.model_dump_json())
                metrics.ws_events_sent.labels(type=synthetic.type).inc()
                await _persist_assistant_turn(
                    conn,
                    session_id=session_id,
                    message_id=msg_id,
                    content="".join(buf),
                    thinking="".join(thinking_buf) or None,
                    tool_call_ids=tool_call_ids,
                    cost_usd=None,
                )
    except WebSocketDisconnect:
        return
    finally:
        reader.cancel()
        websocket.app.state.active_ws.discard(websocket)
        metrics.ws_active_connections.dec()
