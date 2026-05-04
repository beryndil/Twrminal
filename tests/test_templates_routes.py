"""Integration tests for the templates REST endpoints (G7).

Covers the full CRUD surface:

* ``POST /api/templates`` — create; 409 on duplicate name; 422 on bad model.
* ``GET /api/templates`` — list all, alphabetically.
* ``GET /api/templates/{id}`` — single fetch; 404 on unknown.
* ``PATCH /api/templates/{id}`` — partial update; 404 on unknown; 409 on
  name collision with a different row.
* ``DELETE /api/templates/{id}`` — delete; 404 when already gone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.db.connection import load_schema
from bearings.web.app import create_app


@pytest.fixture
async def app_and_db(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    db_path = tmp_path / "templates_routes.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# POST /api/templates
# ---------------------------------------------------------------------------


async def test_create_template_returns_201(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        response = client.post(
            "/api/templates",
            json={
                "name": "Workhorse",
                "model": "sonnet",
                "description": "Default Sonnet + Opus advisor",
                "advisor_model": "opus",
                "advisor_max_uses": 5,
                "effort_level": "auto",
                "permission_profile": "standard",
                "tag_names": ["bearings/exec"],
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Workhorse"
    assert body["model"] == "sonnet"
    assert body["advisor_model"] == "opus"
    assert body["tag_names"] == ["bearings/exec"]
    assert isinstance(body["id"], int)
    assert body["id"] > 0
    assert isinstance(body["created_at"], str) and len(body["created_at"]) > 0


async def test_create_template_409_on_duplicate_name(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    payload = {"name": "Dupe", "model": "sonnet"}
    with TestClient(app) as client:
        r1 = client.post("/api/templates", json=payload)
        assert r1.status_code == 201
        r2 = client.post("/api/templates", json=payload)
    assert r2.status_code == 409
    assert "already exists" in r2.json()["detail"]


async def test_create_template_422_on_unknown_model(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/templates", json={"name": "Bad", "model": "gpt-4"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/templates
# ---------------------------------------------------------------------------


async def test_list_templates_returns_empty_initially(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        response = client.get("/api/templates")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_templates_ordered_alphabetically(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        client.post("/api/templates", json={"name": "Zebra", "model": "sonnet"})
        client.post("/api/templates", json={"name": "Alpha", "model": "haiku"})
        client.post("/api/templates", json={"name": "Middle", "model": "opus"})
        response = client.get("/api/templates")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()]
    assert names == ["Alpha", "Middle", "Zebra"]


# ---------------------------------------------------------------------------
# GET /api/templates/{id}
# ---------------------------------------------------------------------------


async def test_get_template_returns_row(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post("/api/templates", json={"name": "Fetch me", "model": "haiku"})
        template_id = created.json()["id"]
        response = client.get(f"/api/templates/{template_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Fetch me"


async def test_get_template_404_on_unknown(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        response = client.get("/api/templates/9999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/templates/{id}
# ---------------------------------------------------------------------------


async def test_patch_template_updates_name(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post("/api/templates", json={"name": "Old Name", "model": "sonnet"})
        template_id = created.json()["id"]
        response = client.patch(f"/api/templates/{template_id}", json={"name": "New Name"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Name"
    # Non-patched fields are preserved.
    assert body["model"] == "sonnet"


async def test_patch_template_preserves_unpatched_fields(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post(
            "/api/templates",
            json={
                "name": "Stable",
                "model": "opus",
                "advisor_model": None,
                "advisor_max_uses": 0,
                "effort_level": "xhigh",
                "permission_profile": "restricted",
            },
        )
        template_id = created.json()["id"]
        # Only patching description — all routing fields must survive.
        response = client.patch(
            f"/api/templates/{template_id}",
            json={"description": "added later"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "opus"
    assert body["effort_level"] == "xhigh"
    assert body["permission_profile"] == "restricted"
    assert body["description"] == "added later"


async def test_patch_template_404_on_unknown(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        response = client.patch("/api/templates/9999", json={"name": "Ghost"})
    assert response.status_code == 404


async def test_patch_template_409_on_name_collision(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        client.post("/api/templates", json={"name": "Taken", "model": "sonnet"})
        r2 = client.post("/api/templates", json={"name": "Target", "model": "haiku"})
        target_id = r2.json()["id"]
        response = client.patch(f"/api/templates/{target_id}", json={"name": "Taken"})
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /api/templates/{id}
# ---------------------------------------------------------------------------


async def test_delete_template_returns_204(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post("/api/templates", json={"name": "Ephemeral", "model": "haiku"})
        template_id = created.json()["id"]
        delete_response = client.delete(f"/api/templates/{template_id}")
        assert delete_response.status_code == 204
        get_response = client.get(f"/api/templates/{template_id}")
    assert get_response.status_code == 404


async def test_delete_template_404_when_already_gone(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_db
    with TestClient(app) as client:
        response = client.delete("/api/templates/9999")
    assert response.status_code == 404
