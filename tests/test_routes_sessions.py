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
