from __future__ import annotations

from fastapi.testclient import TestClient


def _create(client: TestClient, **kwargs: object) -> dict:
    body = {"working_dir": "/tmp", "model": "claude-sonnet-4-6", "title": None, **kwargs}
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_post_create_returns_session(client: TestClient) -> None:
    data = _create(client, title="hello")
    assert len(data["id"]) == 32
    assert data["working_dir"] == "/tmp"
    assert data["model"] == "claude-sonnet-4-6"
    assert data["title"] == "hello"
    assert data["created_at"]
    assert data["updated_at"]


def test_get_list_includes_created(client: TestClient) -> None:
    created = _create(client)
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert created["id"] in ids


def test_get_session_round_trip(client: TestClient) -> None:
    created = _create(client, title="round-trip")
    resp = client.get(f"/api/sessions/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == created


def test_get_missing_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32)
    assert resp.status_code == 404


def test_delete_then_get_404(client: TestClient) -> None:
    created = _create(client)
    resp = client.delete(f"/api/sessions/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True}
    resp = client.get(f"/api/sessions/{created['id']}")
    assert resp.status_code == 404


def test_delete_missing_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/sessions/" + "0" * 32)
    assert resp.status_code == 404


def test_get_messages_empty_for_new_session(client: TestClient) -> None:
    created = _create(client)
    resp = client.get(f"/api/sessions/{created['id']}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_messages_missing_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/messages")
    assert resp.status_code == 404


def test_get_tool_calls_empty_for_new_session(client: TestClient) -> None:
    created = _create(client)
    resp = client.get(f"/api/sessions/{created['id']}/tool_calls")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_tool_calls_missing_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/tool_calls")
    assert resp.status_code == 404


def test_get_tool_calls_returns_persisted_rows(
    client: TestClient, mock_agent_tool_stream: None
) -> None:
    created = _create(client, title="tc")
    with client.websocket_connect(f"/ws/sessions/{created['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        for _ in range(4):
            ws.receive_text()

    rows = client.get(f"/api/sessions/{created['id']}/tool_calls").json()
    assert len(rows) == 1
    call = rows[0]
    assert call["id"] == "tool-1"
    assert call["name"] == "Read"
    assert call["input"] == '{"path": "/etc/hosts"}'
    assert call["output"] == "127.0.0.1 localhost"
    assert call["error"] is None
    assert call["started_at"]
    assert call["finished_at"]
