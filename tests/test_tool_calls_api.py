"""Integration tests for the tool_calls DB layer and REST endpoint.

Acceptance criteria covered (gap-cycle-03-012):

* AC1: GET /api/sessions/{id}/tool_calls?message_ids=… returns persisted
  tool_call rows attached to the listed messages.
* AC4: tool_calls are retrievable for a session whose runner has never
  started in this process (all inserts via DB helpers directly).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema
from bearings.db.tool_calls import ToolCallRecord, insert_batch, list_for_messages
from bearings.web.app import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    conn = await aiosqlite.connect(tmp_path / "tc_test.db")
    try:
        await load_schema(conn)
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def app_and_db(
    tmp_path: Path,
) -> AsyncIterator[tuple[FastAPI, aiosqlite.Connection]]:
    conn = await aiosqlite.connect(tmp_path / "tc_api.db")
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
        executor_input_tokens=10,
        executor_output_tokens=20,
        advisor_input_tokens=None,
        advisor_output_tokens=None,
        advisor_calls_count=0,
        cache_read_tokens=None,
    )
    return msg.id


# ---------------------------------------------------------------------------
# DB-layer unit tests (AC4 — no runner)
# ---------------------------------------------------------------------------


async def test_insert_batch_and_list_for_messages(
    db: aiosqlite.Connection,
) -> None:
    """insert_batch persists records; list_for_messages retrieves them."""
    sid = await _make_session(db)
    mid = await _make_assistant(db, sid)

    records = [
        ToolCallRecord(
            tool_call_id="toolu_01",
            tool_name="Bash",
            input_json='{"command":"ls"}',
            output="file1.txt\nfile2.txt",
            ok=True,
            duration_ms=42,
            error_message=None,
        ),
        ToolCallRecord(
            tool_call_id="toolu_02",
            tool_name="Read",
            input_json='{"file_path":"/tmp/x"}',
            output="content",
            ok=True,
            duration_ms=10,
            error_message=None,
        ),
    ]
    await insert_batch(db, session_id=sid, message_id=mid, records=records)

    rows = await list_for_messages(db, session_id=sid, message_ids=[mid])
    assert len(rows) == 2
    assert rows[0].id == "toolu_01"
    assert rows[0].tool_name == "Bash"
    assert rows[0].output == "file1.txt\nfile2.txt"
    assert rows[0].ok is True
    assert rows[0].duration_ms == 42
    assert rows[0].error_message is None
    assert rows[1].id == "toolu_02"


async def test_list_for_messages_empty_ids_returns_empty(
    db: aiosqlite.Connection,
) -> None:
    """Passing an empty message_ids list returns [] without hitting DB."""
    sid = await _make_session(db)
    rows = await list_for_messages(db, session_id=sid, message_ids=[])
    assert rows == []


async def test_list_for_messages_unknown_session_returns_empty(
    db: aiosqlite.Connection,
) -> None:
    """Query against a non-existent session returns empty list."""
    rows = await list_for_messages(db, session_id="ses_nope", message_ids=["msg_x"])
    assert rows == []


async def test_insert_batch_empty_is_noop(
    db: aiosqlite.Connection,
) -> None:
    """insert_batch with no records performs no DB write."""
    sid = await _make_session(db)
    mid = await _make_assistant(db, sid)
    await insert_batch(db, session_id=sid, message_id=mid, records=[])
    rows = await list_for_messages(db, session_id=sid, message_ids=[mid])
    assert rows == []


async def test_failed_tool_call_ok_false(
    db: aiosqlite.Connection,
) -> None:
    """ok=False is preserved through the round-trip."""
    sid = await _make_session(db)
    mid = await _make_assistant(db, sid)
    await insert_batch(
        db,
        session_id=sid,
        message_id=mid,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_fail",
                tool_name="Bash",
                input_json="{}",
                output="error: command not found",
                ok=False,
                duration_ms=5,
                error_message="command not found",
            )
        ],
    )
    rows = await list_for_messages(db, session_id=sid, message_ids=[mid])
    assert len(rows) == 1
    assert rows[0].ok is False
    assert rows[0].error_message == "command not found"


async def test_insert_batch_idempotent_on_duplicate_id(
    db: aiosqlite.Connection,
) -> None:
    """Second insert for the same tool_call_id is silently ignored."""
    sid = await _make_session(db)
    mid = await _make_assistant(db, sid)
    rec = ToolCallRecord(
        tool_call_id="toolu_dup",
        tool_name="Bash",
        input_json="{}",
        output="first",
        ok=True,
        duration_ms=1,
        error_message=None,
    )
    await insert_batch(db, session_id=sid, message_id=mid, records=[rec])
    # Second insert of the same id — INSERT OR IGNORE keeps first row.
    rec2 = ToolCallRecord(
        tool_call_id="toolu_dup",
        tool_name="Read",
        input_json="{}",
        output="second",
        ok=False,
        duration_ms=2,
        error_message="oops",
    )
    await insert_batch(db, session_id=sid, message_id=mid, records=[rec2])
    rows = await list_for_messages(db, session_id=sid, message_ids=[mid])
    assert len(rows) == 1
    assert rows[0].output == "first"  # first row preserved


async def test_list_filters_by_session_id(
    db: aiosqlite.Connection,
) -> None:
    """message_ids from a different session are not returned."""
    sid1 = await _make_session(db, "s1")
    sid2 = await _make_session(db, "s2")
    mid1 = await _make_assistant(db, sid1)
    mid2 = await _make_assistant(db, sid2)
    await insert_batch(
        db,
        session_id=sid1,
        message_id=mid1,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_s1",
                tool_name="Bash",
                input_json="{}",
                output="x",
                ok=True,
                duration_ms=1,
                error_message=None,
            )
        ],
    )
    # Querying sid2 with mid1 (from sid1) returns nothing.
    rows = await list_for_messages(db, session_id=sid2, message_ids=[mid1, mid2])
    assert rows == []


# ---------------------------------------------------------------------------
# REST endpoint integration tests (AC1)
# ---------------------------------------------------------------------------


async def test_api_tool_calls_returns_rows(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """GET /api/sessions/{id}/tool_calls?message_ids=… returns persisted rows."""
    app, conn = app_and_db
    sid = await _make_session(conn)
    mid = await _make_assistant(conn, sid)
    await insert_batch(
        conn,
        session_id=sid,
        message_id=mid,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_api",
                tool_name="Grep",
                input_json='{"pattern":"foo"}',
                output="bar.py:1:foo",
                ok=True,
                duration_ms=15,
                error_message=None,
            )
        ],
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/sessions/{sid}/tool_calls",
            params={"message_ids": mid},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "toolu_api"
    assert data[0]["tool_name"] == "Grep"
    assert data[0]["message_id"] == mid
    assert data[0]["ok"] is True


async def test_api_tool_calls_404_on_missing_session(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """GET /api/sessions/{id}/tool_calls returns 404 for unknown session."""
    app, _ = app_and_db
    with TestClient(app) as client:
        resp = client.get(
            "/api/sessions/ses_nope/tool_calls",
            params={"message_ids": "msg_x"},
        )
    assert resp.status_code == 404


async def test_api_tool_calls_empty_when_no_tool_calls(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Session with no tool calls returns 200 with []."""
    app, conn = app_and_db
    sid = await _make_session(conn)
    mid = await _make_assistant(conn, sid)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/sessions/{sid}/tool_calls",
            params={"message_ids": mid},
        )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_api_tool_calls_no_message_ids_returns_all(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Omitting message_ids returns all tool calls for the session."""
    app, conn = app_and_db
    sid = await _make_session(conn)
    mid1 = await _make_assistant(conn, sid)
    mid2 = await _make_assistant(conn, sid)
    await insert_batch(
        conn,
        session_id=sid,
        message_id=mid1,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_a",
                tool_name="Bash",
                input_json="{}",
                output="a",
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
                tool_call_id="toolu_b",
                tool_name="Read",
                input_json="{}",
                output="b",
                ok=True,
                duration_ms=2,
                error_message=None,
            )
        ],
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/sessions/{sid}/tool_calls")
    assert resp.status_code == 200
    ids = {tc["id"] for tc in resp.json()}
    assert ids == {"toolu_a", "toolu_b"}


async def test_api_tool_calls_multiple_message_ids(
    app_and_db: tuple[FastAPI, aiosqlite.Connection],
) -> None:
    """Passing multiple message_ids fetches tool calls for each."""
    app, conn = app_and_db
    sid = await _make_session(conn)
    mid1 = await _make_assistant(conn, sid)
    mid2 = await _make_assistant(conn, sid)
    await insert_batch(
        conn,
        session_id=sid,
        message_id=mid1,
        records=[
            ToolCallRecord(
                tool_call_id="toolu_m1",
                tool_name="Bash",
                input_json="{}",
                output="out1",
                ok=True,
                duration_ms=3,
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
                tool_call_id="toolu_m2",
                tool_name="Read",
                input_json="{}",
                output="out2",
                ok=True,
                duration_ms=4,
                error_message=None,
            )
        ],
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/sessions/{sid}/tool_calls",
            params=[("message_ids", mid1), ("message_ids", mid2)],
        )
    assert resp.status_code == 200
    ids = {tc["id"] for tc in resp.json()}
    assert ids == {"toolu_m1", "toolu_m2"}
