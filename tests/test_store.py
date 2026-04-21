from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bearings.db.store import (
    append_tool_output,
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
    set_sdk_session_id,
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
        # Count tracks the migrations shipped in `src/bearings/db/migrations/`.
        migrations_dir = Path(__file__).parent.parent / "src/bearings/db/migrations"
        expected = len(list(migrations_dir.glob("*.sql")))
        assert row is not None and row[0] == expected
        # Re-initializing should not duplicate migration records.
        async with conn2.execute("SELECT count(*) FROM schema_migrations") as cursor:
            row2 = await cursor.fetchone()
        assert row2 is not None and row2[0] == expected
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
async def test_set_sdk_session_id_persists(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/tmp", model="m")
        assert created["sdk_session_id"] is None
        await set_sdk_session_id(conn, created["id"], "sdk-abc-123")
        refreshed = await get_session(conn, created["id"])
        assert refreshed is not None
        assert refreshed["sdk_session_id"] == "sdk-abc-123"
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
async def test_session_rows_expose_message_count(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        assert (await get_session(conn, sess["id"]))["message_count"] == 0
        for i in range(3):
            await insert_message(conn, session_id=sess["id"], role="user", content=f"m{i}")
        assert (await get_session(conn, sess["id"]))["message_count"] == 3
        # list_sessions also includes it.
        rows = await list_sessions(conn)
        row = next(r for r in rows if r["id"] == sess["id"])
        assert row["message_count"] == 3
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_sessions_promotes_active_session(tmp_path: Path) -> None:
    """Inserting a message bumps the owning session's updated_at, so
    an older session that just streamed rises above a newer idle one."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        older = await create_session(conn, working_dir="/a", model="m", title="older")
        await asyncio.sleep(0.002)
        newer = await create_session(conn, working_dir="/b", model="m", title="newer")
        # Sanity: newer is on top right after creation.
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [newer["id"], older["id"]]
        # Activity on the older session promotes it.
        await asyncio.sleep(0.002)
        await insert_message(conn, session_id=older["id"], role="user", content="hi")
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [older["id"], newer["id"]]
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
async def test_append_tool_output_builds_cumulative_string(tmp_path: Path) -> None:
    """Three chunks land in order, DB holds the concatenation. This is
    the reconnect-persistence guarantee: the history endpoint can
    reconstruct the tail of output a dropped WS client missed."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="t-stream", name="Bash", input_json="{}"
        )
        assert await append_tool_output(conn, tool_call_id="t-stream", chunk="line 1\n")
        assert await append_tool_output(conn, tool_call_id="t-stream", chunk="line 2\n")
        assert await append_tool_output(conn, tool_call_id="t-stream", chunk="line 3\n")
        row = (await list_tool_calls(conn, sess["id"]))[0]
        assert row["output"] == "line 1\nline 2\nline 3\n"
        # finished_at stays null — append_tool_output must not close the call.
        assert row["finished_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_append_tool_output_handles_first_chunk_from_null(tmp_path: Path) -> None:
    """`insert_tool_call_start` leaves output NULL. The first delta
    must COALESCE that null to '' — otherwise SQLite returns NULL and
    the output field is corrupted on the first append."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="t-first", name="Bash", input_json="{}"
        )
        assert await append_tool_output(conn, tool_call_id="t-first", chunk="hello\n")
        row = (await list_tool_calls(conn, sess["id"]))[0]
        assert row["output"] == "hello\n"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_append_tool_output_then_finish_overwrites_with_canonical(tmp_path: Path) -> None:
    """Deltas build an in-progress view; `finish_tool_call` lands the
    canonical final string and may overwrite. Pinning this behavior
    so a missed delta can't leave a phantom artifact once the call
    finishes."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="t-overwrite", name="Bash", input_json="{}"
        )
        await append_tool_output(conn, tool_call_id="t-overwrite", chunk="partial output\n")
        await finish_tool_call(
            conn, tool_call_id="t-overwrite", output="full final output\n", error=None
        )
        row = (await list_tool_calls(conn, sess["id"]))[0]
        assert row["output"] == "full final output\n"
        assert row["finished_at"] is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_append_tool_output_returns_false_when_missing(tmp_path: Path) -> None:
    """No row → no-op. Caller logs; nothing explodes."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await append_tool_output(conn, tool_call_id="nope", chunk="x") is False
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


@pytest.mark.asyncio
async def test_list_messages_paginates_newest_first(tmp_path: Path) -> None:
    """With `limit`, returns the N most-recent messages in newest-first
    order so a paginated client can prepend older pages as it scrolls
    up."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        inserted = []
        for i in range(5):
            msg = await insert_message(conn, session_id=sess["id"], role="user", content=f"m{i}")
            inserted.append(msg)
            await asyncio.sleep(0.002)

        page = await list_messages(conn, sess["id"], limit=3)
        assert [r["content"] for r in page] == ["m4", "m3", "m2"]

        older = await list_messages(conn, sess["id"], before=inserted[2]["created_at"], limit=3)
        assert [r["content"] for r in older] == ["m1", "m0"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_list_messages_no_limit_still_returns_all(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        for i in range(3):
            await insert_message(conn, session_id=sess["id"], role="user", content=f"m{i}")
            await asyncio.sleep(0.002)
        rows = await list_messages(conn, sess["id"])
        assert [r["content"] for r in rows] == ["m0", "m1", "m2"]
    finally:
        await conn.close()
