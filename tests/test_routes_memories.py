"""Integration tests for ``bearings.web.routes.memories`` via FastAPI."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "routes_memories.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def _make_tag(client: TestClient, name: str = "t") -> int:
    response = client.post("/api/tags", json={"name": name})
    assert response.status_code == 201
    return int(response.json()["id"])


def test_post_memory_creates_under_tag(app_client: TestClient) -> None:
    tag_id = _make_tag(app_client)
    response = app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "anchor", "body": "cite arch", "enabled": True},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "anchor"
    assert body["tag_id"] == tag_id
    assert body["enabled"] is True


def test_post_memory_404_on_unknown_tag(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/tags/99999/memories",
        json={"title": "t", "body": "b"},
    )
    assert response.status_code == 404


def test_post_memory_422_on_empty_body(app_client: TestClient) -> None:
    tag_id = _make_tag(app_client)
    response = app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "t", "body": ""},
    )
    assert response.status_code == 422


def test_list_memories_for_tag(app_client: TestClient) -> None:
    tag_id = _make_tag(app_client)
    for i in range(3):
        app_client.post(
            f"/api/tags/{tag_id}/memories",
            json={"title": f"m{i}", "body": "b"},
        )
    response = app_client.get(f"/api/tags/{tag_id}/memories")
    assert response.status_code == 200
    assert [m["title"] for m in response.json()] == ["m0", "m1", "m2"]


def test_list_memories_only_enabled_filter(app_client: TestClient) -> None:
    tag_id = _make_tag(app_client)
    app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "on", "body": "b", "enabled": True},
    )
    app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "off", "body": "b", "enabled": False},
    )
    response = app_client.get(f"/api/tags/{tag_id}/memories", params={"only_enabled": "true"})
    assert response.status_code == 200
    titles = [m["title"] for m in response.json()]
    assert titles == ["on"]


def test_get_memory_by_id(app_client: TestClient) -> None:
    tag_id = _make_tag(app_client)
    created = app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "x", "body": "y"},
    ).json()
    response = app_client.get(f"/api/memories/{created['id']}")
    assert response.status_code == 200
    assert response.json()["title"] == "x"


def test_get_memory_404(app_client: TestClient) -> None:
    response = app_client.get("/api/memories/99999")
    assert response.status_code == 404


def test_patch_memory_replaces(app_client: TestClient) -> None:
    tag_id = _make_tag(app_client)
    created = app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "orig", "body": "orig"},
    ).json()
    response = app_client.patch(
        f"/api/memories/{created['id']}",
        json={"title": "new", "body": "new", "enabled": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "new"
    assert body["enabled"] is False


def test_patch_memory_404(app_client: TestClient) -> None:
    response = app_client.patch(
        "/api/memories/99999",
        json={"title": "x", "body": "y", "enabled": True},
    )
    assert response.status_code == 404


def test_delete_memory(app_client: TestClient) -> None:
    tag_id = _make_tag(app_client)
    created = app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "rm", "body": "rm"},
    ).json()
    response = app_client.delete(f"/api/memories/{created['id']}")
    assert response.status_code == 204
    response2 = app_client.delete(f"/api/memories/{created['id']}")
    assert response2.status_code == 404


def test_tag_delete_cascades_to_memories_via_api(
    app_client: TestClient,
) -> None:
    """Behaviour-doc-aligned test: delete a tag → its memories are gone."""
    tag_id = _make_tag(app_client)
    created = app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "bye", "body": "bye"},
    ).json()
    app_client.delete(f"/api/tags/{tag_id}")
    response = app_client.get(f"/api/memories/{created['id']}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Global flat-list endpoint — GET /api/memories (gap-cycle-13-007)
# ---------------------------------------------------------------------------


def test_list_all_memories_empty_on_fresh_db(app_client: TestClient) -> None:
    """``GET /api/memories`` returns [] when no memories exist."""
    response = app_client.get("/api/memories")
    assert response.status_code == 200
    assert response.json() == []


def test_list_all_memories_returns_cross_tag_rows(app_client: TestClient) -> None:
    """Rows span multiple tags; each row carries the tag context."""
    tag_a = _make_tag(app_client, "alpha")
    tag_b = _make_tag(app_client, "beta")
    app_client.post(f"/api/tags/{tag_a}/memories", json={"title": "A-mem", "body": "a body"})
    app_client.post(f"/api/tags/{tag_b}/memories", json={"title": "B-mem", "body": "b body"})

    response = app_client.get("/api/memories")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    # Both tag fields are present.
    tag_names = {r["tag_name"] for r in rows}
    assert tag_names == {"alpha", "beta"}
    # Each row has the mandatory shape.
    for row in rows:
        for key in (
            "tag_id",
            "tag_name",
            "tag_color",
            "memory_id",
            "memory_title",
            "memory_body_preview",
            "enabled",
            "updated_at",
        ):
            assert key in row, f"missing key {key!r}"


def test_list_all_memories_sorted_by_tag_name_then_title(app_client: TestClient) -> None:
    """Response is sorted by (tag_name ASC, memory_title ASC)."""
    tag_z = _make_tag(app_client, "zzz")
    tag_a = _make_tag(app_client, "aaa")
    # Insert in reverse order to confirm sort is applied.
    app_client.post(f"/api/tags/{tag_z}/memories", json={"title": "z-mem", "body": "b"})
    app_client.post(f"/api/tags/{tag_a}/memories", json={"title": "a-m2", "body": "b"})
    app_client.post(f"/api/tags/{tag_a}/memories", json={"title": "a-m1", "body": "b"})

    rows = app_client.get("/api/memories").json()
    assert [r["tag_name"] for r in rows] == ["aaa", "aaa", "zzz"]
    assert [r["memory_title"] for r in rows] == ["a-m1", "a-m2", "z-mem"]


def test_list_all_memories_only_enabled_filter(app_client: TestClient) -> None:
    """``?only_enabled=true`` excludes disabled memories."""
    tag_id = _make_tag(app_client, "filter-tag")
    app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "on", "body": "b", "enabled": True},
    )
    app_client.post(
        f"/api/tags/{tag_id}/memories",
        json={"title": "off", "body": "b", "enabled": False},
    )

    all_rows = app_client.get("/api/memories").json()
    assert len(all_rows) == 2

    enabled_rows = app_client.get("/api/memories", params={"only_enabled": "true"}).json()
    assert len(enabled_rows) == 1
    assert enabled_rows[0]["memory_title"] == "on"
    assert enabled_rows[0]["enabled"] is True


def test_list_all_memories_body_preview_truncated(app_client: TestClient) -> None:
    """``memory_body_preview`` is truncated to at most 200 chars."""
    from bearings.config.constants import MEMORY_BODY_PREVIEW_MAX_LENGTH

    tag_id = _make_tag(app_client, "trunc-tag")
    long_body = "x" * (MEMORY_BODY_PREVIEW_MAX_LENGTH + 100)
    app_client.post(f"/api/tags/{tag_id}/memories", json={"title": "big", "body": long_body})

    rows = app_client.get("/api/memories").json()
    assert len(rows) == 1
    assert len(rows[0]["memory_body_preview"]) == MEMORY_BODY_PREVIEW_MAX_LENGTH
