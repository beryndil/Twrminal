"""HTTP surface for Phase 8 of docs/context-menu-plan.md.

Covers the single message mutation endpoint:

  PATCH /api/messages/{message_id} — toggle pinned / hidden_from_context

Messages are seeded via the `/api/sessions/import` endpoint — same
pattern used by `test_routes_checkpoints.py` — so each test gets
deterministic ids without needing the WS stream to create them.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _default_tag(client: TestClient) -> int:
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


def _seed_with_messages(client: TestClient) -> dict[str, Any]:
    """Create a session with two messages at ascending timestamps.
    Returns the imported session dict with messages as `_messages`."""
    payload = {
        "session": {
            "id": "ignored-remapped",
            "working_dir": "/tmp",
            "model": "claude-sonnet-4-6",
            "title": "seeded",
        },
        "messages": [
            {"id": "m1", "role": "user", "content": "first", "created_at": "2026-04-22T00:00:01Z"},
            {
                "id": "m2",
                "role": "assistant",
                "content": "second",
                "created_at": "2026-04-22T00:00:02Z",
            },
        ],
        "tool_calls": [],
    }
    resp = client.post("/api/sessions/import", json=payload)
    assert resp.status_code == 200, resp.text
    session = resp.json()
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    session["_messages"] = messages
    return session


# --- defaults -------------------------------------------------------


def test_message_out_defaults_flags_false(client: TestClient) -> None:
    """Freshly imported rows must serialize the flag columns as False —
    the migration sets DEFAULT 0 so pre-0023 rows read that way too."""
    session = _seed_with_messages(client)
    for msg in session["_messages"]:
        assert msg["pinned"] is False
        assert msg["hidden_from_context"] is False


# --- pin / unpin ----------------------------------------------------


def test_patch_pin_flips_flag_to_true(client: TestClient) -> None:
    session = _seed_with_messages(client)
    msg = session["_messages"][0]
    resp = client.patch(f"/api/messages/{msg['id']}", json={"pinned": True})
    assert resp.status_code == 200, resp.text
    row = resp.json()
    assert row["pinned"] is True
    assert row["hidden_from_context"] is False
    # Persisted — a fresh list reflects the change
    refetched = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert refetched[0]["pinned"] is True


def test_patch_unpin_flips_flag_to_false(client: TestClient) -> None:
    session = _seed_with_messages(client)
    msg = session["_messages"][0]
    client.patch(f"/api/messages/{msg['id']}", json={"pinned": True})
    resp = client.patch(f"/api/messages/{msg['id']}", json={"pinned": False})
    assert resp.status_code == 200
    assert resp.json()["pinned"] is False


# --- hide / unhide --------------------------------------------------


def test_patch_hide_flips_flag_to_true(client: TestClient) -> None:
    session = _seed_with_messages(client)
    msg = session["_messages"][1]
    resp = client.patch(
        f"/api/messages/{msg['id']}",
        json={"hidden_from_context": True},
    )
    assert resp.status_code == 200
    assert resp.json()["hidden_from_context"] is True


def test_patch_unhide_flips_flag_to_false(client: TestClient) -> None:
    session = _seed_with_messages(client)
    msg = session["_messages"][1]
    client.patch(f"/api/messages/{msg['id']}", json={"hidden_from_context": True})
    resp = client.patch(
        f"/api/messages/{msg['id']}",
        json={"hidden_from_context": False},
    )
    assert resp.status_code == 200
    assert resp.json()["hidden_from_context"] is False


# --- combined + no-op -----------------------------------------------


def test_patch_both_fields_in_one_call(client: TestClient) -> None:
    """A single PATCH can toggle both flags — the store applies each
    non-null column in the same UPDATE."""
    session = _seed_with_messages(client)
    msg = session["_messages"][0]
    resp = client.patch(
        f"/api/messages/{msg['id']}",
        json={"pinned": True, "hidden_from_context": True},
    )
    assert resp.status_code == 200
    row = resp.json()
    assert row["pinned"] is True
    assert row["hidden_from_context"] is True


def test_patch_empty_body_is_noop(client: TestClient) -> None:
    """A PATCH with no fields set doesn't bump any column. We still
    return 200 with the current row so clients reconcile uniformly."""
    session = _seed_with_messages(client)
    msg = session["_messages"][0]
    resp = client.patch(f"/api/messages/{msg['id']}", json={})
    assert resp.status_code == 200
    row = resp.json()
    assert row["pinned"] is False
    assert row["hidden_from_context"] is False


def test_patch_preserves_other_flag(client: TestClient) -> None:
    """Touching only `pinned` must leave `hidden_from_context` alone."""
    session = _seed_with_messages(client)
    msg = session["_messages"][0]
    client.patch(f"/api/messages/{msg['id']}", json={"hidden_from_context": True})
    resp = client.patch(f"/api/messages/{msg['id']}", json={"pinned": True})
    assert resp.status_code == 200
    row = resp.json()
    assert row["pinned"] is True
    assert row["hidden_from_context"] is True  # untouched


# --- error paths ----------------------------------------------------


def test_patch_unknown_message_returns_404(client: TestClient) -> None:
    resp = client.patch("/api/messages/no-such-id", json={"pinned": True})
    assert resp.status_code == 404


def test_patch_invalid_flag_type_returns_422(client: TestClient) -> None:
    """Pydantic rejects a non-bool at the boundary — the store never
    sees the bad payload."""
    session = _seed_with_messages(client)
    msg = session["_messages"][0]
    resp = client.patch(
        f"/api/messages/{msg['id']}",
        json={"pinned": "not-a-bool"},
    )
    assert resp.status_code == 422


# --- context-window filter ------------------------------------------


def test_hidden_row_still_renders_in_messages_list(client: TestClient) -> None:
    """Hiding a message drops it from the agent's prompt but NOT from
    the conversation view — the row still appears in GET /messages so
    the UI can render it greyed and offer an unhide toggle."""
    session = _seed_with_messages(client)
    msg = session["_messages"][0]
    client.patch(f"/api/messages/{msg['id']}", json={"hidden_from_context": True})
    rows = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert len(rows) == 2
    assert rows[0]["id"] == msg["id"]
    assert rows[0]["hidden_from_context"] is True
