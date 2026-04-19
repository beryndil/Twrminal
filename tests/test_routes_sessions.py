from __future__ import annotations

from fastapi.testclient import TestClient


def _default_tag(client: TestClient) -> int:
    """Every session must carry ≥1 tag (v0.2.13). The tests don't
    particularly care which tag, so we seed a single "default" tag
    per client and hand out its id. Per-test client fixtures start
    with an empty DB, so the POST only creates once per test."""
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


def _create(client: TestClient, **kwargs: object) -> dict:
    tag_ids = kwargs.pop("tag_ids", None) or [_default_tag(client)]
    body = {
        "working_dir": "/tmp",
        "model": "claude-sonnet-4-6",
        "title": None,
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_post_rejects_session_without_tags(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "tag_ids": []},
    )
    assert resp.status_code == 400


def test_post_rejects_nonexistent_tag_id(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions",
        json={"working_dir": "/tmp", "model": "m", "tag_ids": [9999]},
    )
    assert resp.status_code == 400


def test_post_create_returns_session(client: TestClient) -> None:
    data = _create(client, title="hello")
    assert len(data["id"]) == 32
    assert data["working_dir"] == "/tmp"
    assert data["model"] == "claude-sonnet-4-6"
    assert data["title"] == "hello"
    assert data["max_budget_usd"] is None
    assert data["created_at"]
    assert data["updated_at"]


def test_post_create_persists_budget(client: TestClient) -> None:
    data = _create(client, title="bounded", max_budget_usd=1.25)
    assert data["max_budget_usd"] == 1.25
    roundtrip = client.get(f"/api/sessions/{data['id']}").json()
    assert roundtrip["max_budget_usd"] == 1.25


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


def test_patch_updates_title(client: TestClient) -> None:
    created = _create(client, title="before")
    before_updated = created["updated_at"]
    resp = client.patch(
        f"/api/sessions/{created['id']}",
        json={"title": "after"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "after"
    # Other fields untouched.
    assert body["working_dir"] == created["working_dir"]
    assert body["model"] == created["model"]
    assert body["max_budget_usd"] == created["max_budget_usd"]
    # updated_at bumped.
    assert body["updated_at"] != before_updated


def test_patch_can_clear_title(client: TestClient) -> None:
    created = _create(client, title="named")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"title": None},
    ).json()
    assert body["title"] is None


def test_patch_updates_budget(client: TestClient) -> None:
    created = _create(client, max_budget_usd=1.0)
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"max_budget_usd": 5.5},
    ).json()
    assert body["max_budget_usd"] == 5.5


def test_post_create_persists_description(client: TestClient) -> None:
    data = _create(client, title="noted", description="investigating the auth bug")
    assert data["description"] == "investigating the auth bug"
    roundtrip = client.get(f"/api/sessions/{data['id']}").json()
    assert roundtrip["description"] == "investigating the auth bug"


def test_patch_updates_description(client: TestClient) -> None:
    created = _create(client, description="first pass")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"description": "revised notes"},
    ).json()
    assert body["description"] == "revised notes"
    # Title untouched by description-only patch.
    assert body["title"] == created["title"]


def test_patch_can_clear_description(client: TestClient) -> None:
    created = _create(client, description="temporary")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={"description": None},
    ).json()
    assert body["description"] is None


def test_patch_empty_body_is_noop(client: TestClient) -> None:
    created = _create(client, title="stays")
    body = client.patch(
        f"/api/sessions/{created['id']}",
        json={},
    ).json()
    assert body["title"] == "stays"


def test_patch_missing_session_returns_404(client: TestClient) -> None:
    resp = client.patch(
        "/api/sessions/" + "0" * 32,
        json={"title": "whatever"},
    )
    assert resp.status_code == 404


def test_export_missing_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/export")
    assert resp.status_code == 404


def test_export_empty_session(client: TestClient) -> None:
    created = _create(client, title="exported")
    body = client.get(f"/api/sessions/{created['id']}/export").json()
    assert body["session"]["id"] == created["id"]
    assert body["session"]["title"] == "exported"
    assert body["messages"] == []
    assert body["tool_calls"] == []


def test_import_roundtrip_preserves_content(
    client: TestClient, mock_agent_tool_stream: None
) -> None:
    import time

    # Seed a session with a full turn + a tool call.
    src = _create(client, title="source")
    with client.websocket_connect(f"/ws/sessions/{src['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "read hosts"})
        for _ in range(4):
            ws.receive_text()
        for _ in range(50):
            body = client.get(f"/api/sessions/{src['id']}/export").json()
            if body["tool_calls"] and body["tool_calls"][0]["message_id"]:
                break
            time.sleep(0.02)

    export = client.get(f"/api/sessions/{src['id']}/export").json()

    # Round-trip.
    resp = client.post("/api/sessions/import", json=export)
    assert resp.status_code == 200
    imported = resp.json()
    assert imported["id"] != src["id"]
    assert imported["title"] == "source"
    assert imported["total_cost_usd"] == 0.0  # reset on import
    assert imported["message_count"] == 2

    # Messages and tool calls carried over with remapped ids.
    messages = client.get(f"/api/sessions/{imported['id']}/messages").json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "read hosts"

    tool_calls = client.get(f"/api/sessions/{imported['id']}/tool_calls").json()
    assert len(tool_calls) == 1
    assert tool_calls[0]["name"] == "Read"
    # message_id was remapped to the newly-inserted assistant message.
    assert tool_calls[0]["message_id"] == messages[1]["id"]


def test_import_rejects_missing_session_key(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions/import",
        json={"messages": [], "tool_calls": []},
    )
    assert resp.status_code == 400


def test_export_includes_messages_and_tool_calls(
    client: TestClient, mock_agent_tool_stream: None
) -> None:
    import time

    created = _create(client, title="with-activity")
    with client.websocket_connect(f"/ws/sessions/{created['id']}") as ws:
        ws.send_json({"type": "prompt", "content": "read it"})
        for _ in range(4):
            ws.receive_text()
        # Wait for the WS handler to finish persisting post-send writes
        # before the context cancels the server task.
        for _ in range(50):
            body = client.get(f"/api/sessions/{created['id']}/export").json()
            if body["tool_calls"] and body["tool_calls"][0]["message_id"]:
                break
            time.sleep(0.02)

    body = client.get(f"/api/sessions/{created['id']}/export").json()
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant"]
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["name"] == "Read"


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
