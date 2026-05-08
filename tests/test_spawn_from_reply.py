"""Integration tests for ``POST /api/sessions/{parent}/spawn_from_reply/{msg}``.

Covers gap-cycle-03-007 acceptance criteria:

* spawn idempotency — same session id returned on re-click
* quoted seed body matches the pivot message
* 404 on missing parent session or missing/mismatched message
* 422 on non-assistant pivot message
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.config.constants import SESSION_KIND_CHAT, SPAWN_FROM_REPLY_QUOTE_PREFIX
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app


@pytest.fixture
async def app_and_conn(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    db_path = tmp_path / "sfr-api.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


async def _make_parent_with_assistant_message(
    conn: aiosqlite.Connection,
) -> tuple[str, str]:
    """Create a chat session with one assistant message; return (session_id, message_id)."""
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="Parent session",
        working_dir="/some/dir",
        model="sonnet",
    )
    msg = await messages_db.insert_assistant(
        conn,
        session_id=session.id,
        content="Hello from the assistant",
        executor_model="sonnet",
        advisor_model=None,
        effort_level="auto",
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
    return session.id, msg.id


# ---------------------------------------------------------------------------
# Happy-path: first spawn → 201, idempotent re-spawn → 200
# ---------------------------------------------------------------------------


async def test_spawn_from_reply_201_on_first_call(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_conn
    parent_id, msg_id = await _make_parent_with_assistant_message(conn)
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{parent_id}/spawn_from_reply/{msg_id}")
    assert response.status_code == 201
    body = response.json()
    assert body["chat_session_id"].startswith("ses_")
    assert body["parent_session_id"] == parent_id
    assert body["pivot_message_id"] == msg_id
    assert body["created"] is True


async def test_spawn_from_reply_200_on_idempotent_re_call(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_conn
    parent_id, msg_id = await _make_parent_with_assistant_message(conn)
    with TestClient(app) as client:
        first = client.post(f"/api/sessions/{parent_id}/spawn_from_reply/{msg_id}")
        second = client.post(f"/api/sessions/{parent_id}/spawn_from_reply/{msg_id}")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["chat_session_id"] == first.json()["chat_session_id"]
    assert second.json()["created"] is False


async def test_seed_body_is_blockquote_of_pivot(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """The first user message in the spawned chat must be a quote of the pivot."""
    app, conn = app_and_conn
    parent_id, msg_id = await _make_parent_with_assistant_message(conn)
    with TestClient(app) as client:
        resp = client.post(f"/api/sessions/{parent_id}/spawn_from_reply/{msg_id}")
    assert resp.status_code == 201
    chat_session_id = resp.json()["chat_session_id"]

    # Fetch the messages of the spawned chat and verify the seed.
    pivot_msg = await messages_db.get(conn, msg_id)
    assert pivot_msg is not None
    msgs = await messages_db.list_for_session(conn, chat_session_id)
    assert len(msgs) == 1
    seed = msgs[0]
    assert seed.role == "user"
    expected_lines = pivot_msg.content.rstrip().splitlines() or [""]
    expected = "\n".join(f"{SPAWN_FROM_REPLY_QUOTE_PREFIX}{line}" for line in expected_lines)
    assert seed.content == expected


async def test_spawned_session_inherits_parent_working_dir_and_model(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_conn
    parent_id, msg_id = await _make_parent_with_assistant_message(conn)
    parent = await sessions_db.get(conn, parent_id)
    assert parent is not None
    with TestClient(app) as client:
        resp = client.post(f"/api/sessions/{parent_id}/spawn_from_reply/{msg_id}")
    assert resp.status_code == 201
    body = resp.json()
    assert body["working_dir"] == parent.working_dir
    assert body["model"] == parent.model


# ---------------------------------------------------------------------------
# 404 paths
# ---------------------------------------------------------------------------


async def test_spawn_from_reply_404_on_missing_parent(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _conn = app_and_conn
    with TestClient(app) as client:
        response = client.post("/api/sessions/ses_nonexistent/spawn_from_reply/msg_nonexistent")
    assert response.status_code == 404


async def test_spawn_from_reply_404_on_missing_message(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_conn
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="S",
        working_dir="/d",
        model="sonnet",
    )
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{session.id}/spawn_from_reply/msg_nonexistent")
    assert response.status_code == 404


async def test_spawn_from_reply_404_on_message_from_other_session(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """message_id that exists but belongs to a different session → 404."""
    app, conn = app_and_conn
    parent_id, _msg_id = await _make_parent_with_assistant_message(conn)
    # Create a different session and message.
    other_session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="Other",
        working_dir="/d",
        model="sonnet",
    )
    other_msg = await messages_db.insert_assistant(
        conn,
        session_id=other_session.id,
        content="other assistant",
        executor_model="sonnet",
        advisor_model=None,
        effort_level="auto",
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
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{parent_id}/spawn_from_reply/{other_msg.id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 422 — non-assistant pivot
# ---------------------------------------------------------------------------


async def test_spawn_from_reply_422_on_user_message(
    app_and_conn: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_conn
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="S",
        working_dir="/d",
        model="sonnet",
    )
    user_msg = await messages_db.insert_user(conn, session_id=session.id, content="user prompt")
    with TestClient(app) as client:
        response = client.post(f"/api/sessions/{session.id}/spawn_from_reply/{user_msg.id}")
    assert response.status_code == 422
