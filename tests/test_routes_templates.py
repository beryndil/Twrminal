"""HTTP surface for Phase 9b.2 of docs/context-menu-plan.md.

Covers the four template endpoints:

  POST   /api/templates                    — create
  GET    /api/templates                    — list newest-first
  DELETE /api/templates/{id}               — remove
  POST   /api/sessions/from_template/{id}  — instantiate

Instantiate tests walk through the override hierarchy (request > saved
template > app default) and confirm the "stale tag silently skipped"
contract.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _create_template(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    body = {"name": kwargs.pop("name", "t"), **kwargs}
    resp = client.post("/api/templates", json=body)
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _default_tag(client: TestClient) -> int:
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


# --- create ---------------------------------------------------------


def test_post_template_returns_row(client: TestClient) -> None:
    resp = client.post(
        "/api/templates",
        json={
            "name": "Debug helper",
            "body": "Walk me through the failing test.",
            "working_dir": "/tmp/work",
            "model": "claude-sonnet-4-6",
            "session_instructions": "Be concise.",
            "tag_ids": [],
        },
    )
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["name"] == "Debug helper"
    assert row["body"] == "Walk me through the failing test."
    assert row["working_dir"] == "/tmp/work"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["session_instructions"] == "Be concise."
    assert row["tag_ids"] == []
    assert "created_at" in row
    assert len(row["id"]) == 32


def test_post_template_allows_blank_scratchpad(client: TestClient) -> None:
    row = _create_template(client, name="Scratchpad")
    assert row["body"] is None
    assert row["working_dir"] is None
    assert row["model"] is None
    assert row["session_instructions"] is None


def test_post_template_rejects_empty_name(client: TestClient) -> None:
    resp = client.post("/api/templates", json={"name": ""})
    assert resp.status_code == 422


# --- list -----------------------------------------------------------


def test_get_templates_returns_empty_list_on_fresh_db(client: TestClient) -> None:
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_templates_includes_created_rows(client: TestClient) -> None:
    first = _create_template(client, name="first")
    second = _create_template(client, name="second")
    resp = client.get("/api/templates")
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.json()}
    assert ids == {first["id"], second["id"]}


# --- delete ---------------------------------------------------------


def test_delete_template_204_on_hit(client: TestClient) -> None:
    row = _create_template(client, name="to-kill")
    resp = client.delete(f"/api/templates/{row['id']}")
    assert resp.status_code == 204
    listing = client.get("/api/templates").json()
    assert all(r["id"] != row["id"] for r in listing)


def test_delete_template_404_on_miss(client: TestClient) -> None:
    resp = client.delete("/api/templates/deadbeef")
    assert resp.status_code == 404


# --- instantiate ----------------------------------------------------


def test_instantiate_template_creates_session(client: TestClient) -> None:
    tag_id = _default_tag(client)
    template = _create_template(
        client,
        name="Ready-to-go",
        body="Let's get started.",
        working_dir="/tmp/work",
        model="claude-sonnet-4-6",
        session_instructions="Respond in haiku.",
        tag_ids=[tag_id],
    )
    resp = client.post(
        f"/api/sessions/from_template/{template['id']}",
        json={},
    )
    assert resp.status_code == 201, resp.text
    session = resp.json()
    assert session["working_dir"] == "/tmp/work"
    assert session["model"] == "claude-sonnet-4-6"
    assert session["title"] == "Ready-to-go"
    # The template's `body` was seeded as the first user message.
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Let's get started."
    # Tag from the template survived to the session.
    tags = client.get(f"/api/sessions/{session['id']}/tags").json()
    assert any(t["id"] == tag_id for t in tags)


def test_instantiate_template_request_fields_override_saved(
    client: TestClient,
) -> None:
    template = _create_template(
        client,
        name="Defaults",
        body="saved prompt",
        working_dir="/tmp/saved",
        model="claude-sonnet-4-6",
    )
    resp = client.post(
        f"/api/sessions/from_template/{template['id']}",
        json={
            "title": "Override title",
            "working_dir": "/tmp/override",
            "body": "override prompt",
        },
    )
    assert resp.status_code == 201, resp.text
    session = resp.json()
    assert session["title"] == "Override title"
    assert session["working_dir"] == "/tmp/override"
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert messages[0]["content"] == "override prompt"


def test_instantiate_template_skips_missing_tags(client: TestClient) -> None:
    """If a tag was deleted after the template was saved, the
    instantiate path silently drops it rather than 400ing."""
    tag_id = _default_tag(client)
    template = _create_template(
        client,
        name="Stale tags",
        working_dir="/tmp/work",
        model="claude-sonnet-4-6",
        tag_ids=[tag_id, 99999],  # 99999 doesn't exist
    )
    resp = client.post(
        f"/api/sessions/from_template/{template['id']}",
        json={},
    )
    assert resp.status_code == 201, resp.text


def test_instantiate_template_blank_body_creates_empty_session(
    client: TestClient,
) -> None:
    template = _create_template(
        client,
        name="Blank",
        working_dir="/tmp/work",
        model="claude-sonnet-4-6",
    )
    resp = client.post(
        f"/api/sessions/from_template/{template['id']}",
        json={},
    )
    assert resp.status_code == 201, resp.text
    session = resp.json()
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert messages == []


def test_instantiate_template_404_on_missing_template(client: TestClient) -> None:
    resp = client.post("/api/sessions/from_template/deadbeef", json={})
    assert resp.status_code == 404


def test_instantiate_template_400_when_working_dir_missing(client: TestClient) -> None:
    """Template saved without a working_dir requires the caller to
    supply one on instantiation. Saved-null + request-null = 400."""
    template = _create_template(client, name="No dir", model="claude-sonnet-4-6")
    resp = client.post(
        f"/api/sessions/from_template/{template['id']}",
        json={},
    )
    assert resp.status_code == 400


def test_instantiate_template_400_when_model_missing(client: TestClient) -> None:
    """Template saved without a model requires the caller to supply
    one on instantiation. Saved-null + request-null = 400."""
    template = _create_template(client, name="No model", working_dir="/tmp/work")
    resp = client.post(
        f"/api/sessions/from_template/{template['id']}",
        json={},
    )
    assert resp.status_code == 400
