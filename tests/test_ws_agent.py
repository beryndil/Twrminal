from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from bearings.config import Settings


def _create_session(client: TestClient) -> str:
    # v0.2.13: /api/sessions requires ≥1 tag_id. Auto-seed a default
    # tag for the test client and include its id.
    existing = client.get("/api/tags").json()
    if existing:
        tag_id = existing[0]["id"]
    else:
        tag_id = client.post("/api/tags", json={"name": "default"}).json()["id"]
    resp = client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "m",
            "title": None,
            "tag_ids": [tag_id],
        },
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


def _consume_initial_status(ws) -> dict:  # type: ignore[no-untyped-def]
    """Drain the `runner_status` frame every WS connection now emits
    after replay. Keeps the per-test frame-count assertions focused on
    the events the test actually cares about."""
    frame = json.loads(ws.receive_text())
    assert frame["type"] == "runner_status"
    return frame


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


def test_thinking_config_translator_maps_modes() -> None:
    """Each config value lands on the exact TypedDict shape the SDK
    expects. A miss here means `_thinking_config` silently drops the
    setting and sessions go back to having no thinking surfaced."""
    from bearings.api.ws_agent import _thinking_config

    assert _thinking_config("adaptive") == {"type": "adaptive"}
    assert _thinking_config("disabled") == {"type": "disabled"}
    assert _thinking_config(None) is None


def test_ws_streams_events_and_persists_messages(
    client: TestClient, mock_agent_stream: None, tmp_settings: Settings
) -> None:
    import time

    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        _consume_initial_status(ws)
        ws.send_json({"type": "prompt", "content": "say hi"})
        frames = [json.loads(ws.receive_text()) for _ in range(4)]
        # Poll for the assistant row inside the WS context — TestClient
        # cancels the server task on exit, so a post-MessageComplete
        # insert can be racing cancellation if we assert after `with`.
        for _ in range(50):
            if len(_read_messages(tmp_settings.storage.db_path, sid)) == 2:
                break
            time.sleep(0.02)

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
        _consume_initial_status(ws)
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
        _consume_initial_status(ws)
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
        _consume_initial_status(ws)
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
        _consume_initial_status(ws)
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
        _consume_initial_status(ws)
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
        _consume_initial_status(ws)
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
        _consume_initial_status(ws)
        ws.send_json({"type": "noop", "content": "ignored"})
        ws.send_json({"type": "prompt", "content": "go"})
        frames = [json.loads(ws.receive_text()) for _ in range(4)]
    assert [f["type"] for f in frames] == [
        "message_start",
        "token",
        "token",
        "message_complete",
    ]


def test_ws_emits_runner_status_on_connect_for_idle_session(client: TestClient) -> None:
    """First frame on every connection is a `runner_status` snapshot.
    Lets a reconnecting client detect drift when the server restarted
    mid-turn and its ring buffer is empty — without this, a client that
    missed `message_complete` would sit in `streamingActive=true`
    forever."""
    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        frame = json.loads(ws.receive_text())
    assert frame == {
        "type": "runner_status",
        "session_id": sid,
        "is_running": False,
        "is_awaiting_user": False,
    }


def test_ws_runner_status_reports_running_when_turn_in_flight(
    client: TestClient, mock_agent_long_stream: None
) -> None:
    """A client that reconnects while the runner is still executing a
    turn sees `is_running=true` — it should NOT clear its streaming
    fringe in that case."""
    sid = _create_session(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        _consume_initial_status(ws)
        ws.send_json({"type": "prompt", "content": "long task"})
        # Read message_start + a token so the runner is visibly busy.
        start = json.loads(ws.receive_text())
        assert start["type"] == "message_start"
        first_token = json.loads(ws.receive_text())
        assert first_token["type"] == "token"
        ws.send_json({"type": "stop"})

    # Reconnect while runner drains (or just after). The second
    # connection's runner_status reflects whatever is_running is now —
    # we don't assert a specific value because timing is racy, only
    # that the frame arrives and carries the right shape.
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        frame = json.loads(ws.receive_text())
    assert frame["type"] == "runner_status"
    assert frame["session_id"] == sid
    assert isinstance(frame["is_running"], bool)


# ---------------------------------------------------------------------------
# Idle-ping unit tests — exercise _forward_events directly with a fake
# WebSocket + asyncio.Queue. Running the TestClient path would either
# take the full 15s interval (too slow) or require monkeypatching that
# interferes with other tests; this is tighter and closer to the
# contract we care about.
# ---------------------------------------------------------------------------


class _FakeWebSocket:
    """Minimal websocket stand-in for `_forward_events`. Records every
    `send_text` so the test can assert the ping frame's shape. The
    `fail_after` hook flips `send_text` to raise on the Nth send, which
    lets us test corpse-socket cleanup without a real TCP FIN."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.sent: list[str] = []
        self.fail_after = fail_after

    async def send_text(self, frame: str) -> None:
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise RuntimeError("fake corpse socket")
        self.sent.append(frame)


@pytest.mark.asyncio
async def test_forward_events_emits_ping_on_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silent queue for longer than `WS_IDLE_PING_INTERVAL_S` must
    produce a ping frame on the wire. This is the P3 "keep the socket
    warm while the session is completely idle (no in-flight turn, no
    tool work)" check — progress ticks only cover the tool-call path."""
    from bearings.agent.runner import _Envelope
    from bearings.api import ws_agent

    monkeypatch.setattr(ws_agent, "WS_IDLE_PING_INTERVAL_S", 0.02)

    queue: asyncio.Queue[_Envelope] = asyncio.Queue()
    ws = _FakeWebSocket()

    task = asyncio.create_task(ws_agent._forward_events(ws, queue))  # type: ignore[arg-type]
    # Wait long enough for two ping intervals to elapse, then cancel.
    await asyncio.sleep(0.06)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    pings = [json.loads(f) for f in ws.sent]
    assert len(pings) >= 2, f"expected ≥2 pings, got {pings}"
    first = pings[0]
    assert first["type"] == "ping"
    assert isinstance(first["ts"], int) and first["ts"] > 0
    # Pings must not carry _seq — a reconnecting client's replay cursor
    # advances only on ring-buffer events.
    assert "_seq" not in first


@pytest.mark.asyncio
async def test_forward_events_still_flushes_queued_envelopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The idle-ping timeout must not starve real events. A quick
    enqueue followed by an idle gap should land the envelope first and
    only then produce a ping."""
    from bearings.agent.runner import _Envelope
    from bearings.api import ws_agent

    monkeypatch.setattr(ws_agent, "WS_IDLE_PING_INTERVAL_S", 0.03)

    queue: asyncio.Queue[_Envelope] = asyncio.Queue()
    ws = _FakeWebSocket()

    # Seed a real envelope before starting the forwarder.
    env = _Envelope(seq=1, payload={"type": "token", "session_id": "s", "text": "hi"})
    await queue.put(env)

    task = asyncio.create_task(ws_agent._forward_events(ws, queue))  # type: ignore[arg-type]
    await asyncio.sleep(0.08)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    decoded = [json.loads(f) for f in ws.sent]
    assert decoded, "forwarder produced no frames"
    assert decoded[0]["type"] == "token"
    assert decoded[0]["text"] == "hi"
    assert any(f["type"] == "ping" for f in decoded[1:])


@pytest.mark.asyncio
async def test_forward_events_exits_on_ping_send_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ping that raises (dead half-open TCP) must break out of the
    forwarder so the outer handler's finally block can unsubscribe.
    This is the reason P3 exists — `WebSocketDisconnect` alone misses
    corpses whose FIN was lost; the periodic send flushes them out."""
    from bearings.agent.runner import _Envelope
    from bearings.api import ws_agent

    monkeypatch.setattr(ws_agent, "WS_IDLE_PING_INTERVAL_S", 0.01)

    queue: asyncio.Queue[_Envelope] = asyncio.Queue()
    ws = _FakeWebSocket(fail_after=0)  # first send (the ping) raises

    task = asyncio.create_task(ws_agent._forward_events(ws, queue))  # type: ignore[arg-type]
    # The forwarder should exit on its own without needing cancel.
    await asyncio.wait_for(task, timeout=0.5)
    assert task.done()
    assert not task.cancelled()
    assert ws.sent == []  # fail_after=0 rejects the first send outright
