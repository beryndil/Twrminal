"""Tests for `POST /sessions/{id}/checklist/suggest_item_titles` —
the bulk title-suggest endpoint that batches the single-session
suggester over a checklist's linked-chat splits.

Plan: `~/.claude/plans/bulk-retitling-checklist.md`. Mirrors the
shape of `test_routes_suggest_title.py` for the single-session
endpoint: validation branches first, then the gated happy / failure
paths under a monkeypatched SDK driver.

Covers:
- 400 when the session is not checklist-kind.
- 404 when the session doesn't exist.
- 503 when `enable_llm_title_suggest=False` (the shipping default).
- 200 with empty items list when the checklist has no linked chats.
- 200 happy path: every linked item carries 3 candidates.
- 200 mixed-success path: one item succeeds, another fails — both
  rows are present, error is inlined per-item.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bearings.config import Settings


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
        "title": kwargs.pop("title", None) or "test session",
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def _create_checklist(client: TestClient) -> dict[str, Any]:
    return _create_session(client, kind="checklist", title="master plan")


def _add_item_with_link(
    client: TestClient, checklist_id: str, label: str, chat_id: str
) -> dict[str, Any]:
    item = client.post(
        f"/api/sessions/{checklist_id}/checklist/items",
        json={"label": label},
    ).json()
    linked = client.post(
        f"/api/sessions/{checklist_id}/checklist/items/{item['id']}/link",
        json={"chat_session_id": chat_id},
    )
    assert linked.status_code == 200, linked.text
    return dict(linked.json())


# ---------- validation branches -------------------------------------


def test_bulk_suggest_404_on_missing_session(client: TestClient) -> None:
    resp = client.post("/api/sessions/ghost/checklist/suggest_item_titles")
    assert resp.status_code == 404


def test_bulk_suggest_400_on_chat_session(client: TestClient) -> None:
    chat = _create_session(client)
    resp = client.post(f"/api/sessions/{chat['id']}/checklist/suggest_item_titles")
    assert resp.status_code == 400
    assert "checklist" in resp.json()["detail"].lower()


def test_bulk_suggest_disabled_returns_503(client: TestClient, tmp_settings: Settings) -> None:
    """Default config has `enable_llm_title_suggest=False` so the
    bulk endpoint must 503 before doing any work."""
    checklist = _create_checklist(client)
    resp = client.post(f"/api/sessions/{checklist['id']}/checklist/suggest_item_titles")
    assert resp.status_code == 503
    assert "enable_llm_title_suggest" in resp.json()["detail"]


# ---------- enabled happy / mixed-success paths ---------------------


def test_bulk_suggest_empty_when_no_linked_chats(
    client: TestClient, tmp_settings: Settings
) -> None:
    """An empty checklist (no items, or items without chat_session_id)
    returns 200 with `items: []` — the gate enables the endpoint, but
    there's simply nothing to suggest for."""
    checklist = _create_checklist(client)
    client.post(
        f"/api/sessions/{checklist['id']}/checklist/items",
        json={"label": "no-link item"},
    )
    client.app.state.settings.agent.enable_llm_title_suggest = True  # type: ignore[attr-defined]
    try:
        resp = client.post(f"/api/sessions/{checklist['id']}/checklist/suggest_item_titles")
        assert resp.status_code == 200
        assert resp.json() == {"items": []}
    finally:
        client.app.state.settings.agent.enable_llm_title_suggest = False  # type: ignore[attr-defined]


def test_bulk_suggest_happy_path_two_items(
    client: TestClient, tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two linked chats → two rows, each carrying three candidates.
    Order matches the checklist's sort_order."""
    checklist = _create_checklist(client)
    chat_a = _create_session(client, title="[Bug] item-1")
    chat_b = _create_session(client, title="[Bug] item-2")
    _add_item_with_link(client, checklist["id"], "Wire foo", chat_a["id"])
    _add_item_with_link(client, checklist["id"], "Wire bar", chat_b["id"])

    client.app.state.settings.agent.enable_llm_title_suggest = True  # type: ignore[attr-defined]
    fake = '{"titles": ["Narrow", "Medium", "Wide"]}'

    import bearings.agent.title_suggester as suggester_module

    real_run = suggester_module._run_query

    async def patched(messages: list[dict[str, Any]], **kwargs: Any) -> str:
        return fake

    monkeypatch.setattr(suggester_module, "_run_query", patched)

    try:
        resp = client.post(f"/api/sessions/{checklist['id']}/checklist/suggest_item_titles")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["items"]) == 2
        for row in body["items"]:
            assert row["candidates"] == ["Narrow", "Medium", "Wide"]
            assert row["error"] is None
            assert row["chat_session_id"] in {chat_a["id"], chat_b["id"]}
    finally:
        monkeypatch.setattr(suggester_module, "_run_query", real_run)
        client.app.state.settings.agent.enable_llm_title_suggest = False  # type: ignore[attr-defined]


def test_bulk_suggest_mixed_success_inlines_errors(
    client: TestClient, tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-item failures don't abort the batch — the failing row gets
    `error` populated, the succeeding row keeps its candidates, and
    the batch as a whole still returns 200."""
    checklist = _create_checklist(client)
    chat_good = _create_session(client, title="[Bug] item-good")
    chat_bad = _create_session(client, title="[Bug] item-bad")
    _add_item_with_link(client, checklist["id"], "Good", chat_good["id"])
    _add_item_with_link(client, checklist["id"], "Bad", chat_bad["id"])

    client.app.state.settings.agent.enable_llm_title_suggest = True  # type: ignore[attr-defined]

    import bearings.agent.title_suggester as suggester_module

    real_run = suggester_module._run_query
    seen: dict[str, int] = {"calls": 0}

    async def selective(messages: list[dict[str, Any]], **kwargs: Any) -> str:
        seen["calls"] += 1
        # First call (good chat) succeeds; second (bad chat) raises.
        if seen["calls"] == 1:
            return '{"titles": ["A", "B", "C"]}'
        raise RuntimeError("transient SDK failure")

    monkeypatch.setattr(suggester_module, "_run_query", selective)

    try:
        resp = client.post(f"/api/sessions/{checklist['id']}/checklist/suggest_item_titles")
        assert resp.status_code == 200, resp.text
        rows = resp.json()["items"]
        assert len(rows) == 2
        succeeded = [r for r in rows if r["error"] is None]
        failed = [r for r in rows if r["error"] is not None]
        assert len(succeeded) == 1
        assert succeeded[0]["candidates"] == ["A", "B", "C"]
        assert len(failed) == 1
        assert failed[0]["candidates"] is None
        assert failed[0]["error"]  # non-empty reason
    finally:
        monkeypatch.setattr(suggester_module, "_run_query", real_run)
        client.app.state.settings.agent.enable_llm_title_suggest = False  # type: ignore[attr-defined]
