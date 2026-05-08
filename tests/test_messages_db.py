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


async def _insert_assistant(
    conn: aiosqlite.Connection,
    session_id: str,
    content: str = "reply",
) -> messages_db.Message:
    """Helper: insert a minimal assistant-role row for test purposes."""
    return await messages_db.insert_assistant(
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
        cache_creation_tokens=None,
    )


async def test_get_preceding_user_message_finds_pivot(conn: aiosqlite.Connection) -> None:
    """Returns the user message immediately before the given seq."""
    sid = await _new_session(conn)
    u1 = await messages_db.insert_user(conn, session_id=sid, content="first prompt")
    a1 = await _insert_assistant(conn, sid, "first reply")
    u2 = await messages_db.insert_user(conn, session_id=sid, content="second prompt")
    a2 = await _insert_assistant(conn, sid, "second reply")

    # Pivot for a1: should find u1.
    pivot_for_a1 = await messages_db.get_preceding_user_message(conn, sid, a1.seq)
    assert pivot_for_a1 is not None
    assert pivot_for_a1.id == u1.id

    # Pivot for a2: should find u2 (the closest preceding user message).
    pivot_for_a2 = await messages_db.get_preceding_user_message(conn, sid, a2.seq)
    assert pivot_for_a2 is not None
    assert pivot_for_a2.id == u2.id


async def test_get_preceding_user_message_returns_none_when_none(
    conn: aiosqlite.Connection,
) -> None:
    """Returns None when no user message precedes the given seq."""
    sid = await _new_session(conn)
    a1 = await _insert_assistant(conn, sid, "orphan assistant")
    result = await messages_db.get_preceding_user_message(conn, sid, a1.seq)
    assert result is None


async def test_truncate_after_removes_messages_and_fixes_count(
    conn: aiosqlite.Connection,
) -> None:
    """Deletes rows with rowid > pivot_seq and decrements message_count."""
    from bearings.db import sessions as sessions_db

    sid = await _new_session(conn)
    u1 = await messages_db.insert_user(conn, session_id=sid, content="q1")
    await _insert_assistant(conn, sid, "a1")
    await messages_db.insert_user(conn, session_id=sid, content="q2")
    await _insert_assistant(conn, sid, "a2")

    session_before = await sessions_db.get(conn, sid)
    assert session_before is not None and session_before.message_count == 4

    deleted = await messages_db.truncate_after(conn, sid, pivot_seq=u1.seq)
    # Rows after u1 (a1, q2, a2) should be deleted — 3 rows.
    assert deleted == 3

    rows = await messages_db.list_for_session(conn, sid)
    assert [r.id for r in rows] == [u1.id]

    session_after = await sessions_db.get(conn, sid)
    assert session_after is not None and session_after.message_count == 1


async def test_truncate_after_no_op_when_nothing_after(conn: aiosqlite.Connection) -> None:
    """Returns 0 when no messages exist after the pivot_seq."""
    sid = await _new_session(conn)
    u1 = await messages_db.insert_user(conn, session_id=sid, content="q1")
    deleted = await messages_db.truncate_after(conn, sid, pivot_seq=u1.seq)
    assert deleted == 0
    rows = await messages_db.list_for_session(conn, sid)
    assert len(rows) == 1


async def test_truncate_after_does_not_touch_other_sessions(
    conn: aiosqlite.Connection,
) -> None:
    """Only removes messages belonging to session_id, not other sessions."""
    from bearings.db import sessions as sessions_db

    sid_a = await _new_session(conn)
    sid_b = await _new_session(conn)
    u_a = await messages_db.insert_user(conn, session_id=sid_a, content="a1")
    await messages_db.insert_user(conn, session_id=sid_a, content="a2")
    await messages_db.insert_user(conn, session_id=sid_b, content="b1")

    await messages_db.truncate_after(conn, sid_a, pivot_seq=u_a.seq)

    # sid_b is untouched.
    rows_b = await messages_db.list_for_session(conn, sid_b)
    assert len(rows_b) == 1
    session_b = await sessions_db.get(conn, sid_b)
    assert session_b is not None and session_b.message_count == 1


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
            cache_creation_tokens=None,
            input_tokens=None,
            output_tokens=None,
            seq=1,
        )
