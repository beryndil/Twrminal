from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from twrminal.db.store import (
    create_session,
    delete_session,
    finish_tool_call,
    get_session,
    init_db,
    insert_message,
    insert_tool_call_start,
    list_messages,
    list_sessions,
    list_tool_calls,
)


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = [row[0] async for row in cursor]
        assert "sessions" in tables
        assert "messages" in tables
        assert "tool_calls" in tables
        assert "schema_migrations" in tables
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    conn1 = await init_db(db_path)
    await conn1.close()
    conn2 = await init_db(db_path)
    try:
        async with conn2.execute("SELECT count(*) FROM schema_migrations") as cursor:
            row = await cursor.fetchone()
        assert row is not None and row[0] == 1
    finally:
        await conn2.close()


@pytest.mark.asyncio
async def test_create_session_returns_row(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        row = await create_session(
            conn, working_dir="/tmp/demo", model="claude-sonnet-4-6", title="hello"
        )
        assert len(row["id"]) == 32
        assert row["working_dir"] == "/tmp/demo"
        assert row["model"] == "claude-sonnet-4-6"
        assert row["title"] == "hello"
        assert row["created_at"]
        assert row["updated_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_session_round_trip(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/tmp", model="m", title=None)
        fetched = await get_session(conn, created["id"])
        assert fetched == created
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_session_returns_none_for_missing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await get_session(conn, "deadbeef" * 4) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_sessions_orders_newest_first(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        first = await create_session(conn, working_dir="/a", model="m", title="one")
        await asyncio.sleep(0.002)
        second = await create_session(conn, working_dir="/b", model="m", title="two")
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [second["id"], first["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_session_removes_row(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/x", model="m", title=None)
        assert await delete_session(conn, created["id"]) is True
        assert await get_session(conn, created["id"]) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_session_returns_false_for_missing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await delete_session(conn, "deadbeef" * 4) is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_delete_session_cascades_messages(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_message(conn, session_id=sess["id"], role="user", content="hi")
        await insert_message(conn, session_id=sess["id"], role="assistant", content="hello")
        assert len(await list_messages(conn, sess["id"])) == 2
        await delete_session(conn, sess["id"])
        assert await list_messages(conn, sess["id"]) == []
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_insert_message_returns_row(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        row = await insert_message(conn, session_id=sess["id"], role="user", content="prompt")
        assert len(row["id"]) == 32
        assert row["session_id"] == sess["id"]
        assert row["role"] == "user"
        assert row["content"] == "prompt"
        assert row["created_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_insert_tool_call_start_returns_row(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        row = await insert_tool_call_start(
            conn,
            session_id=sess["id"],
            tool_call_id="t-1",
            name="Read",
            input_json='{"path":"/etc/hosts"}',
        )
        assert row["id"] == "t-1"
        assert row["session_id"] == sess["id"]
        assert row["name"] == "Read"
        assert row["input"] == '{"path":"/etc/hosts"}'
        assert row["started_at"]
        assert row["finished_at"] is None
        assert row["output"] is None
        assert row["error"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_finish_tool_call_updates_output(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="t-ok", name="R", input_json="{}"
        )
        assert await finish_tool_call(conn, tool_call_id="t-ok", output="done", error=None)
        rows = await list_tool_calls(conn, sess["id"])
        assert rows[0]["output"] == "done"
        assert rows[0]["error"] is None
        assert rows[0]["finished_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_finish_tool_call_records_error(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="t-err", name="R", input_json="{}"
        )
        assert await finish_tool_call(conn, tool_call_id="t-err", output=None, error="boom")
        row = (await list_tool_calls(conn, sess["id"]))[0]
        assert row["output"] is None
        assert row["error"] == "boom"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_finish_tool_call_returns_false_when_missing(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await finish_tool_call(conn, tool_call_id="nope", output="x", error=None) is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_tool_calls_orders_oldest_first(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="a", name="R", input_json="{}"
        )
        await asyncio.sleep(0.002)
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="b", name="W", input_json="{}"
        )
        rows = await list_tool_calls(conn, sess["id"])
        assert [r["id"] for r in rows] == ["a", "b"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_messages_orders_oldest_first(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        m1 = await insert_message(conn, session_id=sess["id"], role="user", content="first")
        await asyncio.sleep(0.002)
        m2 = await insert_message(conn, session_id=sess["id"], role="assistant", content="second")
        rows = await list_messages(conn, sess["id"])
        assert [r["id"] for r in rows] == [m1["id"], m2["id"]]
    finally:
        await conn.close()
