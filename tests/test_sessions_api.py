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
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.db.messages import Message
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


# ---------------------------------------------------------------------------
# Tag-class cardinality + three-section filter — tag-class feature
# ---------------------------------------------------------------------------


async def test_create_session_two_project_tags_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """API enforces ≤1 project tag per session on bulk replace."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    a = await tags_db.create(conn, name="proj-a", class_="project")
    b = await tags_db.create(conn, name="proj-b", class_="project")
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "two-projects",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
        "tag_ids": [a.id, b.id],
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 422
    assert "project" in response.json()["detail"]
    # No orphan session lands.
    assert await sessions_db.list_all(conn) == []


async def test_create_session_two_severity_tags_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """API enforces ≤1 severity tag per session on bulk replace."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    low = await tags_db.create(conn, name="low", class_="severity")
    high = await tags_db.create(conn, name="high", class_="severity")
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "two-severities",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
        "tag_ids": [low.id, high.id],
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 422
    assert "severity" in response.json()["detail"]


async def test_create_session_one_project_one_severity_ok(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """One of each class plus general tags is the canonical valid shape."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    proj = await tags_db.create(conn, name="bearings", class_="project")
    sev = await tags_db.create(conn, name="urgent", class_="severity")
    gen = await tags_db.create(conn, name="freeform")
    payload = {
        "kind": SESSION_KIND_CHAT,
        "title": "ok-shape",
        "working_dir": "/tmp/wd",
        "model": "claude-sonnet-4-5",
        "tag_ids": [proj.id, sev.id, gen.id],
    }
    with TestClient(app) as client:
        response = client.post("/api/sessions", json=payload)
    assert response.status_code == 201


async def test_list_sessions_three_section_filter_and_across_or_within(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """OR within a section; AND across sections."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    proj_a = await tags_db.create(conn, name="proj-a", class_="project")
    proj_b = await tags_db.create(conn, name="proj-b", class_="project")
    sev_high = await tags_db.create(conn, name="high", class_="severity")
    sev_low = await tags_db.create(conn, name="low", class_="severity")
    gen = await tags_db.create(conn, name="gen")

    # Sessions:
    #   alpha: proj-a + sev-high
    #   beta:  proj-b + sev-high + gen
    #   gamma: proj-a + sev-low
    #   delta: proj-b only (no severity)
    alpha = await _new_chat(conn, "alpha")
    beta = await _new_chat(conn, "beta")
    gamma = await _new_chat(conn, "gamma")
    delta = await _new_chat(conn, "delta")
    await tags_db.attach(conn, session_id=alpha, tag_id=proj_a.id)
    await tags_db.attach(conn, session_id=alpha, tag_id=sev_high.id)
    await tags_db.attach(conn, session_id=beta, tag_id=proj_b.id)
    await tags_db.attach(conn, session_id=beta, tag_id=sev_high.id)
    await tags_db.attach(conn, session_id=beta, tag_id=gen.id)
    await tags_db.attach(conn, session_id=gamma, tag_id=proj_a.id)
    await tags_db.attach(conn, session_id=gamma, tag_id=sev_low.id)
    await tags_db.attach(conn, session_id=delta, tag_id=proj_b.id)

    with TestClient(app) as client:
        # AND across (project IN {a,b}) AND (severity IN {high}).
        # → alpha + beta (both project-matching with high severity).
        response = client.get(
            "/api/sessions",
            params=[
                ("tag_ids_project", str(proj_a.id)),
                ("tag_ids_project", str(proj_b.id)),
                ("tag_ids_severity", str(sev_high.id)),
            ],
        )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert ids == {alpha, beta}, "OR within project + AND with severity"


async def test_list_sessions_empty_severity_filter_returns_all_severities(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Empty section ≠ "exclude everything" — it means "no constraint."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    proj = await tags_db.create(conn, name="proj-a", class_="project")
    sev = await tags_db.create(conn, name="high", class_="severity")
    a = await _new_chat(conn, "a")
    b = await _new_chat(conn, "b")
    await tags_db.attach(conn, session_id=a, tag_id=proj.id)
    await tags_db.attach(conn, session_id=a, tag_id=sev.id)
    await tags_db.attach(conn, session_id=b, tag_id=proj.id)

    with TestClient(app) as client:
        # Project filter set, severity omitted → both sessions returned.
        response = client.get(
            "/api/sessions",
            params=[("tag_ids_project", str(proj.id))],
        )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert ids == {a, b}, "omitting a section must not exclude rows"


async def test_list_sessions_legacy_session_with_no_project_remains_listable(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """No project tag is fine — cardinality is ≤1, not =1."""
    app, conn = app_and_db
    sid = await _new_chat(conn, "untagged")
    with TestClient(app) as client:
        response = client.get("/api/sessions")
    assert response.status_code == 200
    assert sid in {row["id"] for row in response.json()}


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


async def test_patch_session_two_project_tags_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """PATCH with 2 project-class tags returns 422 (cardinality guard)."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    sid = await _new_chat(conn)
    a = await tags_db.create(conn, name="proj-a", class_="project")
    b = await tags_db.create(conn, name="proj-b", class_="project")
    with TestClient(app) as client:
        response = client.patch(f"/api/sessions/{sid}", json={"tag_ids": [a.id, b.id]})
    assert response.status_code == 422
    assert "project" in response.json()["detail"]


async def test_patch_session_two_severity_tags_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """PATCH with 2 severity-class tags returns 422 (cardinality guard)."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    sid = await _new_chat(conn)
    low = await tags_db.create(conn, name="low", class_="severity")
    high = await tags_db.create(conn, name="high", class_="severity")
    with TestClient(app) as client:
        response = client.patch(f"/api/sessions/{sid}", json={"tag_ids": [low.id, high.id]})
    assert response.status_code == 422
    assert "severity" in response.json()["detail"]


async def test_patch_session_valid_mixed_tags_200(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """PATCH with ≤1 project + ≤1 severity + general tags returns 200 and persists."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    sid = await _new_chat(conn)
    proj = await tags_db.create(conn, name="bearings", class_="project")
    sev = await tags_db.create(conn, name="urgent", class_="severity")
    gen = await tags_db.create(conn, name="freeform")
    with TestClient(app) as client:
        response = client.patch(
            f"/api/sessions/{sid}",
            json={"tag_ids": [proj.id, sev.id, gen.id]},
        )
    assert response.status_code == 200
    attached = await tags_db.list_for_session(conn, sid)
    assert {t.id for t in attached} == {proj.id, sev.id, gen.id}


async def test_close_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Chat sessions close successfully and get a closed_at timestamp."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/close")
    assert response.status_code == 200
    assert response.json()["closed_at"] is not None


async def test_close_checklist_session_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Checklist sessions must not be closeable — 422 with explanatory detail.

    Closing a checklist session would produce the inconsistent
    ``(kind='checklist', closed_at IS NOT NULL)`` row state that the
    verifier identified in feature-1-004.  The kind guard in
    ``close_session`` must reject the request before writing anything.
    """
    app, conn = app_and_db
    checklist_session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHECKLIST,
        title="my-checklist",
        working_dir="/wd",
        model="sonnet",
    )
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{checklist_session.id}/close")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "checklist" in detail
    # Row must remain unmodified — closed_at stays NULL.
    row = await sessions_db.get(conn, checklist_session.id)
    assert row is not None
    assert row.closed_at is None


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


async def _insert_assistant_row(
    conn: aiosqlite.Connection,
    session_id: str,
    content: str = "reply",
) -> Message:
    """Minimal assistant-role row for route-level tests."""
    from bearings.db.messages import insert_assistant

    return await insert_assistant(
        conn,
        session_id=session_id,
        content=content,
        executor_model="sonnet",
        advisor_model=None,
        effort_level="med",
        routing_source="default",
        routing_reason="default routing",
        matched_rule_id=None,
        evaluated_rules=[],
        executor_input_tokens=None,
        executor_output_tokens=None,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=0,
        cache_read_tokens=None,
    )


async def test_regenerate_from_unknown_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Unknown session_id returns 404."""
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_missing/regenerate_from/msg_x")
    assert response.status_code == 404


async def test_regenerate_from_unknown_message_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Session exists but message_id is not in it — 404."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate_from/msg_missing")
    assert response.status_code == 404
    assert "no message matches" in response.json()["detail"]


async def test_regenerate_from_non_assistant_message_422(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Named message is a user turn — 422."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    user_msg = await messages_db.insert_user(conn, session_id=sid, content="hello")
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate_from/{user_msg.id}")
    assert response.status_code == 422
    assert "not an assistant turn" in response.json()["detail"]


async def test_regenerate_from_no_preceding_user_message_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Assistant turn exists but has no preceding user message — 404."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    # Insert an orphan assistant row (no prior user message in this session).
    asst = await _insert_assistant_row(conn, sid, "orphan")
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate_from/{asst.id}")
    assert response.status_code == 404
    assert "no user message precedes" in response.json()["detail"]


async def test_regenerate_from_truncates_and_requeues(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Truncation matches the pivot; the pivot user message is re-queued."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    pivot_user = await messages_db.insert_user(conn, session_id=sid, content="pivot prompt")
    asst = await _insert_assistant_row(conn, sid, "first reply")
    await messages_db.insert_user(conn, session_id=sid, content="follow-up")
    await _insert_assistant_row(conn, sid, "second reply")

    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate_from/{asst.id}")

    assert response.status_code == 202
    body = response.json()
    assert body["queued"] is True
    assert body["session_id"] == sid
    assert response.headers["Location"] == f"/api/sessions/{sid}"

    # Only the pivot user message should remain in the DB (plus the
    # re-queued user message inserted by dispatch_prompt).
    remaining = await messages_db.list_for_session(conn, sid)
    # The pivot user message stays; rows after it are gone before re-dispatch.
    remaining_ids = {m.id for m in remaining}
    assert pivot_user.id in remaining_ids
    assert asst.id not in remaining_ids


async def test_regenerate_from_closed_session_409(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Closed sessions reject via 409."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    pivot_user = await messages_db.insert_user(conn, session_id=sid, content="hello")
    asst = await _insert_assistant_row(conn, sid, "reply")
    await sessions_db.close(conn, sid)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/regenerate_from/{asst.id}")
    assert response.status_code == 409
    # pivot_user is referenced but not used beyond setup — keep variable for clarity.
    _ = pivot_user


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


async def test_mark_session_viewed_stamps_last_viewed_at(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """POST /viewed stamps last_viewed_at on the row and returns 200."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    row_before = await sessions_db.get(conn, sid)
    assert row_before is not None
    assert row_before.last_viewed_at is None
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{sid}/viewed")
    assert response.status_code == 200
    body = response.json()
    assert body["last_viewed_at"] is not None
    # DB row also reflects the stamp.
    row_after = await sessions_db.get(conn, sid)
    assert row_after is not None
    assert row_after.last_viewed_at is not None


async def test_mark_session_viewed_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_missing/viewed")
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


# ---------------------------------------------------------------------------
# GET /api/sessions/{id}/tokens — token totals hydration (gap-cycle-13-003)
# ---------------------------------------------------------------------------


async def _insert_assistant_with_tokens(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    executor_input_tokens: int | None,
    executor_output_tokens: int | None,
    cache_read_tokens: int | None,
) -> Message:
    """Insert an assistant row carrying the given token columns."""
    from bearings.db.messages import insert_assistant

    return await insert_assistant(
        conn,
        session_id=session_id,
        content="reply",
        executor_model="sonnet",
        advisor_model=None,
        effort_level="med",
        routing_source="default",
        routing_reason="default",
        matched_rule_id=None,
        evaluated_rules=[],
        executor_input_tokens=executor_input_tokens,
        executor_output_tokens=executor_output_tokens,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=0,
        cache_read_tokens=cache_read_tokens,
    )


async def test_get_tokens_unknown_session_404(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Missing session_id returns 404."""
    app, _ = app_and_db
    with TestClient(app) as client:
        response = client.get("/api/sessions/ses_missing/tokens")
    assert response.status_code == 404


async def test_get_tokens_session_with_no_turns_returns_zeros(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """A session whose runner has never started returns all-zero totals.

    Covers the AC: "tokens retrievable for a session whose runner has
    never started in this process."
    """
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{sid}/tokens")
    assert response.status_code == 200
    body = response.json()
    assert body == {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


async def test_get_tokens_aggregates_assistant_rows(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Token totals are summed across multiple assistant rows."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    await _insert_assistant_with_tokens(
        conn,
        sid,
        executor_input_tokens=100,
        executor_output_tokens=50,
        cache_read_tokens=200,
    )
    await _insert_assistant_with_tokens(
        conn,
        sid,
        executor_input_tokens=300,
        executor_output_tokens=75,
        cache_read_tokens=None,  # NULL → treated as 0
    )
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{sid}/tokens")
    assert response.status_code == 200
    body = response.json()
    assert body["input"] == 400
    assert body["output"] == 125
    assert body["cache_read"] == 200
    assert body["cache_creation"] == 0  # no column in v18 schema


async def test_get_tokens_null_fields_treated_as_zero(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Rows with NULL token columns contribute 0 to the aggregate.

    Covers the AC: "cache_creation summed correctly when present" —
    NULL cache_read_tokens is treated as 0, and cache_creation is
    always 0 in v18.
    """
    app, conn = app_and_db
    sid = await _new_chat(conn)
    await _insert_assistant_with_tokens(
        conn,
        sid,
        executor_input_tokens=None,
        executor_output_tokens=None,
        cache_read_tokens=None,
    )
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{sid}/tokens")
    assert response.status_code == 200
    body = response.json()
    assert body == {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


async def test_get_tokens_user_rows_excluded(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """User-role messages are not included in the aggregate."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    # Insert a user row (its executor_input_tokens column is NULL — but
    # even if it weren't, user rows should be excluded from the SUM).
    await messages_db.insert_user(conn, session_id=sid, content="hello")
    # One assistant row with known tokens.
    await _insert_assistant_with_tokens(
        conn,
        sid,
        executor_input_tokens=10,
        executor_output_tokens=5,
        cache_read_tokens=20,
    )
    with TestClient(app) as client:
        response = client.get(f"/api/sessions/{sid}/tokens")
    assert response.status_code == 200
    body = response.json()
    assert body["input"] == 10
    assert body["output"] == 5
    assert body["cache_read"] == 20


# ---------------------------------------------------------------------------
# severity_none filter — gap-cycle-18-003
# ---------------------------------------------------------------------------


async def test_list_sessions_severity_none_returns_unseveritied(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """``?severity_none=true`` returns sessions with no severity-class tag."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    sev = await tags_db.create(conn, name="high", class_="severity")

    has_sev = await _new_chat(conn, "has-severity")
    await tags_db.attach(conn, session_id=has_sev, tag_id=sev.id)

    no_sev = await _new_chat(conn, "no-severity")

    with TestClient(app) as client:
        response = client.get("/api/sessions", params={"severity_none": "true"})
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert no_sev in ids
    assert has_sev not in ids


async def test_list_sessions_severity_none_or_with_tag_ids_severity(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Combining ``severity_none=true`` with ``tag_ids_severity`` applies OR."""
    from bearings.db import tags as tags_db

    app, conn = app_and_db
    sev_high = await tags_db.create(conn, name="high", class_="severity")
    sev_low = await tags_db.create(conn, name="low", class_="severity")

    has_high = await _new_chat(conn, "has-high")
    await tags_db.attach(conn, session_id=has_high, tag_id=sev_high.id)

    has_low = await _new_chat(conn, "has-low")
    await tags_db.attach(conn, session_id=has_low, tag_id=sev_low.id)

    no_sev = await _new_chat(conn, "no-severity")

    with TestClient(app) as client:
        response = client.get(
            "/api/sessions",
            params=[("severity_none", "true"), ("tag_ids_severity", str(sev_high.id))],
        )
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    # OR: sessions with no severity OR sessions tagged high.
    assert ids == {no_sev, has_high}
    assert has_low not in ids
