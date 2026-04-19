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
            "SELECT id, message_id, name, input, output, error, started_at, finished_at "
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
        frames = [json.loads(ws.receive_text()) for _ in range(4)]

    assert [f["type"] for f in frames] == [
        "message_start",
        "token",
        "token",
        "message_complete",
    ]
    assert [f["text"] for f in frames[1:3]] == ["hello ", "world"]
    assert frames[0]["message_id"] == frames[3]["message_id"] == "mock-msg"

    assert _read_messages(tmp_settings.storage.db_path, sid) == [
        ("user", "say hi"),
        ("assistant", "hello world"),
    ]


def test_ws_persists_tool_calls(
    client: TestClient, mock_agent_tool_stream: None, tmp_settings: Settings
) -> None:
    import time

    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        frames = [json.loads(ws.receive_text()) for _ in range(4)]

        # Stay inside the WS context while the server finishes its
        # post-send DB writes (assistant-message insert + tool-call
        # backfill). The TestClient may cancel the server task on
        # exit, so we must wait for the writes before closing.
        msg_id = frames[0]["message_id"]
        for _ in range(50):
            rows = _read_tool_calls(tmp_settings.storage.db_path, sid)
            if rows and rows[0]["message_id"] == msg_id:
                break
            time.sleep(0.02)

    assert [f["type"] for f in frames] == [
        "message_start",
        "tool_call_start",
        "tool_call_end",
        "message_complete",
    ]
    assert frames[0]["message_id"] == frames[3]["message_id"]

    rows = _read_tool_calls(tmp_settings.storage.db_path, sid)
    assert len(rows) == 1
    call = rows[0]
    assert call["id"] == "tool-1"
    assert call["message_id"] == msg_id
    assert call["name"] == "Read"
    assert call["input"] == '{"path": "/etc/hosts"}'
    assert call["output"] == "127.0.0.1 localhost"
    assert call["error"] is None
    assert call["started_at"] and call["finished_at"]


def test_ws_persists_thinking_on_assistant_message(
    client: TestClient, mock_agent_thinking_stream: None, tmp_settings: Settings
) -> None:
    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "think"})
        frames = [json.loads(ws.receive_text()) for _ in range(5)]

        import time

        # insert_message runs after the last send — poll until the
        # assistant row materialises before exiting the WS context.
        conn = sqlite3.connect(tmp_settings.storage.db_path)
        try:
            for _ in range(50):
                cur = conn.execute(
                    "SELECT thinking FROM messages WHERE session_id=? AND role='assistant'",
                    (sid,),
                )
                row = cur.fetchone()
                if row is not None and row[0]:
                    break
                time.sleep(0.02)
        finally:
            conn.close()

    types = [f["type"] for f in frames]
    assert types == [
        "message_start",
        "thinking",
        "thinking",
        "token",
        "message_complete",
    ]

    # History endpoint returns the persisted thinking.
    rows = client.get(f"/api/sessions/{sid}/messages").json()
    assistant = next(m for m in rows if m["role"] == "assistant")
    assert assistant["thinking"] == "first I consider... then I decide."
    user = next(m for m in rows if m["role"] == "user")
    assert user["thinking"] is None


def test_ws_accumulates_session_cost(client: TestClient, mock_agent_cost_stream: None) -> None:
    sid = _create_session(client)
    before = client.get(f"/api/sessions/{sid}").json()
    assert before["total_cost_usd"] == 0

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "go"})
        frames = [json.loads(ws.receive_text()) for _ in range(3)]

        import time

        # Cost UPDATE runs after the MessageComplete frame is sent; poll.
        for _ in range(50):
            row = client.get(f"/api/sessions/{sid}").json()
            if row["total_cost_usd"] > 0:
                break
            time.sleep(0.02)

    assert [f["type"] for f in frames] == ["message_start", "token", "message_complete"]
    assert frames[2]["cost_usd"] == pytest.approx(0.01)

    after = client.get(f"/api/sessions/{sid}").json()
    assert after["total_cost_usd"] == pytest.approx(0.01)

    # Second turn accumulates.
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "again"})
        for _ in range(3):
            ws.receive_text()
        for _ in range(50):
            row = client.get(f"/api/sessions/{sid}").json()
            if row["total_cost_usd"] >= 0.02:
                break
            time.sleep(0.02)

    final = client.get(f"/api/sessions/{sid}").json()
    assert final["total_cost_usd"] == pytest.approx(0.02)


def test_ws_registers_and_deregisters_active_connection(
    client: TestClient, mock_agent_stream: None
) -> None:
    sid = _create_session(client)
    assert len(client.app.state.active_ws) == 0  # type: ignore[attr-defined]
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "hi"})
        # Read at least one frame so the server has executed its setup.
        ws.receive_text()
        assert len(client.app.state.active_ws) == 1  # type: ignore[attr-defined]
    # Server-side cleanup is async; poll briefly for the deregister.
    import time

    for _ in range(50):
        if len(client.app.state.active_ws) == 0:  # type: ignore[attr-defined]
            break
        time.sleep(0.02)
    assert len(client.app.state.active_ws) == 0  # type: ignore[attr-defined]


def test_ws_stop_frame_persists_partial_turn(
    client: TestClient, mock_agent_long_stream: None, tmp_settings: Settings
) -> None:
    import time

    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "long task"})
        # Read the message_start and a few tokens, then interrupt.
        start = json.loads(ws.receive_text())
        assert start["type"] == "message_start"
        first_tokens = [json.loads(ws.receive_text()) for _ in range(3)]
        assert all(f["type"] == "token" for f in first_tokens)

        ws.send_json({"type": "stop"})

        # Drain until we hit message_complete. Must come long before
        # the 200-token natural end.
        frames: list[dict] = []
        while True:
            f = json.loads(ws.receive_text())
            frames.append(f)
            if f["type"] == "message_complete":
                break
            assert len(frames) < 200, "stop should break out well before natural end"
        assert frames[-1]["message_id"] == start["message_id"]

        for _ in range(50):
            rows = _read_messages(tmp_settings.storage.db_path, sid)
            if len(rows) >= 2:
                break
            time.sleep(0.02)

    # Partial assistant content persisted — includes at least the tokens
    # the test observed, and fewer than the full 200.
    rows = _read_messages(tmp_settings.storage.db_path, sid)
    assert rows[0] == ("user", "long task")
    role, assistant_content = rows[1]
    assert role == "assistant"
    assert assistant_content.startswith("t0 t1 t2 ")
    assert "t199" not in assistant_content  # natural end did not arrive


def test_ws_ignores_unknown_payload_types(client: TestClient, mock_agent_stream: None) -> None:
    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "noop", "content": "ignored"})
        ws.send_json({"type": "prompt", "content": "go"})
        frames = [json.loads(ws.receive_text()) for _ in range(4)]
    assert [f["type"] for f in frames] == [
        "message_start",
        "token",
        "token",
        "message_complete",
    ]
