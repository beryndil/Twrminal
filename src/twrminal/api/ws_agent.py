from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from twrminal import metrics
from twrminal.agent.events import (
    MessageComplete,
    MessageStart,
    Token,
    ToolCallEnd,
    ToolCallStart,
)
from twrminal.agent.session import AgentSession
from twrminal.db import store

router = APIRouter(tags=["agent-ws"])

CODE_SESSION_NOT_FOUND = 4404


@router.websocket("/ws/sessions/{session_id}")
async def agent_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    conn = websocket.app.state.db
    row = await store.get_session(conn, session_id)
    if row is None:
        await websocket.close(code=CODE_SESSION_NOT_FOUND)
        return

    metrics.ws_active_connections.inc()
    agent = AgentSession(
        session_id,
        row["working_dir"],
        row["model"],
        max_budget_usd=row.get("max_budget_usd"),
    )
    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("type") != "prompt":
                continue
            prompt = str(payload.get("content", ""))
            await store.insert_message(conn, session_id=session_id, role="user", content=prompt)
            metrics.messages_persisted.labels(role="user").inc()
            buf: list[str] = []
            tool_call_ids: list[str] = []
            async for event in agent.stream(prompt):
                await websocket.send_text(event.model_dump_json())
                metrics.ws_events_sent.labels(type=event.type).inc()
                if isinstance(event, MessageStart):
                    continue
                if isinstance(event, Token):
                    buf.append(event.text)
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
                    await store.insert_message(
                        conn,
                        session_id=session_id,
                        id=event.message_id,
                        role="assistant",
                        content="".join(buf),
                    )
                    metrics.messages_persisted.labels(role="assistant").inc()
                    await store.attach_tool_calls_to_message(
                        conn,
                        message_id=event.message_id,
                        tool_call_ids=tool_call_ids,
                    )
                    buf.clear()
                    tool_call_ids.clear()
    except WebSocketDisconnect:
        return
    finally:
        metrics.ws_active_connections.dec()
