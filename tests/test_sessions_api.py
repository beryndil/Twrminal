"""Integration tests for the session-row CRUD endpoints in
``web/routes/sessions.py`` (item 1.7 — auxiliary surface beside the
prompt endpoint)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.config.constants import (
    SESSION_KIND_CHAT,
    SESSION_KIND_CHECKLIST,
)
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app


@pytest.fixture
async def app_and_db(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    db_path = tmp_path / "sapi.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


async def _new_chat(conn: aiosqlite.Connection, title: str = "t") -> str:
    s = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title=title, working_dir="/wd", model="sonnet"
    )
    return s.id


async def test_list_sessions_returns_rows(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    await _new_chat(conn, "a")
    await _new_chat(conn, "b")
    with TestClient(app) as client:
        response = client.get("/api/sessions")
    assert response.status_code == 200
    titles = {row["title"] for row in response.json()}
    assert titles == {"a", "b"}


async def test_list_sessions_filter_by_kind(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    chat = await _new_chat(conn)
    cl = await sessions_db.create(
        conn, kind=SESSION_KIND_CHECKLIST, title="cl", working_dir="/wd", model="sonnet"
    )
    with TestClient(app) as client:
        chats = client.get("/api/sessions", params={"kind": "chat"})
        cls = client.get("/api/sessions", params={"kind": "checklist"})
    assert {row["id"] for row in chats.json()} == {chat}
    assert {row["id"] for row in cls.json()} == {cl.id}


async def test_list_sessions_invalid_kind_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.get("/api/sessions", params={"kind": "bogus"})
    assert response.status_code == 422


async def test_list_sessions_filter_open_only(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    open_id = await _new_chat(conn, "open")
    closed_id = await _new_chat(conn, "closed")
    await sessions_db.close(conn, closed_id)
    with TestClient(app) as client:
        response = client.get("/api/sessions", params={"include_closed": "false"})
    assert {row["id"] for row in response.json()} == {open_id}


async def test_list_sessions_filter_by_tag_ids_or_semantics(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Item 2.2 — wire-shape contract for ``?tag_ids=1&tag_ids=2`` OR filter.

    The sidebar filter UI passes selected tag ids as repeated query
    params; the route must (a) accept the repeated form, and (b) apply
    OR semantics across them. We assert both with a disjoint setup:
    ``?tag_ids=tag1&tag_ids=tag2`` returns sessions tagged with EITHER,
    not the AND-intersection (which would be empty here).
    """
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    tag1 = await tags_db.create(conn, name="bearings/architect")
    tag2 = await tags_db.create(conn, name="bearings/exec")

    a = await _new_chat(conn, "a")
    b = await _new_chat(conn, "b")
    untagged = await _new_chat(conn, "untagged")
    await tags_db.attach(conn, session_id=a, tag_id=tag1.id)
    await tags_db.attach(conn, session_id=b, tag_id=tag2.id)

    with TestClient(app) as client:
        response = client.get(
            "/api/sessions",
            params=[("tag_ids", str(tag1.id)), ("tag_ids", str(tag2.id))],
        )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert ids == {a, b}, "OR semantics — untagged session must be excluded"
    assert untagged not in ids


async def test_list_sessions_no_tag_filter_returns_all(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Omitting ``tag_ids`` applies no tag filter (untagged sessions stay)."""
    app, conn = app_and_db
    a = await _new_chat(conn, "a")
    with TestClient(app) as client:
        response = client.get("/api/sessions")
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {a}


async def test_list_sessions_single_tag_id(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Single ``?tag_ids=N`` works without the OR-list shape."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    tag1 = await tags_db.create(conn, name="bearings/architect")
    a = await _new_chat(conn, "a")
    b = await _new_chat(conn, "b")
    await tags_db.attach(conn, session_id=a, tag_id=tag1.id)

    with TestClient(app) as client:
        response = client.get("/api/sessions", params={"tag_ids": tag1.id})
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert ids == {a}
    assert b not in ids


async def test_get_session_round_trip(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn, "the-title")
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{sid}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == sid
    assert body["title"] == "the-title"


async def test_create_session_minimal(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Happy path — minimal payload returns 201 + Location + a fresh row."""
    app, _ = app_and_db
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "first chat",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "first chat"
    assert body["kind"] == SESSION_KIND_CHAT
    assert body["working_dir"] == "/tmp/wd"
    assert body["model"] == "claude-sonnet-4-5"
    assert body["id"].startswith("ses_")
    assert response.headers["Location"] == f"/api/sessions/{body['id']}"
    # Default fields surface as zeros / nulls per :class:`SessionOut`.
    assert body["message_count"] == 0
    assert body["total_cost_usd"] == 0.0
    assert body["closed_at"] is None


async def test_create_session_with_tags(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """``tag_ids`` populates ``session_tags`` atomically with the row."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    tag_a = await tags_db.create(conn, name="bearings/a")
    tag_b = await tags_db.create(conn, name="bearings/b")
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "tagged",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
        "tag_ids": [tag_a.id, tag_b.id],
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
        assert response.status_code == 201
        sid = response.json()["id"]
        # Round-trip through the per-session tags endpoint to confirm
        # both rows landed.
        tags_response = client.get(f"/api/sessions/{sid}/tags")
    assert tags_response.status_code == 200
    attached = {row["id"] for row in tags_response.json()}
    assert attached == {tag_a.id, tag_b.id}


async def test_create_session_unknown_kind_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    payload = {
        "kind": "bogus",
        "title": "x",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 422
    assert "kind" in response.json()["detail"]


async def test_create_session_unknown_tag_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Bad ``tag_ids`` returns 404 BEFORE the session row is inserted."""
    app, conn = app_and_db
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "x",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
        "tag_ids": [9999],
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 404
    assert "9999" in response.json()["detail"]
    # Verify NO orphan session landed in the table.
    rows = await sessions_db.list_all(conn)
    assert rows == []


async def test_create_session_empty_title_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 422


async def test_create_session_extra_field_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """``extra='forbid'`` keeps the wire shape pinned to the documented fields."""
    app, _ = app_and_db
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "x",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
        "id": "ses_caller_chose_this",  # Not allowed.
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 422


async def test_get_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.get("/api/sessions/ses_missing")
    assert response.status_code == 404


async def test_patch_session_title(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn, "old")
    with TestClient(app) as client:
        response = client.patch(f"/api/sessions/{sid}", json={"title": "new"})
    assert response.status_code == 200
    assert response.json()["title"] == "new"


async def test_patch_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.patch("/api/sessions/ses_missing", json={"title": "x"})
    assert response.status_code == 404


async def test_patch_session_empty_title_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.patch(f"/api/sessions/{sid}", json={"title": ""})
    assert response.status_code == 422


async def test_close_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/close")
    assert response.status_code == 200
    assert response.json()["closed_at"] is not None


async def test_patch_model_swap(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Happy path — PATCH /model updates the row's model column."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.patch(f"/api/sessions/{sid}/model", json={"model": "opus"})
    assert response.status_code == 200
    assert response.json()["model"] == "opus"
    refreshed = await sessions_db.get(conn, sid)
    assert refreshed is not None
    assert refreshed.model == "opus"


async def test_patch_model_unknown_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.patch(f"/api/sessions/{sid}/model", json={"model": "bogus-model-99"})
    assert response.status_code == 422
    refreshed = await sessions_db.get(conn, sid)
    assert refreshed is not None
    assert refreshed.model == "sonnet"


async def test_patch_model_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.patch("/api/sessions/ses_missing/model", json={"model": "opus"})
    assert response.status_code == 404


async def test_patch_model_recycles_runner_supervisor(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """A successful PATCH /model recycles the live SDK supervisor so
    the next prompt respawns the subprocess with ``--model <new>``.
    Spies on the registry's ``recycle`` so the test does not have to
    spawn a real subprocess to observe the behavior."""
    from bearings.web.runner_factory import InProcessRunnerRegistry

    app, conn = app_and_db
    factory = app.state.runner_factory
    assert isinstance(factory, InProcessRunnerRegistry)
    sid = await _new_chat(conn)

    recycled: list[str] = []
    original_recycle = factory.recycle

    async def spy_recycle(session_id: str) -> bool:
        recycled.append(session_id)
        return await original_recycle(session_id)

    factory.recycle = spy_recycle  # type: ignore[method-assign]
    try:
        with TestClient(app) as client:
            response = client.patch(f"/api/sessions/{sid}/model", json={"model": "opus"})
        assert response.status_code == 200
        assert recycled == [sid]
    finally:
        factory.recycle = original_recycle  # type: ignore[method-assign]


async def test_patch_model_404_skips_recycle(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """A 404 on PATCH /model must NOT call recycle — there is no
    session to recycle and recycle on a phantom id would race with
    a future genuine session creation reusing the same id."""
    from bearings.web.runner_factory import InProcessRunnerRegistry

    app, _ = app_and_db
    factory = app.state.runner_factory
    assert isinstance(factory, InProcessRunnerRegistry)

    recycled: list[str] = []
    original_recycle = factory.recycle

    async def spy_recycle(session_id: str) -> bool:
        recycled.append(session_id)
        return await original_recycle(session_id)

    factory.recycle = spy_recycle  # type: ignore[method-assign]
    try:
        with TestClient(app) as client:
            response = client.patch("/api/sessions/ses_missing/model", json={"model": "opus"})
        assert response.status_code == 404
        assert recycled == []
    finally:
        factory.recycle = original_recycle  # type: ignore[method-assign]


async def test_patch_permission_mode_swap(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Happy path — PATCH /permission_mode updates the row's permission_mode column."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.patch(
            f"/api/sessions/{sid}/permission_mode",
            json={"permission_mode": "bypassPermissions"},
        )
    assert response.status_code == 200
    assert response.json()["permission_mode"] == "bypassPermissions"
    refreshed = await sessions_db.get(conn, sid)
    assert refreshed is not None
    assert refreshed.permission_mode == "bypassPermissions"


async def test_patch_permission_mode_clear(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """``None`` payload clears permission_mode (runner uses profile default)."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        # First set a mode ...
        client.patch(
            f"/api/sessions/{sid}/permission_mode",
            json={"permission_mode": "acceptEdits"},
        )
        # ... then clear it.
        response = client.patch(
            f"/api/sessions/{sid}/permission_mode",
            json={"permission_mode": None},
        )
    assert response.status_code == 200
    assert response.json()["permission_mode"] is None
    refreshed = await sessions_db.get(conn, sid)
    assert refreshed is not None
    assert refreshed.permission_mode is None


async def test_patch_permission_mode_unknown_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.patch(
            f"/api/sessions/{sid}/permission_mode",
            json={"permission_mode": "bogus-mode"},
        )
    assert response.status_code == 422
    refreshed = await sessions_db.get(conn, sid)
    assert refreshed is not None
    assert refreshed.permission_mode is None


async def test_patch_permission_mode_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.patch(
            "/api/sessions/ses_missing/permission_mode",
            json={"permission_mode": "default"},
        )
    assert response.status_code == 404


async def test_regenerate_no_messages_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Freshly-created sessions with no user messages 404 on regenerate."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate")
    assert response.status_code == 404
    assert "regenerate" in response.json()["detail"]


async def test_regenerate_unknown_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_missing/regenerate")
    assert response.status_code == 404


async def test_regenerate_replays_latest_user_message(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """With a user message in history the regenerate endpoint queues a replay."""
    from bearings.db import messages as messages_db

    app, conn = app_and_db
    sid = await _new_chat(conn)
    await messages_db.insert_user(conn, session_id=sid, content="first prompt")
    await messages_db.insert_user(conn, session_id=sid, content="latest prompt")
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate")
    assert response.status_code == 202
    body = response.json()
    assert body["queued"] is True
    assert body["session_id"] == sid
    assert response.headers["Location"] == f"/api/sessions/{sid}"


async def test_regenerate_closed_session_409(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    from bearings.db import messages as messages_db

    app, conn = app_and_db
    sid = await _new_chat(conn)
    await messages_db.insert_user(conn, session_id=sid, content="hello")
    await sessions_db.close(conn, sid)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate")
    assert response.status_code == 409


async def test_close_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_missing/close")
    assert response.status_code == 404


async def test_reopen_session_round_trip(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    await sessions_db.close(conn, sid)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/reopen")
    assert response.status_code == 200
    assert response.json()["closed_at"] is None


async def test_reopen_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_missing/reopen")
    assert response.status_code == 404


async def test_delete_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.delete(f"/api/sessions/{sid}")
    assert response.status_code == 204
    assert await sessions_db.get(conn, sid) is None


async def test_delete_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.delete("/api/sessions/ses_missing")
    assert response.status_code == 404


# ---- stop endpoint --------------------------------------------------------


async def test_stop_session_no_runner_204(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Stop on a session with no live runner returns 204 (no-op — turn not running)."""
    from bearings.web.runner_factory import InProcessRunnerRegistry

    app, conn = app_and_db
    sid = await _new_chat(conn)
    # Wire a registry with no spawned supervisor (session_setup=None).
    registry = InProcessRunnerRegistry()
    app.state.runner_factory = registry
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/stop")
    assert response.status_code == 204


async def test_stop_session_with_runner_calls_request_stop(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Stop on a session whose runner is registered calls runner.request_stop()."""
    from bearings.agent.runner import SessionRunner
    from bearings.web.runner_factory import InProcessRunnerRegistry

    app, conn = app_and_db
    sid = await _new_chat(conn)
    registry = InProcessRunnerRegistry()
    runner = SessionRunner(sid)
    # Manually register the runner without spawning a supervisor.
    registry._runners[sid] = runner
    app.state.runner_factory = registry
    assert not runner.stop_event.is_set()
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/stop")
    assert response.status_code == 204
    assert runner.stop_event.is_set()


async def test_stop_session_404_unknown(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Stop on an unknown session id returns 404."""
    from bearings.web.runner_factory import InProcessRunnerRegistry

    app, _ = app_and_db
    app.state.runner_factory = InProcessRunnerRegistry()
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_missing/stop")
    assert response.status_code == 404


async def test_stop_session_503_without_registry(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Stop returns 503 when a non-registry runner factory is wired."""
    from bearings.agent.runner import SessionRunner

    app, conn = app_and_db
    sid = await _new_chat(conn)

    # Wire a plain RunnerFactory Protocol impl (not InProcessRunnerRegistry).
    async def plain_factory(session_id: str) -> SessionRunner:
        return SessionRunner(session_id)

    app.state.runner_factory = plain_factory
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/stop")
    assert response.status_code == 503
