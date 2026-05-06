"""Happy-path coverage for /api/sessions CRUD."""

from typing import Any

from httpx import AsyncClient


def _payload(**overrides: object) -> dict[str, Any]:
    """Return a minimal valid create-session body, with optional overrides."""
    body: dict[str, Any] = {
        "working_dir": "/home/user/project",
        "model": "sonnet",
        "title": "First chat",
        "kind": "chat",
    }
    body.update(overrides)
    return body


async def _create_one(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    """Helper: create a session and return the parsed response body."""
    response = await client.post("/api/sessions", json=_payload(), headers=headers)
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


async def test_create_returns_persisted_record(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """POST returns 201 + the row with server-generated id and timestamps."""
    created = await _create_one(client, auth_headers)
    assert len(created["id"]) == 32  # uuid4 hex
    assert created["title"] == "First chat"
    assert created["description"] == ""
    assert created["max_budget"] is None
    assert created["created_at"] == created["updated_at"]


async def test_get_after_create_returns_same_record(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """GET /{id} returns exactly what POST returned."""
    created = await _create_one(client, auth_headers)
    fetched = await client.get(f"/api/sessions/{created['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json() == created


async def test_list_then_patch_then_delete(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """List shows the row, PATCH updates it, DELETE removes it (404 after)."""
    created = await _create_one(client, auth_headers)
    session_id = created["id"]

    listed = await client.get("/api/sessions", headers=auth_headers)
    assert listed.status_code == 200
    page = listed.json()
    assert page == {"items": [created], "total": 1, "limit": 50, "offset": 0}

    patched = await client.patch(
        f"/api/sessions/{session_id}",
        json={"title": "Renamed", "max_budget": 5.0},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["title"] == "Renamed"
    assert body["max_budget"] == 5.0
    assert body["updated_at"] >= created["updated_at"]

    deleted = await client.delete(f"/api/sessions/{session_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert deleted.content == b""

    gone = await client.get(f"/api/sessions/{session_id}", headers=auth_headers)
    assert gone.status_code == 404


async def test_list_pagination_and_kind_filter(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Listing supports limit/offset and a ``kind`` filter."""
    # Two chat sessions and two executor sessions.
    for kind in ("chat", "chat", "executor", "executor"):
        await client.post(
            "/api/sessions",
            json=_payload(kind=kind, title=f"{kind} session"),
            headers=auth_headers,
        )

    chat_only = await client.get("/api/sessions?kind=chat", headers=auth_headers)
    assert chat_only.status_code == 200
    assert chat_only.json()["total"] == 2
    assert all(item["kind"] == "chat" for item in chat_only.json()["items"])

    page1 = await client.get("/api/sessions?limit=2&offset=0", headers=auth_headers)
    page2 = await client.get("/api/sessions?limit=2&offset=2", headers=auth_headers)
    assert page1.status_code == 200
    assert page2.status_code == 200
    assert page1.json()["total"] == 4
    assert len(page1.json()["items"]) == 2
    assert len(page2.json()["items"]) == 2
    # Page contents must be disjoint when concatenated.
    ids = {row["id"] for row in page1.json()["items"]}
    ids.update(row["id"] for row in page2.json()["items"])
    assert len(ids) == 4


async def test_patch_with_no_fields_only_touches_updated_at(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """An empty PATCH body refreshes ``updated_at`` and nothing else."""
    create = await client.post("/api/sessions", json=_payload(), headers=auth_headers)
    session_id = create.json()["id"]
    original_updated = create.json()["updated_at"]

    patched = await client.patch(
        f"/api/sessions/{session_id}",
        json={},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["title"] == create.json()["title"]
    assert body["updated_at"] >= original_updated
