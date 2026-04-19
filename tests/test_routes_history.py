from __future__ import annotations

from fastapi.testclient import TestClient


def _create(client: TestClient, title: str = "t") -> str:
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "title": title},
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def test_export_returns_all_sections(client: TestClient) -> None:
    sid = _create(client, "exported")
    resp = client.get("/api/history/export")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"sessions", "messages", "tool_calls"}
    assert any(s["id"] == sid for s in data["sessions"])
    assert data["messages"] == []
    assert data["tool_calls"] == []


def test_export_includes_messages(client: TestClient, mock_agent_stream: None) -> None:
    sid = _create(client)
    with client.websocket_connect(f"/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "prompt", "content": "hi"})
        for _ in range(4):
            ws.receive_text()

    data = client.get("/api/history/export").json()
    roles = [m["role"] for m in data["messages"] if m["session_id"] == sid]
    assert roles == ["user", "assistant"]


def test_daily_filters_by_date(client: TestClient) -> None:
    sid = _create(client, "today")

    # Find the day we actually created on (test-server clock).
    today = client.get(f"/api/sessions/{sid}").json()["created_at"][:10]

    resp = client.get(f"/api/history/daily/{today}")
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["id"] == sid for s in data["sessions"])

    # A day long past — should return empty sections.
    empty = client.get("/api/history/daily/2000-01-01").json()
    assert empty["sessions"] == []
    assert empty["messages"] == []
    assert empty["tool_calls"] == []


def test_daily_rejects_bad_date(client: TestClient) -> None:
    resp = client.get("/api/history/daily/not-a-date")
    assert resp.status_code == 400
    resp = client.get("/api/history/daily/2026-13-40")
    assert resp.status_code == 400
