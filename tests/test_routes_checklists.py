"""Integration tests for ``bearings.web.routes.checklists`` via FastAPI.

Covers the picking / linking / reordering / run-control endpoint
categories from ``docs/behavior/checklists.md``. Each test exercises
the FastAPI handler end-to-end against a freshly-loaded schema.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from bearings.config.constants import (
    ITEM_OUTCOME_BLOCKED,
    ITEM_OUTCOME_FAILED,
    ITEM_OUTCOME_SKIPPED,
    PAIRED_CHAT_SPAWNED_BY_USER,
)
from bearings.db import get_connection_factory, load_schema
from bearings.web.app import create_app

_HEARTBEAT_S: Final[float] = 5.0
_CHECKLIST_ID: Final[str] = "chk_routes"


@pytest.fixture
def app_client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "routes_checklists.db"

    async def _open() -> aiosqlite.Connection:
        factory = get_connection_factory(db_path)
        conn = await factory()
        await load_schema(conn)
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                _CHECKLIST_ID,
                "checklist",
                "T",
                "/tmp",
                "sonnet",
                "2026-01-01",
                "2026-01-01",
            ),
        )
        # Pre-seed a chat-kind session for link tests
        await conn.execute(
            "INSERT INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "chat_link",
                "chat",
                "L",
                "/tmp",
                "sonnet",
                "2026-01-01",
                "2026-01-01",
            ),
        )
        await conn.commit()
        return conn

    loop = asyncio.new_event_loop()
    try:
        conn = loop.run_until_complete(_open())
        app = create_app(heartbeat_interval_s=_HEARTBEAT_S, db_connection=conn)
        # Stash the loop so sync test helpers can run async DB ops on the
        # same loop the connection was opened on (avoids get_event_loop() issues
        # when pytest-asyncio has torn down its own loop for earlier tests).
        app.state._test_loop = loop
        with TestClient(app) as client:
            yield client
        loop.run_until_complete(conn.close())
    finally:
        loop.close()


def _create_item(client: TestClient, label: str, **kwargs: object) -> int:
    response = client.post(
        f"/api/checklists/{_CHECKLIST_ID}/items",
        json={"label": label, **kwargs},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


# ---- create / read --------------------------------------------------------


def test_create_item_201(app_client: TestClient) -> None:
    response = app_client.post(
        f"/api/checklists/{_CHECKLIST_ID}/items",
        json={"label": "first"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "first"
    assert body["parent_item_id"] is None


def test_create_item_422_on_empty_label(app_client: TestClient) -> None:
    response = app_client.post(
        f"/api/checklists/{_CHECKLIST_ID}/items",
        json={"label": ""},
    )
    assert response.status_code == 422


def test_create_child_item_under_parent(app_client: TestClient) -> None:
    parent = _create_item(app_client, "P")
    response = app_client.post(
        f"/api/checklists/{_CHECKLIST_ID}/items",
        json={"label": "C", "parent_item_id": parent},
    )
    assert response.status_code == 201
    assert response.json()["parent_item_id"] == parent


def test_list_items(app_client: TestClient) -> None:
    _create_item(app_client, "A")
    _create_item(app_client, "B")
    response = app_client.get(f"/api/checklists/{_CHECKLIST_ID}/items")
    assert response.status_code == 200
    labels = [item["label"] for item in response.json()]
    assert labels == ["A", "B"]


def test_get_overview_bundles_active_run(app_client: TestClient) -> None:
    _create_item(app_client, "A")
    response = app_client.get(f"/api/checklists/{_CHECKLIST_ID}")
    assert response.status_code == 200
    body = response.json()
    assert body["checklist_id"] == _CHECKLIST_ID
    assert body["active_run"] is None
    assert len(body["items"]) == 1


def test_get_item_404(app_client: TestClient) -> None:
    response = app_client.get("/api/checklist-items/99999")
    assert response.status_code == 404


def test_get_item_round_trip(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    response = app_client.get(f"/api/checklist-items/{item_id}")
    assert response.status_code == 200
    assert response.json()["label"] == "A"


# ---- update / delete -----------------------------------------------------


def test_patch_item_updates_label(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    response = app_client.patch(
        f"/api/checklist-items/{item_id}",
        json={"label": "A-prime"},
    )
    assert response.status_code == 200
    assert response.json()["label"] == "A-prime"


def test_patch_item_updates_notes(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    response = app_client.patch(
        f"/api/checklist-items/{item_id}",
        json={"notes": "some notes"},
    )
    assert response.status_code == 200
    assert response.json()["notes"] == "some notes"


def test_patch_item_404(app_client: TestClient) -> None:
    response = app_client.patch("/api/checklist-items/99999", json={"label": "x"})
    assert response.status_code == 404


def test_patch_rejects_extra_keys(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    response = app_client.patch(
        f"/api/checklist-items/{item_id}",
        json={"random": "x"},
    )
    assert response.status_code == 422


def test_delete_item_204(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    response = app_client.delete(f"/api/checklist-items/{item_id}")
    assert response.status_code == 204
    # Idempotent 404 on second delete
    response2 = app_client.delete(f"/api/checklist-items/{item_id}")
    assert response2.status_code == 404


# ---- check / uncheck / block / unblock ----------------------------------


def test_check_item_marks_green(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    response = app_client.post(f"/api/checklist-items/{item_id}/check")
    assert response.status_code == 200
    assert response.json()["checked_at"] is not None


def test_uncheck_clears(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    app_client.post(f"/api/checklist-items/{item_id}/check")
    response = app_client.post(f"/api/checklist-items/{item_id}/uncheck")
    assert response.status_code == 200
    assert response.json()["checked_at"] is None


def test_check_404(app_client: TestClient) -> None:
    response = app_client.post("/api/checklist-items/99999/check")
    assert response.status_code == 404


def test_block_item_with_each_category(app_client: TestClient) -> None:
    for category in (ITEM_OUTCOME_BLOCKED, ITEM_OUTCOME_FAILED, ITEM_OUTCOME_SKIPPED):
        item_id = _create_item(app_client, f"task-{category}")
        response = app_client.post(
            f"/api/checklist-items/{item_id}/block",
            json={"category": category, "reason": "why"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["blocked_reason_category"] == category
        assert body["blocked_reason_text"] == "why"


def test_block_rejects_unknown_category(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    response = app_client.post(
        f"/api/checklist-items/{item_id}/block",
        json={"category": "bogus"},
    )
    assert response.status_code == 422


def test_unblock_clears(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "A")
    app_client.post(
        f"/api/checklist-items/{item_id}/block",
        json={"category": ITEM_OUTCOME_BLOCKED},
    )
    response = app_client.post(f"/api/checklist-items/{item_id}/unblock")
    assert response.status_code == 200
    assert response.json()["blocked_at"] is None


# ---- linking -------------------------------------------------------------


def test_link_chat_to_leaf(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "leaf")
    response = app_client.post(
        f"/api/checklist-items/{item_id}/link",
        json={
            "chat_session_id": "chat_link",
            "spawned_by": PAIRED_CHAT_SPAWNED_BY_USER,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["chat_session_id"] == "chat_link"


def test_link_rejects_parent(app_client: TestClient) -> None:
    parent = _create_item(app_client, "P")
    _create_item(app_client, "C", parent_item_id=parent)
    response = app_client.post(
        f"/api/checklist-items/{parent}/link",
        json={"chat_session_id": "chat_link"},
    )
    assert response.status_code == 422


def test_link_rejects_unknown_spawned_by(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "L")
    response = app_client.post(
        f"/api/checklist-items/{item_id}/link",
        json={"chat_session_id": "chat_link", "spawned_by": "bogus"},
    )
    assert response.status_code == 422


def test_unlink_clears_pointer(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "L")
    app_client.post(
        f"/api/checklist-items/{item_id}/link",
        json={"chat_session_id": "chat_link"},
    )
    response = app_client.post(f"/api/checklist-items/{item_id}/unlink")
    assert response.status_code == 200
    assert response.json()["chat_session_id"] is None


def test_list_legs_returns_one_per_link(app_client: TestClient) -> None:
    item_id = _create_item(app_client, "L")
    app_client.post(
        f"/api/checklist-items/{item_id}/link",
        json={"chat_session_id": "chat_link"},
    )
    response = app_client.get(f"/api/checklist-items/{item_id}/legs")
    assert response.status_code == 200
    legs = response.json()
    assert len(legs) == 1
    assert legs[0]["leg_number"] == 1


# ---- reordering / nesting ---------------------------------------------


def test_move_to_new_parent(app_client: TestClient) -> None:
    a = _create_item(app_client, "A")
    b = _create_item(app_client, "B")
    response = app_client.post(
        f"/api/checklist-items/{b}/move",
        json={"parent_item_id": a},
    )
    assert response.status_code == 200
    assert response.json()["parent_item_id"] == a


def test_move_rejects_self_parent(app_client: TestClient) -> None:
    a = _create_item(app_client, "A")
    response = app_client.post(
        f"/api/checklist-items/{a}/move",
        json={"parent_item_id": a},
    )
    assert response.status_code == 422


def test_indent_under_previous_sibling(app_client: TestClient) -> None:
    a = _create_item(app_client, "A")
    b = _create_item(app_client, "B")
    response = app_client.post(f"/api/checklist-items/{b}/indent")
    assert response.status_code == 200
    assert response.json()["parent_item_id"] == a


def test_outdent_at_root_is_noop(app_client: TestClient) -> None:
    a = _create_item(app_client, "A")
    response = app_client.post(f"/api/checklist-items/{a}/outdent")
    assert response.status_code == 200
    assert response.json()["parent_item_id"] is None


def test_outdent_404(app_client: TestClient) -> None:
    response = app_client.post("/api/checklist-items/99999/outdent")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# feature-6-002: check cascade — paired chat close + parent + checklist close
# ---------------------------------------------------------------------------


def _insert_chat_session(client: TestClient, session_id: str, *, closed: bool = False) -> None:
    """Directly insert a sessions row via SQL through the app's DB connection.

    Uses the test app's underlying aiosqlite connection stored on app.state.
    The loop stored at ``app.state._test_loop`` is used so the async write
    runs on the same event loop that opened the connection (avoids the
    'no current event loop' error when pytest-asyncio has torn down its loop).
    """
    db = client.app.state.db_connection  # type: ignore[attr-defined]
    loop = client.app.state._test_loop  # type: ignore[attr-defined]
    closed_at = "2026-01-01T00:00:00" if closed else None

    async def _run() -> None:
        await db.execute(
            "INSERT OR IGNORE INTO sessions (id, kind, title, working_dir, model, "
            "created_at, updated_at, closed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, "chat", "C", "/tmp", "sonnet", "2026-01-01", "2026-01-01", closed_at),
        )
        await db.commit()

    loop.run_until_complete(_run())


def _link_chat(client: TestClient, item_id: int, session_id: str) -> None:
    resp = client.post(
        f"/api/checklist-items/{item_id}/link",
        json={"chat_session_id": session_id, "spawned_by": "user"},
    )
    assert resp.status_code == 200, resp.text


def test_check_item_closes_paired_chat(app_client: TestClient) -> None:
    """POST /check on a paired leaf closes the paired chat session."""
    leaf = _create_item(app_client, "Leaf")
    _insert_chat_session(app_client, "chat_for_leaf")
    _link_chat(app_client, leaf, "chat_for_leaf")

    resp = app_client.post(f"/api/checklist-items/{leaf}/check")
    assert resp.status_code == 200

    # Verify the paired chat is now closed via the sessions endpoint.
    sess_resp = app_client.get("/api/sessions/chat_for_leaf")
    assert sess_resp.status_code == 200
    assert sess_resp.json()["closed_at"] is not None, "paired chat must be closed after check"


def test_check_item_cascade_auto_checks_parent(app_client: TestClient) -> None:
    """When the last child is checked the parent item is auto-checked."""
    parent = _create_item(app_client, "Parent")
    child_a = _create_item(app_client, "A", parent_item_id=parent)
    child_b = _create_item(app_client, "B", parent_item_id=parent)

    # Check child_a first — parent should NOT be checked yet.
    app_client.post(f"/api/checklist-items/{child_a}/check")
    parent_resp = app_client.get(f"/api/checklist-items/{parent}")
    assert parent_resp.json()["checked_at"] is None

    # Check child_b — now parent should be auto-checked.
    app_client.post(f"/api/checklist-items/{child_b}/check")
    parent_resp = app_client.get(f"/api/checklist-items/{parent}")
    assert parent_resp.json()["checked_at"] is not None, "parent must be auto-checked"


def test_check_last_root_item_closes_checklist_session(app_client: TestClient) -> None:
    """When every root item is checked the checklist session is closed."""
    leaf_a = _create_item(app_client, "A")
    leaf_b = _create_item(app_client, "B")

    app_client.post(f"/api/checklist-items/{leaf_a}/check")
    # Checklist must still be open after only one root checked.
    cl_resp = app_client.get(f"/api/sessions/{_CHECKLIST_ID}")
    assert cl_resp.json()["closed_at"] is None

    app_client.post(f"/api/checklist-items/{leaf_b}/check")
    # All roots checked — checklist session must now be closed.
    cl_resp = app_client.get(f"/api/sessions/{_CHECKLIST_ID}")
    assert cl_resp.json()["closed_at"] is not None, "checklist must be closed when all roots done"


def test_uncheck_does_not_reopen_closed_parent(app_client: TestClient) -> None:
    """POST /uncheck on a previously-checked item must not reopen closed parent."""
    parent = _create_item(app_client, "Parent")
    child = _create_item(app_client, "C", parent_item_id=parent)

    # Check child → triggers cascade → parent gets auto-checked.
    app_client.post(f"/api/checklist-items/{child}/check")
    parent_before = app_client.get(f"/api/checklist-items/{parent}").json()
    assert parent_before["checked_at"] is not None

    # Uncheck child — parent must remain checked (one-directional rule).
    app_client.post(f"/api/checklist-items/{child}/uncheck")
    parent_after = app_client.get(f"/api/checklist-items/{parent}").json()
    assert parent_after["checked_at"] is not None, "parent must remain checked after uncheck"


# ---------------------------------------------------------------------------
# F6-rt-18/19/20: /link input-validation gates
# F6-rt-24: /run/start 404 for missing checklist
# ---------------------------------------------------------------------------


def test_link_rejects_non_chat_kind_session(app_client: TestClient) -> None:
    """F6-rt-18 — /link must reject a non-chat-kind session_id with 422."""
    item_id = _create_item(app_client, "leaf-rt18")
    # _CHECKLIST_ID is kind=checklist — not a valid link target.
    response = app_client.post(
        f"/api/checklist-items/{item_id}/link",
        json={
            "chat_session_id": _CHECKLIST_ID,
            "spawned_by": PAIRED_CHAT_SPAWNED_BY_USER,
        },
    )
    assert response.status_code == 422, response.text


def test_link_rejects_closed_chat(app_client: TestClient) -> None:
    """F6-rt-19 — /link must reject a closed chat session with 422."""
    item_id = _create_item(app_client, "leaf-rt19")
    _insert_chat_session(app_client, "chat_closed_rt19", closed=True)
    response = app_client.post(
        f"/api/checklist-items/{item_id}/link",
        json={
            "chat_session_id": "chat_closed_rt19",
            "spawned_by": PAIRED_CHAT_SPAWNED_BY_USER,
        },
    )
    assert response.status_code == 422, response.text
    assert "closed" in response.json()["detail"]


def test_link_nonexistent_chat_returns_404(app_client: TestClient) -> None:
    """F6-rt-20 — /link to a nonexistent chat_session_id must return 404."""
    item_id = _create_item(app_client, "leaf-rt20")
    response = app_client.post(
        f"/api/checklist-items/{item_id}/link",
        json={
            "chat_session_id": "ses_does_not_exist",
            "spawned_by": PAIRED_CHAT_SPAWNED_BY_USER,
        },
    )
    assert response.status_code == 404, response.text


def test_run_start_404_for_missing_checklist(app_client: TestClient) -> None:
    """F6-rt-24 — /run/start on a nonexistent checklist_id must return 404."""
    from bearings.config.constants import AUTO_DRIVER_FAILURE_POLICY_HALT

    response = app_client.post(
        "/api/checklists/ses_does_not_exist/run/start",
        json={"failure_policy": AUTO_DRIVER_FAILURE_POLICY_HALT},
    )
    assert response.status_code == 404, response.text
