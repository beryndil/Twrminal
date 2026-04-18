from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from twrminal.db.store import (
    create_session,
    delete_session,
    get_session,
    init_db,
    insert_message,
    list_messages,
    list_sessions,
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
