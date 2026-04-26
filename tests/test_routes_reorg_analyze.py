"""Tests for `POST /sessions/{id}/reorg/analyze` — Slice 6 of the
Session Reorg plan (`~/.claude/plans/sparkling-triaging-otter.md`).

Covers:
- 404 / 400 validation branches.
- Heuristic mode happy path (deterministic split on time gap).
- LLM mode disabled by config falls back to heuristic with a `notes`
  advisory.
- LLM mode enabled with a monkeypatched `query_fn` that returns valid
  JSON.
- LLM mode enabled but the query fails → fallback with notes.
- The route is read-only — no message rows move on the source.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite
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


def _create(client: TestClient, **kwargs: Any) -> dict[str, Any]:
    tag_ids = kwargs.pop("tag_ids", None) or [_default_tag(client)]
    body = {
        "working_dir": "/tmp",
        "model": "claude-sonnet-4-6",
        "title": "test session",  # v0.20.6: required at API boundary
        "tag_ids": tag_ids,
        **kwargs,
    }
    resp = client.post("/api/sessions", json=body)
    assert resp.status_code == 200, resp.text
    return dict(resp.json())


def _seed_message(
    db_path: Path,
    session_id: str,
    role: str,
    content: str,
    *,
    created_at: str,
) -> str:
    """Direct DB insert with explicit `created_at` so analyze tests
    can construct the time-gap pattern the heuristic keys off of."""
    msg_id = uuid4().hex

    async def _run() -> None:
        conn = await aiosqlite.connect(str(db_path))
        try:
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.execute(
                "INSERT INTO messages (id, session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (msg_id, session_id, role, content, created_at),
            )
            await conn.commit()
        finally:
            await conn.close()

    asyncio.run(_run())
    return msg_id


def _seed_two_clusters(db_path: Path, session_id: str) -> list[str]:
    """Seed four messages: two early, two ~3h later. Heuristic should
    split into two proposals with the time-gap reason on the boundary."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    stamps = [
        base,
        base + timedelta(minutes=10),
        base + timedelta(hours=3, minutes=10),
        base + timedelta(hours=3, minutes=20),
    ]
    contents = [
        "checklist research first",
        "checklist plumbing follow-up",
        "resume bug investigation",
        "resume bug fix landed",
    ]
    return [
        _seed_message(db_path, session_id, "user", c, created_at=s.isoformat())
        for c, s in zip(contents, stamps, strict=False)
    ]


# ---------- validation branches -------------------------------------


def test_analyze_404_on_missing_session(client: TestClient) -> None:
    resp = client.post(
        "/api/sessions/ghost/reorg/analyze",
        json={"mode": "heuristic"},
    )
    assert resp.status_code == 404


def test_analyze_rejects_checklist_kind(client: TestClient) -> None:
    """Reorg ops are defined over chat-kind sessions; a checklist
    session has no message rows in the conversational sense."""
    resp = client.post(
        "/api/sessions",
        json={
            "working_dir": "/tmp",
            "model": "claude-sonnet-4-6",
            "title": "checklist",
            "tag_ids": [_default_tag(client)],
            "kind": "checklist",
        },
    )
    assert resp.status_code == 200, resp.text
    sid = resp.json()["id"]
    resp = client.post(
        f"/api/sessions/{sid}/reorg/analyze",
        json={"mode": "heuristic"},
    )
    assert resp.status_code == 400
    assert "chat" in resp.json()["detail"]


# ---------- heuristic happy path ------------------------------------


def test_analyze_heuristic_splits_on_time_gap(client: TestClient, tmp_settings: Settings) -> None:
    src = _create(client, title="src")
    ids = _seed_two_clusters(tmp_settings.storage.db_path, src["id"])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/analyze",
        json={"mode": "heuristic"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode_used"] == "heuristic"
    assert body["messages_in"] == 4
    assert len(body["proposals"]) == 2
    # Per-proposal message ordering preserved.
    assert body["proposals"][0]["message_ids"] == ids[:2]
    assert body["proposals"][1]["message_ids"] == ids[2:]
    # Suggested sessions inherit the source's tag.
    src_tags = client.get(f"/api/sessions/{src['id']}/tags").json()
    src_tag_ids = sorted(t["id"] for t in src_tags)
    for prop in body["proposals"]:
        assert sorted(prop["suggested_session"]["tag_ids"]) == src_tag_ids


def test_analyze_does_not_move_any_messages(client: TestClient, tmp_settings: Settings) -> None:
    """Read-only contract: the analyze call must not change message_count."""
    src = _create(client, title="src")
    _seed_two_clusters(tmp_settings.storage.db_path, src["id"])
    before = client.get(f"/api/sessions/{src['id']}").json()["message_count"]
    client.post(
        f"/api/sessions/{src['id']}/reorg/analyze",
        json={"mode": "heuristic"},
    )
    after = client.get(f"/api/sessions/{src['id']}").json()["message_count"]
    assert before == after == 4


# ---------- LLM mode -----------------------------------------------


def test_analyze_llm_mode_disabled_falls_back_to_heuristic(
    client: TestClient, tmp_settings: Settings
) -> None:
    """`enable_llm_reorg_analyze=False` (the default) → heuristic
    mode runs, `mode_used` echoes 'heuristic', `notes` explains
    the fallback."""
    src = _create(client, title="src")
    _seed_two_clusters(tmp_settings.storage.db_path, src["id"])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/analyze",
        json={"mode": "llm"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode_used"] == "heuristic"
    assert "disabled" in body["notes"].lower()


def test_analyze_llm_mode_enabled_uses_fake_query(
    client: TestClient, tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flip the config knob, monkeypatch the SDK call to return JSON,
    and verify the route returns the LLM-shaped proposals."""
    src = _create(client, title="src")
    ids = _seed_two_clusters(tmp_settings.storage.db_path, src["id"])

    # Settings on the running app — the route reads via app.state.
    client.app.state.settings.agent.enable_llm_reorg_analyze = True  # type: ignore[attr-defined]

    fake_response = (
        '{"proposals": ['
        '{"topic": "checklist", "rationale": "early thread",'
        f' "message_ids": ["{ids[0]}", "{ids[1]}"], "title": "Checklist work"}},'
        '{"topic": "resume bug", "rationale": "later thread",'
        f' "message_ids": ["{ids[2]}", "{ids[3]}"], "title": "Resume bug"}}'
        "]}"
    )

    async def fake_query(_messages: list[dict[str, Any]]) -> str:
        return fake_response

    # Patch the SDK driver so the route's call goes to our fake.
    import bearings.db._reorg_analyze as analyzer_module

    real_run = analyzer_module._run_llm_query

    async def patched_run(messages: list[dict[str, Any]], **kwargs: Any) -> str:
        return await fake_query(messages)

    monkeypatch.setattr(analyzer_module, "_run_llm_query", patched_run)

    try:
        resp = client.post(
            f"/api/sessions/{src['id']}/reorg/analyze",
            json={"mode": "llm"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode_used"] == "llm"
        assert body["notes"] == ""
        assert len(body["proposals"]) == 2
        assert body["proposals"][0]["suggested_session"]["title"] == "Checklist work"
    finally:
        # restore for any subsequent test in the module
        monkeypatch.setattr(analyzer_module, "_run_llm_query", real_run)
        client.app.state.settings.agent.enable_llm_reorg_analyze = False  # type: ignore[attr-defined]


def test_analyze_llm_mode_query_failure_falls_back(
    client: TestClient, tmp_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLM enabled but the SDK call raises both attempts → route
    returns heuristic results with a fallback note. The user still
    gets a useful answer, not a 500."""
    src = _create(client, title="src")
    _seed_two_clusters(tmp_settings.storage.db_path, src["id"])

    client.app.state.settings.agent.enable_llm_reorg_analyze = True  # type: ignore[attr-defined]

    import bearings.db._reorg_analyze as analyzer_module

    real_run = analyzer_module._run_llm_query

    async def boom(_messages: list[dict[str, Any]], **kwargs: Any) -> str:
        raise RuntimeError("transient SDK failure")

    monkeypatch.setattr(analyzer_module, "_run_llm_query", boom)

    try:
        resp = client.post(
            f"/api/sessions/{src['id']}/reorg/analyze",
            json={"mode": "llm"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["mode_used"] == "heuristic"
        assert body["notes"]  # populated with a fallback explanation
        assert len(body["proposals"]) == 2  # heuristic still produces splits
    finally:
        monkeypatch.setattr(analyzer_module, "_run_llm_query", real_run)
        client.app.state.settings.agent.enable_llm_reorg_analyze = False  # type: ignore[attr-defined]


def test_analyze_default_mode_is_heuristic(client: TestClient, tmp_settings: Settings) -> None:
    """No `mode` in the body → heuristic by default per the
    ReorgAnalyzeRequest schema. Lets a thin client opt out of the
    LLM path entirely with no extra wiring."""
    src = _create(client, title="src")
    _seed_two_clusters(tmp_settings.storage.db_path, src["id"])

    resp = client.post(
        f"/api/sessions/{src['id']}/reorg/analyze",
        json={},
    )
    assert resp.status_code == 200
    assert resp.json()["mode_used"] == "heuristic"
