"""HTTP surface for L4.3.1 — `POST /api/sessions/{id}/spawn_from_reply/{message_id}`.

Wave 2 lane 1 of the assistant-reply action row (TODO.md research entry
2026-04-22). v0 always creates a single chat-kind session seeded with
the assistant reply.

Coverage:
  - happy path: new session inherits parent's working_dir + tags + model
  - title synthesized from the reply's first line, capped at ~60 chars
  - description = full reply + provenance footer
  - empty reply → fallback title `Spawn from <parent title>`
  - 400 on user message (we spawn from the reply, not the prompt)
  - 400 on cross-session message id
  - 404 on unknown session / message
  - source session is untouched
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _default_tag(client: TestClient, *, name: str = "default") -> int:
    existing = client.get("/api/tags").json()
    for tag in existing:
        if tag["name"] == name:
            return int(tag["id"])
    created = client.post("/api/tags", json={"name": name})
    return int(created.json()["id"])


def _seed(
    client: TestClient,
    *,
    title: str = "parent",
    assistant_content: str = "alpha-resp",
) -> dict[str, Any]:
    """Plant a session with one user / one assistant turn and return
    the imported row + its message list (under `_messages`). Imported
    via /api/sessions/import so tests don't need to drive a real
    runner. The default-severity backfill keeps the `tag_ids` invariant
    intact post-import."""
    payload = {
        "session": {
            "working_dir": "/tmp/parent-cwd",
            "model": "claude-sonnet-4-6",
            "title": title,
        },
        "messages": [
            {
                "id": "u1",
                "role": "user",
                "content": "give me alpha",
                "created_at": "2026-04-22T00:00:01Z",
            },
            {
                "id": "a1",
                "role": "assistant",
                "content": assistant_content,
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


def _assistant_msg(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for m in messages:
        if m["role"] == "assistant":
            return m
    raise AssertionError("no assistant row in seeded session")


def _user_msg(messages: list[dict[str, Any]]) -> dict[str, Any]:
    for m in messages:
        if m["role"] == "user":
            return m
    raise AssertionError("no user row in seeded session")


def test_spawn_from_reply_creates_new_chat_session(client: TestClient) -> None:
    """Happy path: new session is `chat` kind, has no messages, and
    inherits parent's working_dir + model."""
    parent = _seed(client)
    assistant = _assistant_msg(parent["_messages"])

    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{assistant['id']}")
    assert resp.status_code == 201, resp.text
    new_session = resp.json()
    assert new_session["id"] != parent["id"]
    assert new_session["kind"] == "chat"
    assert new_session["working_dir"] == parent["working_dir"]
    assert new_session["model"] == parent["model"]
    # Brand-new session has no messages.
    msgs = client.get(f"/api/sessions/{new_session['id']}/messages").json()
    assert msgs == []


def test_spawn_from_reply_inherits_parent_tags(client: TestClient) -> None:
    """Every parent tag (general + severity) reaches the new session.
    `ensure_default_severity` is idempotent so the inherited severity
    isn't doubled."""
    # Seed parent and add an extra non-default tag so we can confirm
    # both the auto-attached severity AND the user-added tag follow.
    parent = _seed(client)
    extra_tag = _default_tag(client, name="extra")
    client.post(f"/api/sessions/{parent['id']}/tags/{extra_tag}")

    parent_tag_ids = {t["id"] for t in client.get(f"/api/sessions/{parent['id']}/tags").json()}
    assert extra_tag in parent_tag_ids

    assistant = _assistant_msg(parent["_messages"])
    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{assistant['id']}")
    assert resp.status_code == 201
    new_id = resp.json()["id"]
    new_tag_ids = {t["id"] for t in client.get(f"/api/sessions/{new_id}/tags").json()}
    # Spawned session carries every tag the parent had; ensure_default_
    # severity must not re-add a duplicate severity row.
    assert parent_tag_ids <= new_tag_ids


def test_spawn_from_reply_title_is_first_line_of_reply(client: TestClient) -> None:
    """Title comes from the reply's first non-blank line, with leading
    markdown noise stripped. Shorter than 60 chars so no ellipsis."""
    parent = _seed(client, assistant_content="# Roadmap\n\nFirst paragraph.")
    assistant = _assistant_msg(parent["_messages"])
    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{assistant['id']}")
    assert resp.status_code == 201
    assert resp.json()["title"] == "Roadmap"


def test_spawn_from_reply_title_truncates_long_first_line(client: TestClient) -> None:
    long = "x" * 200
    parent = _seed(client, assistant_content=long)
    assistant = _assistant_msg(parent["_messages"])
    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{assistant['id']}")
    assert resp.status_code == 201
    title = resp.json()["title"]
    # 59 chars + ellipsis = 60 displayed glyphs.
    assert len(title) == 60
    assert title.endswith("…")


def test_spawn_from_reply_title_falls_back_when_reply_blank(
    client: TestClient,
) -> None:
    """Empty / whitespace-only reply → `Spawn from <parent title>`."""
    parent = _seed(client, title="parent thread", assistant_content="   \n   ")
    assistant = _assistant_msg(parent["_messages"])
    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{assistant['id']}")
    assert resp.status_code == 201
    assert resp.json()["title"] == "Spawn from parent thread"


def test_spawn_from_reply_description_carries_full_reply_and_provenance(
    client: TestClient,
) -> None:
    reply = "Multi\nline\nreply body."
    parent = _seed(client, assistant_content=reply)
    assistant = _assistant_msg(parent["_messages"])
    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{assistant['id']}")
    assert resp.status_code == 201
    desc = resp.json()["description"] or ""
    assert reply in desc
    # Provenance footer references both the parent session and the
    # message id so a fresh spawn of the new session can trace back.
    assert f"Spawned from session {parent['id']}, message {assistant['id']}" in desc


def test_spawn_from_reply_rejects_user_role(client: TestClient) -> None:
    """`spawn_from_reply` is reply-scoped — the user prompt is not a
    valid target. Mirror of the regenerate-from-message error contract
    (which is the inverse — rejects on no-user-found)."""
    parent = _seed(client)
    user = _user_msg(parent["_messages"])
    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{user['id']}")
    assert resp.status_code == 400
    assert "assistant" in resp.json()["detail"].lower()


def test_spawn_from_reply_cross_session_message_400(client: TestClient) -> None:
    """Message id from a different session → 400 (client bug, not
    silent spawn into the wrong tree)."""
    a = _seed(client, title="a")
    b = _seed(client, title="b")
    foreign = _assistant_msg(b["_messages"])
    resp = client.post(f"/api/sessions/{a['id']}/spawn_from_reply/{foreign['id']}")
    assert resp.status_code == 400


def test_spawn_from_reply_unknown_message_404(client: TestClient) -> None:
    parent = _seed(client)
    resp = client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/no-such-msg")
    assert resp.status_code == 404


def test_spawn_from_reply_unknown_session_404(client: TestClient) -> None:
    resp = client.post("/api/sessions/no-such-session/spawn_from_reply/some-msg")
    assert resp.status_code == 404


def test_spawn_from_reply_does_not_touch_source(client: TestClient) -> None:
    """Source session's messages survive the spawn — we never copy or
    move them, only read."""
    parent = _seed(client)
    assistant = _assistant_msg(parent["_messages"])
    client.post(f"/api/sessions/{parent['id']}/spawn_from_reply/{assistant['id']}")
    src_msgs = client.get(f"/api/sessions/{parent['id']}/messages").json()
    assert len(src_msgs) == 2
    # Title and tags on parent are untouched.
    src = client.get(f"/api/sessions/{parent['id']}").json()
    assert src["title"] == "parent"
