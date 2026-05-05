"""Integration tests for ``bearings.web.routes.tags`` via FastAPI.

Boots the real ASGI app via :class:`fastapi.testclient.TestClient` with
a freshly-bootstrapped DB on ``app.state.db_connection``; exercises
the full HTTP surface — CRUD, group filter, per-session attach/detach,
and the FK / unique-constraint error paths.
"""

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
    """Boot the app with a fresh DB connection on app.state."""
    db_path = tmp_path / "routes_tags.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        # Seed one session so attach/detach FK paths are reachable.
        loop.run_until_complete(_seed_session(conn))
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


async def _seed_session(conn: aiosqlite.Connection) -> None:
    timestamp = "2026-04-28T12:00:00+00:00"
    await conn.execute(
        "INSERT INTO sessions (id, kind, title, working_dir, model, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("sess1", "chat", "Alpha", "/tmp/alpha", "sonnet", timestamp, timestamp),
    )
    await conn.commit()


def test_post_tag_creates_and_returns(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/tags",
        json={
            "name": "bearings/architect",
            "color": "#ffaa00",
            "default_model": "opus",
            "working_dir": "/home/dave/proj",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "bearings/architect"
    assert body["group"] == "bearings"
    assert body["default_model"] == "opus"


def test_post_tag_409_on_duplicate_name(app_client: TestClient) -> None:
    app_client.post("/api/tags", json={"name": "dup"})
    response = app_client.post("/api/tags", json={"name": "dup"})
    assert response.status_code == 409


def test_post_tag_422_on_bad_default_model(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/tags",
        json={"name": "x", "default_model": "not-a-model"},
    )
    assert response.status_code == 422


def test_get_tags_returns_alphabetical(app_client: TestClient) -> None:
    for n in ("z-tag", "a-tag", "m-tag"):
        app_client.post("/api/tags", json={"name": n})
    response = app_client.get("/api/tags")
    assert response.status_code == 200
    assert [t["name"] for t in response.json()] == ["a-tag", "m-tag", "z-tag"]


def test_get_tags_filters_by_group(app_client: TestClient) -> None:
    for n in ("bearings/a", "bearings/b", "general"):
        app_client.post("/api/tags", json={"name": n})
    response = app_client.get("/api/tags", params={"group": "bearings"})
    assert response.status_code == 200
    assert [t["name"] for t in response.json()] == ["bearings/a", "bearings/b"]


def test_get_tag_groups(app_client: TestClient) -> None:
    for n in ("bearings/a", "research/b", "general"):
        app_client.post("/api/tags", json={"name": n})
    response = app_client.get("/api/tag-groups")
    assert response.status_code == 200
    assert response.json() == ["bearings", "research"]


def test_get_tag_404_on_unknown_id(app_client: TestClient) -> None:
    response = app_client.get("/api/tags/99999")
    assert response.status_code == 404


def test_patch_tag_replaces_fields(app_client: TestClient) -> None:
    created = app_client.post("/api/tags", json={"name": "orig"}).json()
    response = app_client.patch(
        f"/api/tags/{created['id']}",
        json={
            "name": "renamed",
            "color": "#000000",
            "default_model": "haiku",
            "working_dir": "/x",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "renamed"
    assert body["default_model"] == "haiku"


def test_patch_tag_404_on_unknown_id(app_client: TestClient) -> None:
    response = app_client.patch("/api/tags/99999", json={"name": "x"})
    assert response.status_code == 404


def test_delete_tag_204(app_client: TestClient) -> None:
    created = app_client.post("/api/tags", json={"name": "to-delete"}).json()
    response = app_client.delete(f"/api/tags/{created['id']}")
    assert response.status_code == 204
    # Idempotency: second delete yields 404.
    response2 = app_client.delete(f"/api/tags/{created['id']}")
    assert response2.status_code == 404


def test_attach_and_detach_tag(app_client: TestClient) -> None:
    created = app_client.post("/api/tags", json={"name": "attach-me"}).json()
    tag_id = created["id"]
    # Initially no tags on session.
    assert app_client.get("/api/sessions/sess1/tags").json() == []
    # Attach.
    response = app_client.put(f"/api/sessions/sess1/tags/{tag_id}")
    assert response.status_code == 200
    rows = app_client.get("/api/sessions/sess1/tags").json()
    assert [t["id"] for t in rows] == [tag_id]
    # Idempotent re-attach.
    response2 = app_client.put(f"/api/sessions/sess1/tags/{tag_id}")
    assert response2.status_code == 200
    # Detach.
    response3 = app_client.delete(f"/api/sessions/sess1/tags/{tag_id}")
    assert response3.status_code == 204
    assert app_client.get("/api/sessions/sess1/tags").json() == []
    # Detach again → 404.
    response4 = app_client.delete(f"/api/sessions/sess1/tags/{tag_id}")
    assert response4.status_code == 404


def test_attach_unknown_session_or_tag_404(app_client: TestClient) -> None:
    created = app_client.post("/api/tags", json={"name": "ok"}).json()
    response = app_client.put(f"/api/sessions/missing/tags/{created['id']}")
    assert response.status_code == 404
    response2 = app_client.put("/api/sessions/sess1/tags/99999")
    assert response2.status_code == 404


# ---------------------------------------------------------------------------
# class_ + sort_order — tag-class feature
# ---------------------------------------------------------------------------


def test_post_tag_with_class_and_sort_order(app_client: TestClient) -> None:
    """Wire shape carries ``class_`` + ``sort_order`` round-trip."""
    response = app_client.post(
        "/api/tags",
        json={
            "name": "bearings",
            "class_": "project",
            "default_model": "opus",
            "working_dir": "/home/dave/proj",
            "sort_order": 3,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["class_"] == "project"
    assert body["sort_order"] == 3


def test_post_tag_defaults_to_general_class(app_client: TestClient) -> None:
    """No ``class_`` in payload → ``general`` (back-compat with old clients)."""
    response = app_client.post("/api/tags", json={"name": "freeform"})
    assert response.status_code == 201
    assert response.json()["class_"] == "general"
    assert response.json()["sort_order"] == 0


def test_post_severity_with_default_model_returns_422(app_client: TestClient) -> None:
    """Severity-class tags reject ``default_model`` at the wire boundary."""
    response = app_client.post(
        "/api/tags",
        json={
            "name": "urgent",
            "class_": "severity",
            "default_model": "opus",
        },
    )
    assert response.status_code == 422
    assert "default_model" in response.json()["detail"]


def test_post_unknown_class_returns_422(app_client: TestClient) -> None:
    """Pydantic Literal rejects classes outside the alphabet."""
    response = app_client.post(
        "/api/tags",
        json={"name": "x", "class_": "milestone"},
    )
    assert response.status_code == 422


def test_get_tags_filters_by_class(app_client: TestClient) -> None:
    """``?class_=project`` returns only project-class tags."""
    app_client.post("/api/tags", json={"name": "freeform"})
    app_client.post(
        "/api/tags",
        json={"name": "bearings", "class_": "project"},
    )
    app_client.post(
        "/api/tags",
        json={"name": "archon", "class_": "project"},
    )
    response = app_client.get("/api/tags", params={"class_": "project"})
    assert response.status_code == 200
    body = response.json()
    assert {t["name"] for t in body} == {"bearings", "archon"}
    assert all(t["class_"] == "project" for t in body)


def test_get_tags_class_filter_rejects_unknown(app_client: TestClient) -> None:
    response = app_client.get("/api/tags", params={"class_": "milestone"})
    assert response.status_code == 422


def test_patch_tag_can_change_class(app_client: TestClient) -> None:
    """PATCH threads ``class_`` and ``sort_order``."""
    created = app_client.post("/api/tags", json={"name": "bearings"}).json()
    response = app_client.patch(
        f"/api/tags/{created['id']}",
        json={
            "name": "bearings",
            "color": None,
            "default_model": "opus",
            "working_dir": "/home/dave/proj",
            "class_": "project",
            "sort_order": 5,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["class_"] == "project"
    assert body["sort_order"] == 5


def test_put_sort_order_resequences(app_client: TestClient) -> None:
    """Drag-reorder path: PUT /api/tags/sort-order assigns ``sort_order = index``."""
    a = app_client.post(
        "/api/tags", json={"name": "a", "class_": "project", "sort_order": 0}
    ).json()
    b = app_client.post(
        "/api/tags", json={"name": "b", "class_": "project", "sort_order": 1}
    ).json()
    c = app_client.post(
        "/api/tags", json={"name": "c", "class_": "project", "sort_order": 2}
    ).json()

    response = app_client.put(
        "/api/tags/sort-order",
        json={"class_": "project", "ordered_ids": [c["id"], a["id"], b["id"]]},
    )
    assert response.status_code == 204

    listed = app_client.get("/api/tags", params={"class_": "project"}).json()
    assert [t["name"] for t in listed] == ["c", "a", "b"]


def test_put_sort_order_rejects_cross_class(app_client: TestClient) -> None:
    """A general tag id cannot appear in a project re-sequence call."""
    proj = app_client.post("/api/tags", json={"name": "p", "class_": "project"}).json()
    gen = app_client.post("/api/tags", json={"name": "g"}).json()

    response = app_client.put(
        "/api/tags/sort-order",
        json={"class_": "project", "ordered_ids": [proj["id"], gen["id"]]},
    )
    assert response.status_code == 422


def test_put_sort_order_rejects_missing_id(app_client: TestClient) -> None:
    response = app_client.put(
        "/api/tags/sort-order",
        json={"class_": "project", "ordered_ids": [99_999]},
    )
    assert response.status_code == 422


def test_put_sort_order_empty_ok(app_client: TestClient) -> None:
    """Empty list is a no-op (still 204)."""
    response = app_client.put(
        "/api/tags/sort-order",
        json={"class_": "project", "ordered_ids": []},
    )
    assert response.status_code == 204


def test_put_sort_order_unknown_class_422(app_client: TestClient) -> None:
    response = app_client.put(
        "/api/tags/sort-order",
        json={"class_": "milestone", "ordered_ids": []},
    )
    assert response.status_code == 422


def test_get_tag_groups_still_works_for_back_compat(app_client: TestClient) -> None:
    """Deprecated endpoint continues to function for v0.18.x frontend builds."""
    for n in ("bearings/a", "bearings/b", "research/c"):
        app_client.post("/api/tags", json={"name": n})
    response = app_client.get("/api/tag-groups")
    assert response.status_code == 200
    assert response.json() == ["bearings", "research"]
