"""Tests for ``bearings.db.messages`` (item 1.7 — message INSERT path)."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from bearings.config.constants import SESSION_KIND_CHAT
from bearings.db import messages as messages_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema


@pytest.fixture
async def conn(tmp_path: Path):
    db_path = tmp_path / "msg.db"
    async with aiosqlite.connect(db_path) as connection:
        await load_schema(connection)
        yield connection


async def _new_session(conn: aiosqlite.Connection) -> str:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/wd", model="sonnet"
    )
    return session.id


async def test_insert_user_persists_row(conn: aiosqlite.Connection) -> None:
    sid = await _new_session(conn)
    msg = await messages_db.insert_user(conn, session_id=sid, content="hello")
    assert msg.id.startswith("msg_")
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.session_id == sid
    # Routing/usage columns are NULL for user rows.
    assert msg.executor_model is None
    assert msg.routing_source is None


async def test_insert_user_bumps_session_message_count(conn: aiosqlite.Connection) -> None:
    sid = await _new_session(conn)
    before = await sessions_db.get(conn, sid)
    assert before is not None and before.message_count == 0
    await messages_db.insert_user(conn, session_id=sid, content="a")
    await messages_db.insert_user(conn, session_id=sid, content="b")
    after = await sessions_db.get(conn, sid)
    assert after is not None and after.message_count == 2


async def test_insert_system_role(conn: aiosqlite.Connection) -> None:
    sid = await _new_session(conn)
    msg = await messages_db.insert_system(conn, session_id=sid, content="resuming…")
    assert msg.role == "system"


async def test_list_for_session_chronological(conn: aiosqlite.Connection) -> None:
    sid = await _new_session(conn)
    a = await messages_db.insert_user(conn, session_id=sid, content="first")
    b = await messages_db.insert_user(conn, session_id=sid, content="second")
    rows = await messages_db.list_for_session(conn, sid)
    assert [row.id for row in rows] == [a.id, b.id]


async def test_list_for_session_with_limit_returns_tail(conn: aiosqlite.Connection) -> None:
    sid = await _new_session(conn)
    await messages_db.insert_user(conn, session_id=sid, content="first")
    b = await messages_db.insert_user(conn, session_id=sid, content="second")
    c = await messages_db.insert_user(conn, session_id=sid, content="third")
    rows = await messages_db.list_for_session(conn, sid, limit=2)
    assert [row.id for row in rows] == [b.id, c.id]


async def test_list_for_session_before_cursor(conn: aiosqlite.Connection) -> None:
    """``before=`` filters to rows with rowid < cursor (item 1.3)."""
    sid = await _new_session(conn)
    a = await messages_db.insert_user(conn, session_id=sid, content="first")
    b = await messages_db.insert_user(conn, session_id=sid, content="second")
    c = await messages_db.insert_user(conn, session_id=sid, content="third")
    # seq of ``b`` — should exclude b and c.
    rows = await messages_db.list_for_session(conn, sid, before=b.seq)
    assert [row.id for row in rows] == [a.id]
    # Combine with limit.
    rows2 = await messages_db.list_for_session(conn, sid, limit=10, before=c.seq)
    assert [row.id for row in rows2] == [a.id, b.id]


async def test_list_for_session_seq_increases(conn: aiosqlite.Connection) -> None:
    """``seq`` is the SQLite rowid — strictly increasing per insert order."""
    sid = await _new_session(conn)
    a = await messages_db.insert_user(conn, session_id=sid, content="x")
    b = await messages_db.insert_user(conn, session_id=sid, content="y")
    assert a.seq > 0
    assert b.seq > a.seq


async def test_count_for_session(conn: aiosqlite.Connection) -> None:
    sid = await _new_session(conn)
    await messages_db.insert_user(conn, session_id=sid, content="x")
    assert await messages_db.count_for_session(conn, sid) == 1


async def test_get_returns_none_for_missing(conn: aiosqlite.Connection) -> None:
    assert await messages_db.get(conn, "msg_missing") is None


async def test_invalid_role_rejected_at_dataclass(
    conn: aiosqlite.Connection,
) -> None:
    sid = await _new_session(conn)
    msg = await messages_db.insert_user(conn, session_id=sid, content="x")
    # The dataclass validator catches a malformed role even when the
    # row came from the DB; phantom-construct to verify.
    with pytest.raises(ValueError, match="role"):
        type(msg)(
            id="msg_x",
            session_id=sid,
            role="bogus",
            content="x",
            created_at=msg.created_at,
            executor_model=None,
            advisor_model=None,
            effort_level=None,
            routing_source=None,
            routing_reason=None,
            matched_rule_id=None,
            executor_input_tokens=None,
            executor_output_tokens=None,
            advisor_input_tokens=None,
            advisor_output_tokens=None,
            advisor_calls_count=None,
            cache_read_tokens=None,
            input_tokens=None,
            output_tokens=None,
            seq=1,
        )
