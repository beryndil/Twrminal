from __future__ import annotations

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from twrminal.agent.events import MessageComplete, Token
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
