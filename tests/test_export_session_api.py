"""Integration tests for ``GET /api/sessions/{id}/export``.

Per ``docs/behavior/sessions.md`` §"Export contract":

* 200 with correct JSON envelope for an existing session.
* Every message (all roles) appears in ``messages``.
* Every checkpoint appears in ``checkpoints``.
* Closed sessions are exportable (no 409).
* 404 for an unknown session id.
* Round-trip: export captures all data written to the session.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import checkpoints as checkpoints_db
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.web.app import create_app


@pytest.fixture
async def app_and_db(tmp_path: Path) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    db_path = tmp_path / "export.db"
    conn = await aiosqlite.connect(db_path)
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


async def _new_chat(conn: aiosqlite.Connection, title: str = "Test Session") -> str:
    s = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title=title,
        working_dir="/wd",
        model="claude-sonnet-4-5",
    )
    return s.id


async def test_export_404_for_unknown_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, _ = app_and_db
    with TestClient(app) as client:
        resp = client.get("/api/sessions/ses_does_not_exist/export")
    assert resp.status_code == 404


async def test_export_returns_200_with_json_envelope(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/export")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    body = resp.json()
    assert set(body.keys()) == {"session", "messages", "tool_calls", "checkpoints", "attachments"}


async def test_export_session_row_matches_get(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """``export.session`` is identical to ``GET /api/sessions/{id}``."""
    app, conn = app_and_db
    sid = await _new_chat(conn, "My Session")
    with TestClient(app) as client:
        export_resp = client.get(f"/api/sessions/{sid}/export")
        get_resp = client.get(f"/api/sessions/{sid}")
    assert export_resp.status_code == 200
    assert get_resp.status_code == 200
    assert export_resp.json()["session"] == get_resp.json()


async def test_export_includes_all_messages(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Every message (all roles) appears in ``messages[]``."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    await messages_db.insert_user(conn, session_id=sid, content="hello")
    await messages_db.insert_system(conn, session_id=sid, content="sys prompt")
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/export")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert len(messages) == 2
    roles = {m["role"] for m in messages}
    assert roles == {"user", "system"}
    # All MessageExport fields present on every row
    expected_fields = {
        "id",
        "session_id",
        "role",
        "content",
        "created_at",
        "executor_model",
        "advisor_model",
        "effort_level",
        "routing_source",
        "routing_reason",
        "matched_rule_id",
        "executor_input_tokens",
        "executor_output_tokens",
        "advisor_input_tokens",
        "advisor_output_tokens",
        "advisor_calls_count",
        "cache_read_tokens",
        "cache_creation_tokens",
        "input_tokens",
        "output_tokens",
        "seq",
        "pinned",
        "hidden_from_context",
    }
    for msg in messages:
        assert set(msg.keys()) == expected_fields


async def test_export_includes_checkpoints(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Checkpoints attached to the session appear in ``checkpoints[]``."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    msg = await messages_db.insert_user(conn, session_id=sid, content="hi")
    await checkpoints_db.create(conn, session_id=sid, message_id=msg.id, label="v1")
    await checkpoints_db.create(conn, session_id=sid, message_id=msg.id, label="v2")
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/export")
    assert resp.status_code == 200
    checkpoints = resp.json()["checkpoints"]
    assert len(checkpoints) == 2
    labels = {c["label"] for c in checkpoints}
    assert labels == {"v1", "v2"}
    # All CheckpointExport fields present
    expected_fields = {"id", "session_id", "message_id", "label", "created_at"}
    for cp in checkpoints:
        assert set(cp.keys()) == expected_fields


async def test_export_closed_session_returns_200(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Closed sessions are exportable — no 409."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    await sessions_db.close(conn, sid)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/export")
    assert resp.status_code == 200
    assert resp.json()["session"]["closed_at"] is not None


async def test_export_attachments_always_empty(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """``attachments[]`` is always ``[]`` in v0.18.x."""
    app, conn = app_and_db
    sid = await _new_chat(conn)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/export")
    assert resp.status_code == 200
    assert resp.json()["attachments"] == []


async def test_export_content_disposition_header(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Content-Disposition carries the slugified session title."""
    app, conn = app_and_db
    sid = await _new_chat(conn, "My Test Session!")
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/export")
    assert resp.status_code == 200
    disposition = resp.headers.get("content-disposition", "")
    assert "my-test-session" in disposition
    assert disposition.endswith('.json"')


async def test_export_round_trip_captures_all_data(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Round-trip: export captures all data written to the session.

    Creates a session with messages and a checkpoint, exports it, then
    verifies the export payload completely reflects what was written.
    This satisfies the acceptance-criterion round-trip gate (no import
    endpoint needed — the export itself is the verifiable artifact).
    """
    app, conn = app_and_db
    sid = await _new_chat(conn, "Round Trip")

    # Write messages
    user_msg = await messages_db.insert_user(conn, session_id=sid, content="user msg")
    sys_msg = await messages_db.insert_system(conn, session_id=sid, content="system msg")

    # Write checkpoint
    await checkpoints_db.create(conn, session_id=sid, message_id=user_msg.id, label="checkpoint-1")

    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/export")
    assert resp.status_code == 200
    body = resp.json()

    # Session row present and correct
    assert body["session"]["id"] == sid
    assert body["session"]["title"] == "Round Trip"

    # Both messages present with correct content
    message_contents = {m["content"] for m in body["messages"]}
    assert "user msg" in message_contents
    assert "system msg" in message_contents

    # Message IDs match what was written
    message_ids = {m["id"] for m in body["messages"]}
    assert user_msg.id in message_ids
    assert sys_msg.id in message_ids

    # Checkpoint present
    assert len(body["checkpoints"]) == 1
    assert body["checkpoints"][0]["label"] == "checkpoint-1"
    assert body["checkpoints"][0]["message_id"] == user_msg.id
