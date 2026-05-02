"""HTTP surface tests for the spawn classify endpoint.

``POST /api/sessions/{id}/spawn_from_reply/{message_id}/classify``

Coverage:
  - 404 on unknown session
  - 404 on unknown message
  - 400 on message not in session
  - 400 on user-role message
  - disabled classifier → graceful single_chat fallback (200)
  - enabled classifier + good LLM response → 200 with correct shape
  - enabled classifier + bad LLM response → 200 with single_chat fallback
  - checklist shape round-trips correctly
  - multi_chat shape round-trips correctly
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from bearings.api.models.spawn_classify import SpawnShape

# ---------------------------------------------------------------------------
# Helpers (mirrors test_spawn_from_reply.py)
# ---------------------------------------------------------------------------


def _seed(
    client: TestClient,
    *,
    title: str = "parent",
    assistant_content: str = "This is the assistant reply.",
) -> dict[str, Any]:
    payload = {
        "session": {
            "working_dir": "/tmp/classify-cwd",
            "model": "claude-haiku-4-5",
            "title": title,
        },
        "messages": [
            {
                "id": "u1",
                "role": "user",
                "content": "do the thing",
                "created_at": "2026-04-30T10:00:00Z",
            },
            {
                "id": "a1",
                "role": "assistant",
                "content": assistant_content,
                "created_at": "2026-04-30T10:00:01Z",
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


def _assistant_id(session: dict[str, Any]) -> str:
    for m in session["_messages"]:
        if m["role"] == "assistant":
            return str(m["id"])
    raise AssertionError("no assistant message in seeded session")


def _user_id(session: dict[str, Any]) -> str:
    for m in session["_messages"]:
        if m["role"] == "user":
            return str(m["id"])
    raise AssertionError("no user message in seeded session")


def _url(session_id: str, message_id: str) -> str:
    return f"/api/sessions/{session_id}/spawn_from_reply/{message_id}/classify"


# ---------------------------------------------------------------------------
# 404 / 400 gates
# ---------------------------------------------------------------------------


def test_classify_404_unknown_session(client: TestClient) -> None:
    resp = client.post(_url("no-such-session", "no-such-message"))
    assert resp.status_code == 404


def test_classify_404_unknown_message(client: TestClient) -> None:
    parent = _seed(client)
    resp = client.post(_url(parent["id"], "no-such-message"))
    assert resp.status_code == 404


def test_classify_400_wrong_session(client: TestClient) -> None:
    """Message id exists in a different session → 400."""
    parent = _seed(client)
    other = _seed(client, title="other")
    other_msg_id = _assistant_id(other)
    resp = client.post(_url(parent["id"], other_msg_id))
    assert resp.status_code == 400
    assert "does not belong" in resp.json()["detail"]


def test_classify_400_user_message(client: TestClient) -> None:
    """Classifying a user-role message is rejected."""
    parent = _seed(client)
    user_msg_id = _user_id(parent)
    resp = client.post(_url(parent["id"], user_msg_id))
    assert resp.status_code == 400
    assert "assistant" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Disabled classifier → fallback
# ---------------------------------------------------------------------------


def test_classify_disabled_returns_single_chat_fallback(client: TestClient) -> None:
    """When enable_llm_spawn_classifier is False (the default in tests),
    the endpoint returns 200 with shape=single_chat and a
    'classifier disabled or failed' reason — no LLM call made."""
    parent = _seed(client, assistant_content="Hello from the assistant.")
    msg_id = _assistant_id(parent)
    resp = client.post(_url(parent["id"], msg_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shape"] == SpawnShape.single_chat
    assert "classifier disabled or failed" in body["reason"]
    assert body["suggested_single"] is not None
    assert body["suggested_multi"] is None
    assert body["suggested_checklist"] is None


# ---------------------------------------------------------------------------
# Enabled classifier — shapes
# ---------------------------------------------------------------------------


@pytest.fixture()
def enabled_settings(app: Any) -> Any:  # type: ignore[type-arg]
    """Temporarily enable the spawn classifier on the test app."""
    settings = app.state.settings
    original = settings.agent.enable_llm_spawn_classifier
    settings.agent.enable_llm_spawn_classifier = True
    yield settings
    settings.agent.enable_llm_spawn_classifier = original


def _single_json(title: str = "My title", desc: str = "My desc") -> str:
    return (
        f'{{"shape":"single_chat","reason":"one thing",'
        f'"suggested":{{"title":"{title}","description":"{desc}"}}}}'
    )


def _multi_json() -> str:
    return (
        '{"shape":"multi_chat","reason":"options",'
        '"suggested":[{"title":"A","description":"da"},{"title":"B","description":"db"}]}'
    )


def _checklist_json() -> str:
    return (
        '{"shape":"checklist","reason":"steps",'
        '"suggested":[{"label":"Step 1","notes":"n1"},{"label":"Step 2","notes":"n2"}]}'
    )


def test_classify_enabled_single_chat(client: TestClient, enabled_settings: Any) -> None:
    parent = _seed(client)
    msg_id = _assistant_id(parent)

    async def fake_query(_reply: str) -> str:
        return _single_json()

    with patch(
        "bearings.agent.spawn_classifier._run_query",
        new=AsyncMock(return_value=_single_json()),
    ):
        resp = client.post(_url(parent["id"], msg_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shape"] == "single_chat"
    assert body["suggested_single"] is not None
    assert body["suggested_single"]["title"] == "My title"


def test_classify_enabled_multi_chat(client: TestClient, enabled_settings: Any) -> None:
    parent = _seed(client)
    msg_id = _assistant_id(parent)

    with patch(
        "bearings.agent.spawn_classifier._run_query",
        new=AsyncMock(return_value=_multi_json()),
    ):
        resp = client.post(_url(parent["id"], msg_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shape"] == "multi_chat"
    assert body["suggested_multi"] is not None
    assert len(body["suggested_multi"]) == 2
    assert body["suggested_multi"][0]["title"] == "A"


def test_classify_enabled_checklist(client: TestClient, enabled_settings: Any) -> None:
    parent = _seed(client)
    msg_id = _assistant_id(parent)

    with patch(
        "bearings.agent.spawn_classifier._run_query",
        new=AsyncMock(return_value=_checklist_json()),
    ):
        resp = client.post(_url(parent["id"], msg_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shape"] == "checklist"
    assert body["suggested_checklist"] is not None
    assert body["suggested_checklist"][0]["label"] == "Step 1"
    assert body["suggested_checklist"][1]["notes"] == "n2"


def test_classify_enabled_bad_llm_falls_back(client: TestClient, enabled_settings: Any) -> None:
    """Bad LLM JSON → classifier falls back; route still returns 200."""
    parent = _seed(client)
    msg_id = _assistant_id(parent)

    with patch(
        "bearings.agent.spawn_classifier._run_query",
        new=AsyncMock(return_value="not json"),
    ):
        resp = client.post(_url(parent["id"], msg_id))

    assert resp.status_code == 200
    body = resp.json()
    assert body["shape"] == "single_chat"
    assert "classifier disabled or failed" in body["reason"]
