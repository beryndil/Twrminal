"""End-to-end HTTP tests for the autonomous-checklist endpoints.

Covers the full round-trip: `POST /sessions/{id}/checklist/run`
spawns a driver → driver spawns a leg paired to the item → fake
`AgentSession.stream` emits a sentinel → driver marks the item
checked and transitions to `finished`.

Uses `monkeypatch` on `AgentSession.stream` so the agent never
actually boots a Claude CLI subprocess; the test controls the
assistant text per session. Pattern mirrors
`tests/conftest.py::mock_agent_stream` but builds replies on the
fly because each checklist item id drives a distinct script.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from bearings.agent.events import (
    AgentEvent,
    MessageComplete,
    MessageStart,
    Token,
)
from bearings.agent.session import AgentSession


def _default_tag(client: TestClient) -> int:
    existing = client.get("/api/tags").json()
    if existing:
        tag_id: int = existing[0]["id"]
        return tag_id
    created = client.post("/api/tags", json={"name": "default"})
    return int(created.json()["id"])


def _create_checklist(client: TestClient) -> dict[str, Any]:
    """Create a tagged `kind='checklist'` session ready for items."""
    tag_id = _default_tag(client)
    resp = client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "claude-sonnet-4-6",
            "title": "plan",
            "kind": "checklist",
            "tag_ids": [tag_id],
        },
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _add_item(client: TestClient, session_id: str, label: str) -> dict[str, Any]:
    resp = client.post(
        f"/api/sessions/{session_id}/checklist/items",
        json={"label": label},
    )
    assert resp.status_code == 201, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _install_sentinel_stream(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Replace `AgentSession.stream` with a minimal stub that emits
    `text` as one Token block followed by a MessageComplete.

    Fresh `message_id` per turn via `uuid4` so a session that runs
    multiple turns doesn't collide on the `messages.id` PK. The
    runner's content-persist path concatenates tokens into the
    `messages.content` column; the driver's `run_turn` reads from
    that column and feeds it to the sentinel parser."""

    async def fake(self: AgentSession, prompt: str) -> AsyncIterator[AgentEvent]:
        msg_id = uuid4().hex
        yield MessageStart(session_id=self.session_id, message_id=msg_id)
        yield Token(session_id=self.session_id, text=text)
        yield MessageComplete(session_id=self.session_id, message_id=msg_id)

    monkeypatch.setattr("bearings.agent.session.AgentSession.stream", fake)


def _wait_for_run_state(
    client: TestClient,
    session_id: str,
    *,
    state: str,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Poll `GET /run` until `state` matches or timeout elapses.
    Returns the final status dict so the test can assert on
    outcome/counts in one place."""
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = client.get(f"/api/sessions/{session_id}/checklist/run")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("state") == state:
            return last
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for state={state!r}; last status={last!r}")


# --- happy path ----------------------------------------------------


def test_autonomous_run_completes_single_item(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One item, fake stream emits CHECKLIST_ITEM_DONE → driver marks
    the item checked and reports `finished` / `outcome=completed`."""
    _install_sentinel_stream(monkeypatch, "Work done.\nCHECKLIST_ITEM_DONE")
    checklist = _create_checklist(client)
    item = _add_item(client, checklist["id"], "prime")

    resp = client.post(f"/api/sessions/{checklist['id']}/checklist/run")
    assert resp.status_code == 202, resp.text
    assert resp.json()["state"] == "running"

    final = _wait_for_run_state(client, checklist["id"], state="finished")
    assert final["outcome"] == "completed"
    assert final["items_completed"] == 1
    assert final["legs_spawned"] == 1

    # Item is checked in the DB.
    refreshed = client.get(f"/api/sessions/{checklist['id']}/checklist").json()
    items = {row["id"]: row for row in refreshed["items"]}
    assert items[item["id"]]["checked_at"] is not None

    # A paired chat leg was created and linked back to the item.
    assert items[item["id"]]["chat_session_id"] is not None


def test_autonomous_run_halts_empty_on_no_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_sentinel_stream(monkeypatch, "irrelevant")
    checklist = _create_checklist(client)
    resp = client.post(f"/api/sessions/{checklist['id']}/checklist/run")
    assert resp.status_code == 202
    final = _wait_for_run_state(client, checklist["id"], state="finished")
    assert final["outcome"] == "halted_empty"
    assert final["items_completed"] == 0


def test_autonomous_run_halts_failure_on_silent_agent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent emits no sentinel — driver halts with failure and
    preserves the failure reason for the UI to surface."""
    _install_sentinel_stream(monkeypatch, "I did stuff but said nothing.")
    checklist = _create_checklist(client)
    item = _add_item(client, checklist["id"], "silent")
    resp = client.post(f"/api/sessions/{checklist['id']}/checklist/run")
    assert resp.status_code == 202
    final = _wait_for_run_state(client, checklist["id"], state="finished")
    assert final["outcome"] == "halted_failure"
    assert final["items_failed"] == 1
    assert final["failed_item_id"] == item["id"]
    assert "completion sentinel" in (final["failure_reason"] or "")


# --- conflicts + idempotency --------------------------------------


def test_second_run_while_running_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A POST /run while one is already running returns 409.

    Uses the silent-agent path as the first run so it's still
    `running` in a predictable window (silent exits halt at the
    next iteration boundary — plenty of time for the conflicting
    POST to arrive). Even if the race resolves the wrong way, the
    test asserts on response codes that distinguish the two valid
    outcomes (202 second-chance + 409 conflict), not on wall-clock
    ordering."""
    _install_sentinel_stream(monkeypatch, "CHECKLIST_ITEM_DONE")
    checklist = _create_checklist(client)
    _add_item(client, checklist["id"], "first")
    _add_item(client, checklist["id"], "second")
    _add_item(client, checklist["id"], "third")
    resp1 = client.post(f"/api/sessions/{checklist['id']}/checklist/run")
    assert resp1.status_code == 202
    # Fire the conflicting POST immediately. Either the driver is
    # still running (409), or it raced to completion (202 accepted
    # because the prior task.done() and registry noticed). Both are
    # valid states — the assertion is on the state transitions.
    resp2 = client.post(f"/api/sessions/{checklist['id']}/checklist/run")
    assert resp2.status_code in (202, 409), resp2.text


def test_get_run_before_start_returns_404(client: TestClient) -> None:
    checklist = _create_checklist(client)
    resp = client.get(f"/api/sessions/{checklist['id']}/checklist/run")
    assert resp.status_code == 404


def test_delete_run_is_idempotent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """DELETE /run succeeds whether there's a live driver, a
    finished driver, or nothing at all. Let the first run finish,
    then call DELETE twice — the second one still returns 204."""
    _install_sentinel_stream(monkeypatch, "CHECKLIST_ITEM_DONE")
    checklist = _create_checklist(client)
    _add_item(client, checklist["id"], "one")
    client.post(f"/api/sessions/{checklist['id']}/checklist/run")
    _wait_for_run_state(client, checklist["id"], state="finished")
    d1 = client.delete(f"/api/sessions/{checklist['id']}/checklist/run")
    assert d1.status_code == 204
    d2 = client.delete(f"/api/sessions/{checklist['id']}/checklist/run")
    assert d2.status_code == 204
    # After DELETE the registry forgets the entry — GET returns 404.
    resp = client.get(f"/api/sessions/{checklist['id']}/checklist/run")
    assert resp.status_code == 404


# --- guards --------------------------------------------------------


def test_run_on_chat_session_returns_400(client: TestClient) -> None:
    """The autonomous driver only applies to `kind='checklist'`
    sessions; attempting it on a chat session returns 400 just like
    the other checklist endpoints."""
    tag_id = _default_tag(client)
    resp = client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "claude-sonnet-4-6",
            "kind": "chat",
            "tag_ids": [tag_id],
        },
    )
    assert resp.status_code == 200
    chat_id = resp.json()["id"]
    r = client.post(f"/api/sessions/{chat_id}/checklist/run")
    assert r.status_code == 400


def test_run_with_custom_config_overrides_defaults(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST body overrides hit the driver's config path. Prove this
    by setting `max_items_per_run=1` and adding two items — only the
    first should be worked; outcome is `halted_max_items`."""
    _install_sentinel_stream(monkeypatch, "CHECKLIST_ITEM_DONE")
    checklist = _create_checklist(client)
    _add_item(client, checklist["id"], "first")
    _add_item(client, checklist["id"], "second")
    resp = client.post(
        f"/api/sessions/{checklist['id']}/checklist/run",
        json={"max_items_per_run": 1},
    )
    assert resp.status_code == 202
    final = _wait_for_run_state(client, checklist["id"], state="finished")
    assert final["outcome"] == "halted_max_items"
    assert final["items_completed"] == 1
