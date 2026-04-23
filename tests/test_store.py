from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bearings.db.store import (
    add_session_cost,
    append_tool_output,
    attach_tool_calls_to_message,
    close_session,
    create_session,
    delete_session,
    finish_tool_call,
    get_latest_todowrite,
    get_session,
    get_session_token_totals,
    import_session,
    init_db,
    insert_message,
    insert_tool_call_start,
    list_messages,
    list_sessions,
    list_tool_calls,
    mark_session_completed,
    mark_session_viewed,
    reopen_if_closed,
    reopen_session,
    set_sdk_session_id,
    set_session_permission_mode,
    touch_session,
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
async def test_set_session_permission_mode_round_trips(tmp_path: Path) -> None:
    """Migration 0012: the runner persists the user's PermissionMode on
    every `set_permission_mode` wire frame so a reload restores Plan /
    Auto-edit / Bypass instead of silently downgrading to Ask. Column
    starts NULL on a fresh row (== 'default' behavior), flips to any of
    the four legal strings, and can be cleared back to NULL."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/tmp", model="m")
        assert created["permission_mode"] is None

        await set_session_permission_mode(conn, created["id"], "plan")
        refreshed = await get_session(conn, created["id"])
        assert refreshed is not None
        assert refreshed["permission_mode"] == "plan"

        # Clear back to NULL — how the UI expresses "back to default".
        await set_session_permission_mode(conn, created["id"], None)
        cleared = await get_session(conn, created["id"])
        assert cleared is not None
        assert cleared["permission_mode"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_set_session_permission_mode_rejects_unknown(tmp_path: Path) -> None:
    """Guard rail: SQLite won't enforce the enum so the helper validates
    at the Python edge. A typo like 'Plan' or a stale client literal
    would otherwise silently land in the column and then mis-route on
    read. Raising keeps the runner's own `except ValueError` path
    exercised too."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/tmp", model="m")
        with pytest.raises(ValueError):
            await set_session_permission_mode(conn, created["id"], "Plan")
        with pytest.raises(ValueError):
            await set_session_permission_mode(conn, created["id"], "off")
        refreshed = await get_session(conn, created["id"])
        assert refreshed is not None
        assert refreshed["permission_mode"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_close_session_stamps_and_idempotent(tmp_path: Path) -> None:
    """Migration 0015: `close_session` sets `closed_at` to an ISO
    timestamp and bumps `updated_at`. Calling twice is a no-op from
    the UI's perspective — the second call just refreshes the stamp.
    The row stays the same row."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/tmp", model="m")
        assert created["closed_at"] is None

        closed = await close_session(conn, created["id"])
        assert closed is not None
        assert closed["closed_at"] is not None
        first_stamp = closed["closed_at"]

        # Idempotent — a second close refreshes the stamp, doesn't 404.
        await asyncio.sleep(0.002)
        re_closed = await close_session(conn, created["id"])
        assert re_closed is not None
        assert re_closed["closed_at"] is not None
        assert re_closed["closed_at"] >= first_stamp
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_close_session_unknown_id_returns_none(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await close_session(conn, "does-not-exist") is None
        assert await reopen_session(conn, "does-not-exist") is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_reopen_session_clears_closed_at(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/tmp", model="m")
        await close_session(conn, created["id"])

        reopened = await reopen_session(conn, created["id"])
        assert reopened is not None
        assert reopened["closed_at"] is None

        # Reopen on an already-open row is a no-op, not an error.
        again = await reopen_session(conn, created["id"])
        assert again is not None
        assert again["closed_at"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_reopen_if_closed_only_touches_closed_rows(tmp_path: Path) -> None:
    """`reopen_if_closed` is the helper the reorg routes call — must
    be safe to invoke with any mix of open/closed/missing ids. Open
    rows are untouched (no updated_at bump), closed rows flip to open,
    unknown ids silently skip."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        open_row = await create_session(conn, working_dir="/a", model="m")
        closed_row = await create_session(conn, working_dir="/b", model="m")
        await close_session(conn, closed_row["id"])

        before_open = await get_session(conn, open_row["id"])
        assert before_open is not None

        await reopen_if_closed(conn, open_row["id"], closed_row["id"], "nonexistent-id")

        after_open = await get_session(conn, open_row["id"])
        after_closed = await get_session(conn, closed_row["id"])
        assert after_open is not None and after_closed is not None
        # Closed → open.
        assert after_closed["closed_at"] is None
        # Open row's updated_at is NOT bumped (WHERE clause filters it
        # out). Confirms the helper doesn't churn open rows.
        assert after_open["updated_at"] == before_open["updated_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_import_session_round_trips_closed_at(tmp_path: Path) -> None:
    """Closed-state survives export/import so a closed session archived
    to JSON restores to closed. Simulates the /export → /import loop."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        created = await create_session(conn, working_dir="/tmp", model="m", title="t")
        closed = await close_session(conn, created["id"])
        assert closed is not None

        payload = {
            "session": {
                "working_dir": closed["working_dir"],
                "model": closed["model"],
                "title": closed["title"],
                "description": closed["description"],
                "max_budget_usd": closed["max_budget_usd"],
                "closed_at": closed["closed_at"],
                "created_at": closed["created_at"],
            },
            "messages": [],
            "tool_calls": [],
        }
        restored = await import_session(conn, payload)
        assert restored["closed_at"] == closed["closed_at"]
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
async def test_get_latest_todowrite_returns_none_when_no_calls(tmp_path: Path) -> None:
    """A fresh session has never invoked TodoWrite — the helper must
    return `None` (not an empty list), so the widget can distinguish
    "no todo session yet" from "todo session active but currently
    empty"."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        assert await get_latest_todowrite(conn, sess["id"]) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_latest_todowrite_returns_most_recent_payload(tmp_path: Path) -> None:
    """Three TodoWrite calls; helper returns the list from the latest
    one. Non-TodoWrite tool calls in between are ignored."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn,
            session_id=sess["id"],
            tool_call_id="tw-1",
            name="TodoWrite",
            input_json='{"todos":[{"content":"A","activeForm":"Aing","status":"pending"}]}',
        )
        await asyncio.sleep(0.002)
        await insert_tool_call_start(
            conn,
            session_id=sess["id"],
            tool_call_id="bash-1",
            name="Bash",
            input_json='{"command":"ls"}',
        )
        await asyncio.sleep(0.002)
        await insert_tool_call_start(
            conn,
            session_id=sess["id"],
            tool_call_id="tw-2",
            name="TodoWrite",
            input_json=(
                '{"todos":['
                '{"content":"A","activeForm":"Aing","status":"completed"},'
                '{"content":"B","activeForm":"Bing","status":"in_progress"}'
                "]}"
            ),
        )
        todos = await get_latest_todowrite(conn, sess["id"])
        assert todos is not None
        assert [t["status"] for t in todos] == ["completed", "in_progress"]
        assert todos[0]["content"] == "A"
        assert todos[1]["activeForm"] == "Bing"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_latest_todowrite_returns_none_for_malformed_row(tmp_path: Path) -> None:
    """Malformed JSON (or a missing `todos` key) degrades to None so a
    single corrupt row can't break the widget's first paint. The
    Inspector still has the raw row for debugging."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        await insert_tool_call_start(
            conn,
            session_id=sess["id"],
            tool_call_id="tw-bad",
            name="TodoWrite",
            input_json="not valid json {",
        )
        assert await get_latest_todowrite(conn, sess["id"]) is None
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
async def test_list_tool_calls_filters_by_message_ids(tmp_path: Path) -> None:
    """The conversation pane pulls only the tool_calls bound to the
    messages currently on screen. Cover the three shapes the DB helper
    has to get right: filter=None (full history), filter=[ids] (scoped,
    orphans dropped), filter=[] (short-circuit to empty)."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        m1 = await insert_message(conn, session_id=sess["id"], role="assistant", content="m1")
        m2 = await insert_message(conn, session_id=sess["id"], role="assistant", content="m2")
        # Three tool_calls: one under m1, one under m2, one orphan (no
        # parent message — simulates a call that streamed but never got
        # backfilled because the turn crashed before insert_message).
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="tc-m1", name="R", input_json="{}"
        )
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="tc-m2", name="R", input_json="{}"
        )
        await insert_tool_call_start(
            conn, session_id=sess["id"], tool_call_id="tc-orphan", name="R", input_json="{}"
        )
        await attach_tool_calls_to_message(conn, message_id=m1["id"], tool_call_ids=["tc-m1"])
        await attach_tool_calls_to_message(conn, message_id=m2["id"], tool_call_ids=["tc-m2"])
        # Default (no filter) returns everything, orphans included.
        full = await list_tool_calls(conn, sess["id"])
        assert {r["id"] for r in full} == {"tc-m1", "tc-m2", "tc-orphan"}
        # Scoped filter drops the orphan and the tool_call under m2.
        scoped = await list_tool_calls(conn, sess["id"], message_ids=[m1["id"]])
        assert {r["id"] for r in scoped} == {"tc-m1"}
        # Two-id filter pulls both scoped rows but still drops the orphan.
        both = await list_tool_calls(conn, sess["id"], message_ids=[m1["id"], m2["id"]])
        assert {r["id"] for r in both} == {"tc-m1", "tc-m2"}
        # Empty list short-circuits: no round-trip, no SQL syntax error
        # from a bare `IN ()`.
        assert await list_tool_calls(conn, sess["id"], message_ids=[]) == []
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


@pytest.mark.asyncio
async def test_insert_message_round_trips_token_counts(tmp_path: Path) -> None:
    """Token counts supplied to insert_message come back out on both
    the return dict and a subsequent list_messages read — so the DB
    write, the SELECT column list, and the dict shape are all aligned."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        inserted = await insert_message(
            conn,
            session_id=sess["id"],
            role="assistant",
            content="hi",
            input_tokens=11,
            output_tokens=22,
            cache_read_tokens=33,
            cache_creation_tokens=44,
        )
        assert inserted["input_tokens"] == 11
        assert inserted["output_tokens"] == 22
        assert inserted["cache_read_tokens"] == 33
        assert inserted["cache_creation_tokens"] == 44

        rows = await list_messages(conn, sess["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["input_tokens"] == 11
        assert row["output_tokens"] == 22
        assert row["cache_read_tokens"] == 33
        assert row["cache_creation_tokens"] == 44
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_insert_message_defaults_token_counts_to_null(tmp_path: Path) -> None:
    """Calls that don't pass token counts (user rows, pre-0011 assistant
    rows replayed from imports) land with NULL columns rather than zero
    — that's how the aggregate query can distinguish "no data" from
    "zero use"."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        row = await insert_message(conn, session_id=sess["id"], role="user", content="hi")
        assert row["input_tokens"] is None
        assert row["output_tokens"] is None
        assert row["cache_read_tokens"] is None
        assert row["cache_creation_tokens"] is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_session_token_totals_sums_all_messages(tmp_path: Path) -> None:
    """The aggregate query sums every row for the session and COALESCEs
    NULLs to 0 so user rows don't turn the totals into NULL."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        # User row — all-NULL, must not poison the totals.
        await insert_message(conn, session_id=sess["id"], role="user", content="go")
        # Two assistant turns with different counts.
        await insert_message(
            conn,
            session_id=sess["id"],
            role="assistant",
            content="first",
            input_tokens=10,
            output_tokens=20,
            cache_read_tokens=30,
            cache_creation_tokens=40,
        )
        await insert_message(
            conn,
            session_id=sess["id"],
            role="assistant",
            content="second",
            input_tokens=1,
            output_tokens=2,
            cache_read_tokens=3,
            cache_creation_tokens=4,
        )
        totals = await get_session_token_totals(conn, sess["id"])
        assert totals == {
            "input_tokens": 11,
            "output_tokens": 22,
            "cache_read_tokens": 33,
            "cache_creation_tokens": 44,
        }
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_session_token_totals_empty_session_is_zero(tmp_path: Path) -> None:
    """A session with no messages at all returns all-zeros (COALESCE
    over an empty SUM yields 0, not NULL) so the frontend never has to
    handle null for this endpoint."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/x", model="m", title=None)
        totals = await get_session_token_totals(conn, sess["id"])
        assert totals == {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_get_session_token_totals_scoped_per_session(tmp_path: Path) -> None:
    """Two sessions in the same DB must not bleed into each other's
    totals. Guards against a missing WHERE clause in the aggregate
    query."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        a = await create_session(conn, working_dir="/x", model="m", title=None)
        b = await create_session(conn, working_dir="/y", model="m", title=None)
        await insert_message(
            conn,
            session_id=a["id"],
            role="assistant",
            content="a",
            input_tokens=5,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        await insert_message(
            conn,
            session_id=b["id"],
            role="assistant",
            content="b",
            input_tokens=99,
            output_tokens=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
        assert (await get_session_token_totals(conn, a["id"]))["input_tokens"] == 5
        assert (await get_session_token_totals(conn, b["id"]))["input_tokens"] == 99
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# View tracking (migration 0020)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_touch_session_promotes_without_message(tmp_path: Path) -> None:
    """`touch_session` bumps `updated_at` so a session with no new
    messages still sorts to the top — covers the runner-boot replay
    path where the user row already exists but the runner is about to
    start the orphan's turn."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        older = await create_session(conn, working_dir="/a", model="m", title="older")
        await asyncio.sleep(0.002)
        newer = await create_session(conn, working_dir="/b", model="m", title="newer")
        # newer sorts first right after creation.
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [newer["id"], older["id"]]
        await asyncio.sleep(0.002)
        await touch_session(conn, older["id"])
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [older["id"], newer["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_mark_session_completed_sets_column_and_bumps_updated(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        sess = await create_session(conn, working_dir="/a", model="m")
        before = await get_session(conn, sess["id"])
        assert before is not None
        assert before["last_completed_at"] is None
        await asyncio.sleep(0.002)
        await mark_session_completed(conn, sess["id"])
        after = await get_session(conn, sess["id"])
        assert after is not None
        assert after["last_completed_at"] is not None
        # Shared timestamp with the updated_at bump so sidebar sort
        # and "finished" indicator agree.
        assert after["last_completed_at"] == after["updated_at"]
        assert after["updated_at"] > before["updated_at"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_mark_session_viewed_stamps_without_bumping_sort(tmp_path: Path) -> None:
    """Viewing a session must NOT change its sort position — otherwise
    opening an old session would incorrectly bubble it above sessions
    with actual new activity."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        older = await create_session(conn, working_dir="/a", model="m", title="older")
        await asyncio.sleep(0.002)
        newer = await create_session(conn, working_dir="/b", model="m", title="newer")
        # Preserve the snapshot so we can compare updated_at.
        older_before = await get_session(conn, older["id"])
        assert older_before is not None
        await asyncio.sleep(0.002)
        viewed = await mark_session_viewed(conn, older["id"])
        assert viewed is not None
        assert viewed["last_viewed_at"] is not None
        # updated_at unchanged: viewing doesn't re-sort.
        assert viewed["updated_at"] == older_before["updated_at"]
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [newer["id"], older["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_mark_session_viewed_returns_none_for_unknown(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await mark_session_viewed(conn, "deadbeef" * 4) is None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_add_session_cost_bumps_updated_at(tmp_path: Path) -> None:
    """A cost delta bubbles the session to the top of the sort even if
    no other activity column changes. Guards against a future call path
    that records cost without pairing with `mark_session_completed`."""
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        older = await create_session(conn, working_dir="/a", model="m", title="older")
        await asyncio.sleep(0.002)
        newer = await create_session(conn, working_dir="/b", model="m", title="newer")
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [newer["id"], older["id"]]
        older_before = await get_session(conn, older["id"])
        assert older_before is not None
        await asyncio.sleep(0.002)
        assert await add_session_cost(conn, older["id"], 0.01) is True
        older_after = await get_session(conn, older["id"])
        assert older_after is not None
        assert older_after["total_cost_usd"] == pytest.approx(0.01)
        assert older_after["updated_at"] > older_before["updated_at"]
        rows = await list_sessions(conn)
        assert [r["id"] for r in rows] == [older["id"], newer["id"]]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_add_session_cost_returns_false_for_unknown(tmp_path: Path) -> None:
    conn = await init_db(tmp_path / "db.sqlite")
    try:
        assert await add_session_cost(conn, "deadbeef" * 4, 0.01) is False
    finally:
        await conn.close()
