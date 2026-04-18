from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from twrminal.config import Settings


def _create_session(client: TestClient) -> str:
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "title": None},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def _read_messages(db_path: Path, session_id: str) -> list[tuple[str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY created_at ASC, id ASC",
            (session_id,),
        )
        return [(row[0], row[1]) for row in cursor.fetchall()]
    finally:
        conn.close()


def _read_tool_calls(db_path: Path, session_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT id, name, input, output, error, started_at, finished_at "
            "FROM tool_calls WHERE session_id = ? ORDER BY started_at ASC, id ASC",
            (session_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def test_ws_unknown_session_closes_4404(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/ws/sessions/" + "0" * 32) as ws:
            ws.receive_text()
    assert excinfo.value.code == 4404


def test_ws_streams_events_and_persists_messages(
    client: TestClient, mock_agent_stream: None, tmp_settings: Settings
) -> None:
    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "say hi"})
        frames = [json.loads(ws.receive_text()) for _ in range(3)]

    assert [f["type"] for f in frames] == ["token", "token", "message_complete"]
    assert [f["text"] for f in frames[:2]] == ["hello ", "world"]
    assert frames[2]["message_id"] == "mock-msg"

    assert _read_messages(tmp_settings.storage.db_path, sid) == [
        ("user", "say hi"),
        ("assistant", "hello world"),
    ]


def test_ws_persists_tool_calls(
    client: TestClient, mock_agent_tool_stream: None, tmp_settings: Settings
) -> None:
    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        frames = [json.loads(ws.receive_text()) for _ in range(3)]
    assert [f["type"] for f in frames] == [
        "tool_call_start",
        "tool_call_end",
        "message_complete",
    ]
    rows = _read_tool_calls(tmp_settings.storage.db_path, sid)
    assert len(rows) == 1
    call = rows[0]
    assert call["id"] == "tool-1"
    assert call["name"] == "Read"
    assert call["input"] == '{"path": "/etc/hosts"}'
    assert call["output"] == "127.0.0.1 localhost"
    assert call["error"] is None
    assert call["started_at"] and call["finished_at"]


def test_ws_ignores_unknown_payload_types(client: TestClient, mock_agent_stream: None) -> None:
    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "noop", "content": "ignored"})
        ws.send_json({"type": "prompt", "content": "go"})
        frames = [json.loads(ws.receive_text()) for _ in range(3)]
    assert [f["type"] for f in frames] == ["token", "token", "message_complete"]
