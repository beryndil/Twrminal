"""HTTP surface for Slice 2 of the checklist feature.

Covers POST /sessions with kind='checklist' (autocreates the
companion row), the seven /sessions/{id}/checklist/* endpoints, and
the cascade-on-session-delete guarantee from the HTTP side. Shape
mirrors test_routes_sessions.py / test_routes_reorg.py — TestClient
+ synchronous asserts, no WS plumbing.
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
        "title": kwargs.pop("title", None),
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _create_checklist(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    return _create_session(client, kind="checklist", title="plan", **kwargs)


def test_create_chat_session_has_kind_chat(client: TestClient) -> None:
    row = _create_session(client)
    assert row["kind"] == "chat"


def test_create_checklist_session_has_kind_and_body(client: TestClient) -> None:
    row = _create_checklist(client)
    assert row["kind"] == "checklist"
    resp = client.get(f"/api/sessions/{row['id']}/checklist")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == row["id"]
    assert body["items"] == []


def test_get_checklist_on_chat_returns_400(client: TestClient) -> None:
    row = _create_session(client)
    resp = client.get(f"/api/sessions/{row['id']}/checklist")
    assert resp.status_code == 400
    assert "checklist" in resp.json()["detail"]


def test_get_checklist_on_missing_session_returns_404(client: TestClient) -> None:
    resp = client.get("/api/sessions/" + "0" * 32 + "/checklist")
    assert resp.status_code == 404


def test_patch_checklist_updates_notes(client: TestClient) -> None:
    row = _create_checklist(client)
    resp = client.patch(
        f"/api/sessions/{row['id']}/checklist",
        json={"notes": "remember to"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "remember to"


def test_create_item_appends_and_persists(client: TestClient) -> None:
    row = _create_checklist(client)
    first = client.post(
        f"/api/sessions/{row['id']}/checklist/items",
        json={"label": "first"},
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/sessions/{row['id']}/checklist/items",
        json={"label": "second"},
    )
    assert second.status_code == 201
    assert second.json()["sort_order"] > first.json()["sort_order"]

    listing = client.get(f"/api/sessions/{row['id']}/checklist").json()
    labels = [i["label"] for i in listing["items"]]
    assert labels == ["first", "second"]


def test_create_item_on_chat_session_returns_400(client: TestClient) -> None:
    row = _create_session(client)
    resp = client.post(
        f"/api/sessions/{row['id']}/checklist/items",
        json={"label": "nope"},
    )
    assert resp.status_code == 400


def test_toggle_item_stamps_and_clears_checked_at(client: TestClient) -> None:
    row = _create_checklist(client)
    item = client.post(
        f"/api/sessions/{row['id']}/checklist/items",
        json={"label": "todo"},
    ).json()
    checked = client.post(
        f"/api/sessions/{row['id']}/checklist/items/{item['id']}/toggle",
        json={"checked": True},
    )
    assert checked.status_code == 200
    assert checked.json()["checked_at"] is not None
    unchecked = client.post(
        f"/api/sessions/{row['id']}/checklist/items/{item['id']}/toggle",
        json={"checked": False},
    )
    assert unchecked.json()["checked_at"] is None


def test_toggle_rejects_item_from_other_checklist(client: TestClient) -> None:
    row_a = _create_checklist(client)
    row_b = _create_checklist(client)
    item_b = client.post(
        f"/api/sessions/{row_b['id']}/checklist/items",
        json={"label": "in B"},
    ).json()
    # Using row_a's id with row_b's item id must 404; otherwise a
    # malicious client could mutate items across checklists.
    resp = client.post(
        f"/api/sessions/{row_a['id']}/checklist/items/{item_b['id']}/toggle",
        json={"checked": True},
    )
    assert resp.status_code == 404


def test_update_item_label(client: TestClient) -> None:
    row = _create_checklist(client)
    item = client.post(
        f"/api/sessions/{row['id']}/checklist/items",
        json={"label": "old"},
    ).json()
    resp = client.patch(
        f"/api/sessions/{row['id']}/checklist/items/{item['id']}",
        json={"label": "new"},
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "new"


def test_delete_item_removes_row(client: TestClient) -> None:
    row = _create_checklist(client)
    item = client.post(
        f"/api/sessions/{row['id']}/checklist/items",
        json={"label": "bye"},
    ).json()
    resp = client.delete(f"/api/sessions/{row['id']}/checklist/items/{item['id']}")
    assert resp.status_code == 204
    listing = client.get(f"/api/sessions/{row['id']}/checklist").json()
    assert listing["items"] == []


def test_reorder_rewrites_sort_order(client: TestClient) -> None:
    row = _create_checklist(client)
    ids: list[int] = []
    for label in ("a", "b", "c"):
        item = client.post(
            f"/api/sessions/{row['id']}/checklist/items",
            json={"label": label},
        ).json()
        ids.append(item["id"])
    reversed_ids = list(reversed(ids))
    resp = client.post(
        f"/api/sessions/{row['id']}/checklist/reorder",
        json={"item_ids": reversed_ids},
    )
    assert resp.status_code == 200
    assert resp.json()["reordered"] == 3
    listing = client.get(f"/api/sessions/{row['id']}/checklist").json()
    assert [i["label"] for i in listing["items"]] == ["c", "b", "a"]


def test_delete_session_cascades_to_checklist(client: TestClient) -> None:
    row = _create_checklist(client)
    client.post(
        f"/api/sessions/{row['id']}/checklist/items",
        json={"label": "goodbye"},
    )
    resp = client.delete(f"/api/sessions/{row['id']}")
    assert resp.status_code == 200
    # GET on a deleted session returns 404 (session-level check
    # fires before the checklist lookup).
    resp = client.get(f"/api/sessions/{row['id']}/checklist")
    assert resp.status_code == 404


def test_reorg_move_rejects_checklist_source(client: TestClient) -> None:
    source = _create_checklist(client)
    target = _create_session(client)
    resp = client.post(
        f"/api/sessions/{source['id']}/reorg/move",
        json={
            "target_session_id": target["id"],
            "message_ids": ["00000000000000000000000000000000"],
        },
    )
    assert resp.status_code == 400
    assert "chat" in resp.json()["detail"]


def test_reorg_move_rejects_checklist_target(client: TestClient) -> None:
    source = _create_session(client)
    target = _create_checklist(client)
    resp = client.post(
        f"/api/sessions/{source['id']}/reorg/move",
        json={
            "target_session_id": target["id"],
            "message_ids": ["00000000000000000000000000000000"],
        },
    )
    assert resp.status_code == 400


def test_reorg_split_rejects_checklist_source(client: TestClient) -> None:
    source = _create_checklist(client)
    tag_id = _default_tag(client)
    resp = client.post(
        f"/api/sessions/{source['id']}/reorg/split",
        json={
            "after_message_id": "00000000000000000000000000000000",
            "new_session": {"title": "x", "tag_ids": [tag_id]},
        },
    )
    assert resp.status_code == 400


def test_ws_accepts_checklist_session(client: TestClient, mock_agent_stream: None) -> None:
    """v0.5.2: checklist sessions joined the runnable set so the
    embedded chat panel in ChecklistView can talk to the agent about
    the list. A successful handshake is the first `runner_status`
    frame coming back instead of a close 4400."""
    import json

    row = _create_checklist(client)
    with client.websocket_connect(f"/ws/sessions/{row['id']}") as ws:
        frame = json.loads(ws.receive_text())
        assert frame["type"] == "runner_status"
        assert frame["session_id"] == row["id"]


def test_reorg_merge_rejects_checklist_either_side(client: TestClient) -> None:
    checklist = _create_checklist(client)
    chat = _create_session(client)
    resp = client.post(
        f"/api/sessions/{checklist['id']}/reorg/merge",
        json={"target_session_id": chat["id"]},
    )
    assert resp.status_code == 400
    resp = client.post(
        f"/api/sessions/{chat['id']}/reorg/merge",
        json={"target_session_id": checklist["id"]},
    )
    assert resp.status_code == 400
