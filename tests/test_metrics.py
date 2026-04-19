from __future__ import annotations

import json

from fastapi.testclient import TestClient

from twrminal import metrics
from twrminal.config import Settings


def _default_tag_id(client: TestClient) -> int:
    existing = client.get("/api/tags").json()
    if existing:
        return int(existing[0]["id"])
    return int(client.post("/api/tags", json={"name": "default"}).json()["id"])


def test_metrics_endpoint_emits_registry(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "twrminal_sessions_created_total" in resp.text


def test_sessions_created_counter_increments(client: TestClient) -> None:
    tag_id = _default_tag_id(client)
    before = metrics.sessions_created._value.get()
    client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "title": None, "tag_ids": [tag_id]},
    )
    after = metrics.sessions_created._value.get()
    assert after == before + 1


def test_ws_counters_update(client: TestClient, mock_agent_stream: None) -> None:
    tag_id = _default_tag_id(client)
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "title": None, "tag_ids": [tag_id]},
    )
    sid = resp.json()["id"]

    active_before = metrics.ws_active_connections._value.get()
    user_before = metrics.messages_persisted.labels(role="user")._value.get()
    assistant_before = metrics.messages_persisted.labels(role="assistant")._value.get()

    import time

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "hi"})
        frames = [json.loads(ws.receive_text()) for _ in range(4)]
        # Server has clearly advanced past the inc() once we've read frames.
        active_during = metrics.ws_active_connections._value.get()
        assert active_during == active_before + 1

        # MessageComplete side-effects (assistant insert + inc) happen
        # AFTER the last send — poll inside the context so the server
        # task isn't cancelled by TestClient before the inc runs.
        for _ in range(50):
            if (
                metrics.messages_persisted.labels(role="assistant")._value.get()
                >= assistant_before + 1
            ):
                break
            time.sleep(0.02)

    assert [f["type"] for f in frames] == [
        "message_start",
        "token",
        "token",
        "message_complete",
    ]

    assert metrics.messages_persisted.labels(role="user")._value.get() == user_before + 1
    assert metrics.messages_persisted.labels(role="assistant")._value.get() == assistant_before + 1
    token_sent = metrics.ws_events_sent.labels(type="token")._value.get()
    assert token_sent >= 2
    # Connection closed cleanly — gauge returned to baseline.
    assert metrics.ws_active_connections._value.get() == active_before


def test_tool_call_counters_label_success(
    client: TestClient, mock_agent_tool_stream: None, tmp_settings: Settings
) -> None:
    tag_id = _default_tag_id(client)
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "title": None, "tag_ids": [tag_id]},
    )
    sid = resp.json()["id"]

    started_before = metrics.tool_calls_started._value.get()
    ok_before = metrics.tool_calls_finished.labels(ok="true")._value.get()

    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        for _ in range(4):
            ws.receive_text()

    assert metrics.tool_calls_started._value.get() == started_before + 1
    assert metrics.tool_calls_finished.labels(ok="true")._value.get() == ok_before + 1
