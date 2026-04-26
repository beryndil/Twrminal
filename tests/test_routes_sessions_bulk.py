"""HTTP surface for Phase 9a of docs/context-menu-plan.md.

Covers the single bulk dispatch endpoint:

  POST /api/sessions/bulk — {op, ids, payload}

One test module per op (tag/untag/close/delete/export) plus a shared
error-path section. Sessions are created via the normal POST routes so
the `tag_ids` invariant holds and the default-severity auto-attach
lands on every row.
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
        # v0.20.6: title is required at the API boundary; the bulk
        # tests don't care about the title, so default to a placeholder.
        "title": kwargs.pop("title", None) or "test session",
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    out: dict[str, Any] = resp.json()
    return out


# --- tag ------------------------------------------------------------


def test_bulk_tag_attaches_to_every_id(client: TestClient) -> None:
    a = _create_session(client)
    b = _create_session(client)
    extra = client.post("/api/tags", json={"name": "bulk-tag"}).json()
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "tag", "ids": [a["id"], b["id"]], "payload": {"tag_id": extra["id"]}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["op"] == "tag"
    assert set(body["succeeded"]) == {a["id"], b["id"]}
    assert body["failed"] == []
    # Verify the attach actually landed
    refreshed_a = client.get(f"/api/sessions/{a['id']}").json()
    refreshed_b = client.get(f"/api/sessions/{b['id']}").json()
    assert extra["id"] in refreshed_a["tag_ids"]
    assert extra["id"] in refreshed_b["tag_ids"]


def test_bulk_tag_missing_session_falls_into_failed(client: TestClient) -> None:
    a = _create_session(client)
    extra = client.post("/api/tags", json={"name": "partial-tag"}).json()
    resp = client.post(
        "/api/sessions/bulk",
        json={
            "op": "tag",
            "ids": [a["id"], "no-such-id"],
            "payload": {"tag_id": extra["id"]},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == [a["id"]]
    assert body["failed"] == [{"id": "no-such-id", "error": "session not found"}]


def test_bulk_tag_missing_tag_rejects_batch(client: TestClient) -> None:
    a = _create_session(client)
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "tag", "ids": [a["id"]], "payload": {"tag_id": 99_999}},
    )
    assert resp.status_code == 400


def test_bulk_tag_missing_payload_rejects(client: TestClient) -> None:
    a = _create_session(client)
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "tag", "ids": [a["id"]], "payload": {}},
    )
    assert resp.status_code == 400


# --- untag ----------------------------------------------------------


def test_bulk_untag_detaches_tag(client: TestClient) -> None:
    a = _create_session(client)
    extra = client.post("/api/tags", json={"name": "drop-me"}).json()
    client.post(f"/api/sessions/{a['id']}/tags/{extra['id']}")
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "untag", "ids": [a["id"]], "payload": {"tag_id": extra["id"]}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] == [a["id"]]
    refreshed = client.get(f"/api/sessions/{a['id']}").json()
    assert extra["id"] not in refreshed["tag_ids"]


def test_bulk_untag_missing_attachment_still_succeeds(client: TestClient) -> None:
    """Detaching a tag that was never attached is a silent no-op — the
    whole point of bulk untag is idempotency."""
    a = _create_session(client)
    extra = client.post("/api/tags", json={"name": "not-attached"}).json()
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "untag", "ids": [a["id"]], "payload": {"tag_id": extra["id"]}},
    )
    assert resp.status_code == 200
    assert resp.json()["succeeded"] == [a["id"]]


# --- close ----------------------------------------------------------


def test_bulk_close_stamps_closed_at(client: TestClient) -> None:
    a = _create_session(client)
    b = _create_session(client)
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "close", "ids": [a["id"], b["id"]], "payload": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["succeeded"]) == {a["id"], b["id"]}
    for sid in (a["id"], b["id"]):
        row = client.get(f"/api/sessions/{sid}").json()
        assert row["closed_at"] is not None


def test_bulk_close_mixed_valid_and_invalid(client: TestClient) -> None:
    a = _create_session(client)
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "close", "ids": [a["id"], "bogus"], "payload": {}},
    )
    body = resp.json()
    assert body["succeeded"] == [a["id"]]
    assert body["failed"] == [{"id": "bogus", "error": "session not found"}]


# --- delete ---------------------------------------------------------


def test_bulk_delete_sweeps_ids(client: TestClient) -> None:
    a = _create_session(client)
    b = _create_session(client)
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "delete", "ids": [a["id"], b["id"]], "payload": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["succeeded"]) == {a["id"], b["id"]}
    for sid in (a["id"], b["id"]):
        resp = client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 404


def test_bulk_delete_unknown_id_falls_into_failed(client: TestClient) -> None:
    a = _create_session(client)
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "delete", "ids": [a["id"], "nope"], "payload": {}},
    )
    body = resp.json()
    assert body["succeeded"] == [a["id"]]
    assert body["failed"] == [{"id": "nope", "error": "session not found"}]


# --- export ---------------------------------------------------------


def test_bulk_export_returns_per_id_bundle(client: TestClient) -> None:
    a = _create_session(client, title="one")
    b = _create_session(client, title="two")
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "export", "ids": [a["id"], b["id"]], "payload": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["op"] == "export"
    assert len(body["sessions"]) == 2
    # Shape is {session, messages, tool_calls} per the single-session
    # /export route — mirror the contract exactly.
    for entry in body["sessions"]:
        assert "session" in entry
        assert "messages" in entry
        assert "tool_calls" in entry
    assert body["failed"] == []


def test_bulk_export_unknown_id_falls_into_failed(client: TestClient) -> None:
    a = _create_session(client)
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "export", "ids": [a["id"], "ghost"], "payload": {}},
    )
    body = resp.json()
    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["session"]["id"] == a["id"]
    assert body["failed"] == [{"id": "ghost", "error": "session not found"}]


# --- shared error paths --------------------------------------------


def test_bulk_empty_ids_returns_400(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "close", "ids": [], "payload": {}},
    )
    assert resp.status_code == 400


def test_bulk_unknown_op_returns_422(client: TestClient) -> None:
    """Pydantic's Literal type rejects unknown ops at the boundary."""
    resp = client.post(
        "/api/sessions/bulk",
        json={"op": "nope", "ids": ["whatever"], "payload": {}},
    )
    assert resp.status_code == 422
