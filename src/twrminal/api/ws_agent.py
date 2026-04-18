from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from twrminal.agent.events import MessageComplete, Token, ToolCallEnd, ToolCallStart
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

    agent = AgentSession(session_id, row["working_dir"], row["model"])
    try:
        while True:
            payload = await websocket.receive_json()
            if payload.get("type") != "prompt":
                continue
            prompt = str(payload.get("content", ""))
            await store.insert_message(conn, session_id=session_id, role="user", content=prompt)
            buf: list[str] = []
            async for event in agent.stream(prompt):
                await websocket.send_text(event.model_dump_json())
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
                elif isinstance(event, ToolCallEnd):
                    await store.finish_tool_call(
                        conn,
                        tool_call_id=event.tool_call_id,
                        output=event.output,
                        error=event.error,
                    )
                elif isinstance(event, MessageComplete):
                    await store.insert_message(
                        conn,
                        session_id=session_id,
                        role="assistant",
                        content="".join(buf),
                    )
                    buf.clear()
    except WebSocketDisconnect:
        return
