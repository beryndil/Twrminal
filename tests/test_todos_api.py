"""Integration tests for the todos hydration endpoint (gap-cycle-03-013).

Acceptance criteria covered:

* AC1: GET /api/sessions/{id}/todos returns the most-recent persisted
  TodoWrite payload.
* AC2: null (200) for sessions that never wrote todos.
* AC3: 404 for sessions that do not exist.
* DB layer: latest_todo_write_json returns the most-recent TodoWrite
  input_json and None for sessions without any TodoWrite row.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.db.tool_calls import ToolCallRecord, insert_batch, latest_todo_write_json
from bearings.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await aiosqlite.connect(tmp_path / "todos_test.db")
    try:
        await load_schema(conn)
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def app_and_db(
    tmp_path: Path,
) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    conn = await aiosqlite.connect(tmp_path / "todos_api.db")
    try:
        await load_schema(conn)
        app = create_app(db_connection=conn)
        yield app, conn
    finally:
        await conn.close()


async def _make_session(conn: aiosqlite.Connection, title: str = "s") -> str:
    row = await sessions_db.create(
        conn, kind="chat", title=title, working_dir="/wd", model="sonnet"
    )
    return row.id


async def _make_assistant(conn: aiosqlite.Connection, session_id: str) -> str:
    from bearings.agent.routing import RoutingDecision

    decision = RoutingDecision(
        executor_model="sonnet",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="auto",
        source="default",
        reason="default",
        matched_rule_id=None,
        evaluated_rules=[],
    )
    msg = await messages_db.insert_assistant(
        conn,
        session_id=session_id,
        content="done",
        executor_model=decision.executor_model,
        advisor_model=decision.advisor_model,
        effort_level=decision.effort_level,
        routing_source=decision.source,
        routing_reason=decision.reason,
        matched_rule_id=decision.matched_rule_id,
        evaluated_rules=[],
        executor_input_tokens=10,
        executor_output_tokens=20,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=0,
        cache_read_tokens=None,
    )
    return msg.id


_SAMPLE_TODOS = [
    {"id": "t1", "content": "write tests", "status": "in_progress", "priority": "high"},
    {"id": "t2", "content": "ship it", "status": "pending", "priority": "medium"},
]

_SAMPLE_INPUT_JSON = json.dumps({"todos": _SAMPLE_TODOS})


# ---------------------------------------------------------------------------
# DB-layer unit tests
# ---------------------------------------------------------------------------


async def test_latest_todo_write_json_returns_most_recent(db: aiosqlite.Connection) -> None:
    """latest_todo_write_json returns the input_json of the last TodoWrite row."""
    sid = await _make_session(db)
    mid1 = await _make_assistant(db, sid)
    mid2 = await _make_assistant(db, sid)

    first_todos = json.dumps({"todos": [{"content": "first", "status": "pending"}]})
    await insert_batch(
        db,
        session_id=sid,
        message_id=mid1,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_tw_1",
                tool_name="TodoWrite",
                input_json=first_todos,
                output="",
                ok=True,
                duration_ms=5,
                error_message=None,
            )
        ],
    )
    await insert_batch(
        db,
        session_id=sid,
        message_id=mid2,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_tw_2",
                tool_name="TodoWrite",
                input_json=_SAMPLE_INPUT_JSON,
                output="",
                ok=True,
                duration_ms=5,
                error_message=None,
            )
        ],
    )

    result = await latest_todo_write_json(db, session_id=sid)
    assert result == _SAMPLE_INPUT_JSON


async def test_latest_todo_write_json_none_when_no_todo_write(
    db: aiosqlite.Connection,
) -> None:
    """Returns None for a session with no TodoWrite tool calls."""
    sid = await _make_session(db)
    mid = await _make_assistant(db, sid)
    await insert_batch(
        db,
        session_id=sid,
        message_id=mid,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_bash",
                tool_name="Bash",
                input_json='{"command":"ls"}',
                output="file.txt",
                ok=True,
                duration_ms=10,
                error_message=None,
            )
        ],
    )
    result = await latest_todo_write_json(db, session_id=sid)
    assert result is None


async def test_latest_todo_write_json_none_for_empty_session(
    db: aiosqlite.Connection,
) -> None:
    """Returns None when the session has no tool calls at all."""
    sid = await _make_session(db)
    result = await latest_todo_write_json(db, session_id=sid)
    assert result is None


async def test_latest_todo_write_json_skips_non_todo_rows(
    db: aiosqlite.Connection,
) -> None:
    """Only rows with tool_name='TodoWrite' are considered."""
    sid = await _make_session(db)
    mid = await _make_assistant(db, sid)
    await insert_batch(
        db,
        session_id=sid,
        message_id=mid,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_read",
                tool_name="Read",
                input_json='{"file_path":"/tmp/x"}',
                output="content",
                ok=True,
                duration_ms=2,
                error_message=None,
            ),
            ToolCallRecord(
                tool_call_id="toolu_tw",
                tool_name="TodoWrite",
                input_json=_SAMPLE_INPUT_JSON,
                output="",
                ok=True,
                duration_ms=3,
                error_message=None,
            ),
        ],
    )
    result = await latest_todo_write_json(db, session_id=sid)
    assert result == _SAMPLE_INPUT_JSON


# ---------------------------------------------------------------------------
# REST endpoint integration tests
# ---------------------------------------------------------------------------


async def test_api_todos_returns_latest_todo_write(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """GET /api/sessions/{id}/todos returns todos_json matching the latest TodoWrite."""
    app, conn = app_and_db
    sid = await _make_session(conn)
    mid = await _make_assistant(conn, sid)
    await insert_batch(
        conn,
        session_id=sid,
        message_id=mid,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_tw_api",
                tool_name="TodoWrite",
                input_json=_SAMPLE_INPUT_JSON,
                output="",
                ok=True,
                duration_ms=5,
                error_message=None,
            )
        ],
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/todos")
    assert resp.status_code == 200
    data = resp.json()
    assert data is not None
    assert "todos_json" in data
    parsed = json.loads(data["todos_json"])
    assert parsed == _SAMPLE_TODOS


async def test_api_todos_null_for_session_without_todos(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """GET /api/sessions/{id}/todos returns null (200) for sessions that never wrote todos."""
    app, conn = app_and_db
    sid = await _make_session(conn)
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/todos")
    assert resp.status_code == 200
    assert resp.json() is None


async def test_api_todos_404_for_missing_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """GET /api/sessions/{id}/todos returns 404 for an unknown session."""
    app, _ = app_and_db
    with TestClient(app) as client:
        resp = client.get("/api/sessions/ses_nope/todos")
    assert resp.status_code == 404


async def test_api_todos_returns_most_recent_on_multiple_writes(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """When TodoWrite is called multiple times, the response reflects the latest."""
    app, conn = app_and_db
    sid = await _make_session(conn)
    mid1 = await _make_assistant(conn, sid)
    mid2 = await _make_assistant(conn, sid)

    first_todos = json.dumps({"todos": [{"content": "old", "status": "pending"}]})
    await insert_batch(
        conn,
        session_id=sid,
        message_id=mid1,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_tw_old",
                tool_name="TodoWrite",
                input_json=first_todos,
                output="",
                ok=True,
                duration_ms=1,
                error_message=None,
            )
        ],
    )
    await insert_batch(
        conn,
        session_id=sid,
        message_id=mid2,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_tw_new",
                tool_name="TodoWrite",
                input_json=_SAMPLE_INPUT_JSON,
                output="",
                ok=True,
                duration_ms=2,
                error_message=None,
            )
        ],
    )

    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/todos")
    assert resp.status_code == 200
    data = resp.json()
    parsed = json.loads(data["todos_json"])
    # Should reflect the latest write (_SAMPLE_TODOS), not "old".
    assert parsed == _SAMPLE_TODOS
