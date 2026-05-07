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


# ---------------------------------------------------------------------------
# POST /api/templates/{id}/instantiate  (gap-cycle-13-006)
# ---------------------------------------------------------------------------


async def test_instantiate_template_copies_session_instructions(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """session_instructions on the new session == template.system_prompt_baseline."""
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post(
            "/api/templates",
            json={
                "name": "Baseline Template",
                "model": "sonnet",
                "system_prompt_baseline": "You are a helpful assistant.",
                "working_dir_default": "/tmp",
            },
        )
        assert created.status_code == 201
        template_id = created.json()["id"]

        response = client.post(f"/api/templates/{template_id}/instantiate", json={})
    assert response.status_code == 201
    body = response.json()
    assert body["session_instructions"] == "You are a helpful assistant."
    assert body["model"] == "sonnet"
    assert body["title"] == "Baseline Template"
    assert body["working_dir"] == "/tmp"


async def test_instantiate_template_copies_description(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """description is copied from the template to the new session."""
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post(
            "/api/templates",
            json={
                "name": "Described Template",
                "model": "haiku",
                "description": "Template for testing.",
                "working_dir_default": "/tmp",
            },
        )
        template_id = created.json()["id"]
        response = client.post(f"/api/templates/{template_id}/instantiate", json={})
    assert response.status_code == 201
    assert response.json()["description"] == "Template for testing."


async def test_instantiate_template_attaches_tags(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Tags named in the template are resolved and attached to the new session."""
    app, _conn = app_and_db
    with TestClient(app) as client:
        # Create a tag first.
        tag_resp = client.post(
            "/api/tags",
            json={"name": "bearings/test", "color": "#aabbcc", "class_": "general"},
        )
        assert tag_resp.status_code == 201
        tag_id = tag_resp.json()["id"]

        created = client.post(
            "/api/templates",
            json={
                "name": "Tagged Template",
                "model": "sonnet",
                "working_dir_default": "/tmp",
                "tag_names": ["bearings/test"],
            },
        )
        template_id = created.json()["id"]

        response = client.post(f"/api/templates/{template_id}/instantiate", json={})
    assert response.status_code == 201
    session_id = response.json()["id"]

    # Verify the tag is attached by fetching the session's tags.
    with TestClient(app) as client:
        tags_resp = client.get(f"/api/sessions/{session_id}/tags")
    assert tags_resp.status_code == 200
    attached_ids = [t["id"] for t in tags_resp.json()]
    assert tag_id in attached_ids


async def test_instantiate_template_404_on_unknown_id(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """404 when the template id does not exist."""
    app, _conn = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/templates/9999/instantiate", json={})
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]


async def test_instantiate_template_title_override(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Caller can override the title; other fields still inherit from template."""
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post(
            "/api/templates",
            json={
                "name": "Base Name",
                "model": "haiku",
                "working_dir_default": "/tmp",
            },
        )
        template_id = created.json()["id"]
        response = client.post(
            f"/api/templates/{template_id}/instantiate",
            json={"title": "Custom Title"},
        )
    assert response.status_code == 201
    assert response.json()["title"] == "Custom Title"
    assert response.json()["model"] == "haiku"


async def test_instantiate_template_422_no_working_dir(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """422 when neither the template nor the override provides a working_dir."""
    app, _conn = app_and_db
    with TestClient(app) as client:
        created = client.post(
            "/api/templates",
            json={"name": "No Dir Template", "model": "haiku"},
        )
        template_id = created.json()["id"]
        response = client.post(f"/api/templates/{template_id}/instantiate", json={})
    assert response.status_code == 422
