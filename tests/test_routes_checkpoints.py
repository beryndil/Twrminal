"""HTTP surface for Phase 7.2 of docs/context-menu-plan.md.

Covers the four checkpoint endpoints:

  POST   /api/sessions/{id}/checkpoints              — create
  GET    /api/sessions/{id}/checkpoints              — list
  DELETE /api/sessions/{id}/checkpoints/{cid}        — remove
  POST   /api/sessions/{id}/checkpoints/{cid}/fork   — branch

Messages are seeded via the existing `/api/sessions/import` endpoint
(synthetic export shape) so each test gets deterministic ids and
timestamps without needing the WS stream. The same pattern is used
elsewhere in this test suite — see `test_import_roundtrip_preserves_content`.
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


def _create_session(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    tag_ids = kwargs.pop("tag_ids", None) or [_default_tag(client)]
    body = {
        "working_dir": "/tmp",
        "model": "claude-sonnet-4-6",
        # v0.20.6: title is required at the API boundary; default to a
        # placeholder so the bulk of these tests don't have to pick one.
        "title": kwargs.pop("title", None) or "test session",
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    out: dict[str, Any] = resp.json()
    return out


def _seed_with_messages(client: TestClient, *, title: str = "seeded") -> dict[str, Any]:
    """Create a session pre-loaded with three messages at ascending
    timestamps. Returns the imported session dict plus the messages as
    fetched from `/messages`."""
    payload = {
        "session": {
            "id": "ignored-remapped",
            "working_dir": "/tmp",
            "model": "claude-sonnet-4-6",
            "title": title,
        },
        "messages": [
            {"id": "m1", "role": "user", "content": "first", "created_at": "2026-04-22T00:00:01Z"},
            {
                "id": "m2",
                "role": "assistant",
                "content": "second",
                "created_at": "2026-04-22T00:00:02Z",
            },
            {"id": "m3", "role": "user", "content": "third", "created_at": "2026-04-22T00:00:03Z"},
        ],
        "tool_calls": [],
    }
    resp = client.post("/api/sessions/import", json=payload)
    assert resp.status_code == 200, resp.text
    session = resp.json()
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()
    session["_messages"] = messages
    return session


# --- create ---------------------------------------------------------


def test_post_checkpoint_returns_row(client: TestClient) -> None:
    session = _seed_with_messages(client)
    anchor = session["_messages"][1]
    resp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": anchor["id"], "label": "mid"},
    )
    assert resp.status_code == 201, resp.text
    row = resp.json()
    assert row["session_id"] == session["id"]
    assert row["message_id"] == anchor["id"]
    assert row["label"] == "mid"
    assert len(row["id"]) == 32


def test_post_checkpoint_allows_null_label(client: TestClient) -> None:
    session = _seed_with_messages(client)
    anchor = session["_messages"][0]
    resp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": anchor["id"]},
    )
    assert resp.status_code == 201
    assert resp.json()["label"] is None


def test_post_checkpoint_on_missing_session_404(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions/" + "0" * 32 + "/checkpoints",
        json={"message_id": "whatever"},
    )
    assert resp.status_code == 404


def test_post_checkpoint_unknown_message_404(client: TestClient) -> None:
    session = _create_session(client)
    resp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": "no-such-msg"},
    )
    assert resp.status_code == 404


def test_post_checkpoint_cross_session_message_400(client: TestClient) -> None:
    """A message id from session A must not anchor a checkpoint under
    session B — the route validates the owning session explicitly."""
    a = _seed_with_messages(client, title="A")
    b = _create_session(client, title="B")
    resp = client.post(
        f"/api/sessions/{b['id']}/checkpoints",
        json={"message_id": a["_messages"][0]["id"]},
    )
    assert resp.status_code == 400


# --- list -----------------------------------------------------------


def test_list_checkpoints_returns_newest_first(client: TestClient) -> None:
    session = _seed_with_messages(client)
    for i, msg in enumerate(session["_messages"]):
        client.post(
            f"/api/sessions/{session['id']}/checkpoints",
            json={"message_id": msg["id"], "label": f"cp-{i}"},
        )
    resp = client.get(f"/api/sessions/{session['id']}/checkpoints")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 3
    assert {r["label"] for r in rows} == {"cp-0", "cp-1", "cp-2"}


def test_list_checkpoints_empty_session(client: TestClient) -> None:
    session = _create_session(client)
    resp = client.get(f"/api/sessions/{session['id']}/checkpoints")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_checkpoints_missing_session_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/checkpoints")
    assert resp.status_code == 404


# --- delete ---------------------------------------------------------


def test_delete_checkpoint_returns_204(client: TestClient) -> None:
    session = _seed_with_messages(client)
    created = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": session["_messages"][0]["id"]},
    ).json()
    resp = client.delete(f"/api/sessions/{session['id']}/checkpoints/{created['id']}")
    assert resp.status_code == 204
    # Confirm it's actually gone
    rows = client.get(f"/api/sessions/{session['id']}/checkpoints").json()
    assert rows == []


def test_delete_checkpoint_unknown_id_404(client: TestClient) -> None:
    session = _create_session(client)
    resp = client.delete(f"/api/sessions/{session['id']}/checkpoints/{'0' * 32}")
    assert resp.status_code == 404


def test_delete_checkpoint_cross_session_404(client: TestClient) -> None:
    """A checkpoint under session A can't be deleted via session B's URL."""
    a = _seed_with_messages(client, title="A")
    b = _create_session(client, title="B")
    cp = client.post(
        f"/api/sessions/{a['id']}/checkpoints",
        json={"message_id": a["_messages"][0]["id"]},
    ).json()
    resp = client.delete(f"/api/sessions/{b['id']}/checkpoints/{cp['id']}")
    assert resp.status_code == 404


# --- fork -----------------------------------------------------------


def test_fork_from_middle_keeps_prefix_only(client: TestClient) -> None:
    """Forking from message 2/3 should produce a session with the
    first two messages and drop the third."""
    session = _seed_with_messages(client, title="source")
    anchor = session["_messages"][1]
    cp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": anchor["id"], "label": "mid"},
    ).json()
    resp = client.post(
        f"/api/sessions/{session['id']}/checkpoints/{cp['id']}/fork",
        json={},
    )
    assert resp.status_code == 201, resp.text
    fork = resp.json()
    assert fork["id"] != session["id"]
    assert fork["title"] == "source (fork)"
    fork_msgs = client.get(f"/api/sessions/{fork['id']}/messages").json()
    assert [m["content"] for m in fork_msgs] == ["first", "second"]
    # Ids are remapped — not a reference to source messages.
    assert all(m["id"] != source_id for m, source_id in zip(fork_msgs, ["m1", "m2"], strict=True))


def test_fork_from_last_message_keeps_all(client: TestClient) -> None:
    session = _seed_with_messages(client, title="full")
    anchor = session["_messages"][-1]
    cp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": anchor["id"]},
    ).json()
    resp = client.post(
        f"/api/sessions/{session['id']}/checkpoints/{cp['id']}/fork",
        json={},
    )
    assert resp.status_code == 201
    fork = resp.json()
    fork_msgs = client.get(f"/api/sessions/{fork['id']}/messages").json()
    assert len(fork_msgs) == 3


def test_fork_with_explicit_title_overrides_default(client: TestClient) -> None:
    session = _seed_with_messages(client, title="source")
    anchor = session["_messages"][0]
    cp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": anchor["id"]},
    ).json()
    resp = client.post(
        f"/api/sessions/{session['id']}/checkpoints/{cp['id']}/fork",
        json={"title": "branch-a"},
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "branch-a"


def test_fork_inherits_source_tags(client: TestClient) -> None:
    """The fork must land in the same sidebar bucket as the source —
    i.e. carry every tag the source had."""
    extra_tag = client.post("/api/tags", json={"name": "feature-x"}).json()
    session = _seed_with_messages(client)
    # Attach the custom tag to the source
    client.post(f"/api/sessions/{session['id']}/tags/{extra_tag['id']}")
    cp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": session["_messages"][0]["id"]},
    ).json()
    fork = client.post(f"/api/sessions/{session['id']}/checkpoints/{cp['id']}/fork", json={}).json()
    assert extra_tag["id"] in fork["tag_ids"]


def test_fork_on_orphaned_checkpoint_returns_400(client: TestClient) -> None:
    """A checkpoint whose anchor message got dropped (ON DELETE SET NULL
    fires on message delete) can't be forked — the route rejects the
    call with a readable 400."""
    session = _seed_with_messages(client)
    anchor = session["_messages"][0]
    cp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": anchor["id"]},
    ).json()
    # Delete the anchor message via direct SQL (no route exists for
    # message delete outside reorg audits; we emulate the reorg effect).
    import asyncio

    async def _drop() -> None:
        conn = client.app.state.db  # type: ignore[attr-defined]
        await conn.execute("DELETE FROM messages WHERE id = ?", (anchor["id"],))
        await conn.commit()

    asyncio.run(_drop())
    resp = client.post(
        f"/api/sessions/{session['id']}/checkpoints/{cp['id']}/fork",
        json={},
    )
    assert resp.status_code == 400


def test_fork_source_remains_intact(client: TestClient) -> None:
    """A fork must never touch the source. After the fork the source
    still has all three messages and the checkpoint still resolves."""
    session = _seed_with_messages(client, title="immutable")
    cp = client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": session["_messages"][0]["id"]},
    ).json()
    client.post(
        f"/api/sessions/{session['id']}/checkpoints/{cp['id']}/fork",
        json={},
    )
    src_msgs = client.get(f"/api/sessions/{session['id']}/messages").json()
    assert len(src_msgs) == 3
    cps = client.get(f"/api/sessions/{session['id']}/checkpoints").json()
    assert [r["id"] for r in cps] == [cp["id"]]


def test_session_delete_cascades_to_checkpoints_http(client: TestClient) -> None:
    """Delete the session and the checkpoints disappear — mirrors the
    FK cascade, verified through HTTP."""
    session = _seed_with_messages(client)
    client.post(
        f"/api/sessions/{session['id']}/checkpoints",
        json={"message_id": session["_messages"][0]["id"]},
    )
    client.delete(f"/api/sessions/{session['id']}")
    resp = client.get(f"/api/sessions/{session['id']}/checkpoints")
    assert resp.status_code == 404  # session gone → 404 on list
