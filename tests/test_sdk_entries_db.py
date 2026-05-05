"""Unit tests for :mod:`bearings.db.sdk_entries`.

Covers the storage layer for the SDK :class:`SessionStore` adapter:

* ``append`` writes batches with monotonic per-session ``seq``.
* ``load`` returns entries oldest-first, parsed back to dicts.
* ``count_for_session`` is a fast no-parse existence probe.
* ``delete_for_session`` returns the row count and is honoured by the
  schema's ``ON DELETE CASCADE`` on session deletion.
* Per-session isolation — entries on one session don't leak into another.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.db import sdk_entries as sdk_entries_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema


@pytest.fixture
async def conn(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Fresh schema-loaded SQLite connection per test."""
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await load_schema(connection)
        yield connection


async def _make_session(conn: aiosqlite.Connection) -> str:
    """Insert a chat session row and return its id."""
    row = await sessions_db.create(
        conn,
        kind="chat",
        title="t",
        working_dir="/tmp/wd",
        model="sonnet",
    )
    return row.id


async def test_append_then_load_round_trip(conn: aiosqlite.Connection) -> None:
    """A batch of entries appended round-trips through ``load`` unchanged."""
    sid = await _make_session(conn)
    batch = [
        {"type": "user", "uuid": "u-1", "content": "hello"},
        {"type": "assistant", "uuid": "u-2", "content": "hi"},
    ]
    await sdk_entries_db.append(conn, session_id=sid, entries=batch)
    loaded = await sdk_entries_db.load(conn, session_id=sid)
    assert loaded == batch


async def test_append_assigns_monotonic_seq(conn: aiosqlite.Connection) -> None:
    """Sequential appends carry monotonically-increasing ``seq`` per session."""
    sid = await _make_session(conn)
    await sdk_entries_db.append(conn, session_id=sid, entries=[{"type": "a"}])
    await sdk_entries_db.append(conn, session_id=sid, entries=[{"type": "b"}, {"type": "c"}])
    cursor = await conn.execute(
        "SELECT seq, entry_json FROM sdk_session_entries WHERE session_id = ? ORDER BY seq ASC",
        (sid,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    assert [int(r[0]) for r in rows] == [0, 1, 2]


async def test_load_returns_oldest_first(conn: aiosqlite.Connection) -> None:
    """``load`` orders by seq ascending so subscribers see write order."""
    sid = await _make_session(conn)
    for marker in ("a", "b", "c", "d"):
        await sdk_entries_db.append(
            conn, session_id=sid, entries=[{"type": marker, "uuid": marker}]
        )
    loaded = await sdk_entries_db.load(conn, session_id=sid)
    assert [e["type"] for e in loaded] == ["a", "b", "c", "d"]


async def test_load_empty_session_returns_empty_list(
    conn: aiosqlite.Connection,
) -> None:
    """A session with no entries returns ``[]`` (the adapter translates to ``None``)."""
    sid = await _make_session(conn)
    loaded = await sdk_entries_db.load(conn, session_id=sid)
    assert loaded == []


async def test_count_for_session_is_zero_when_empty(
    conn: aiosqlite.Connection,
) -> None:
    """``count_for_session`` returns 0 for sessions with no entries."""
    sid = await _make_session(conn)
    assert await sdk_entries_db.count_for_session(conn, session_id=sid) == 0


async def test_count_for_session_after_append(
    conn: aiosqlite.Connection,
) -> None:
    """``count_for_session`` reflects the number of appended entries."""
    sid = await _make_session(conn)
    await sdk_entries_db.append(
        conn,
        session_id=sid,
        entries=[{"type": "a"}, {"type": "b"}, {"type": "c"}],
    )
    assert await sdk_entries_db.count_for_session(conn, session_id=sid) == 3


async def test_per_session_isolation(conn: aiosqlite.Connection) -> None:
    """Entries on one session don't appear in another session's load."""
    sid_a = await _make_session(conn)
    sid_b = await _make_session(conn)
    await sdk_entries_db.append(conn, session_id=sid_a, entries=[{"type": "for-a"}])
    await sdk_entries_db.append(conn, session_id=sid_b, entries=[{"type": "for-b"}])
    loaded_a = await sdk_entries_db.load(conn, session_id=sid_a)
    loaded_b = await sdk_entries_db.load(conn, session_id=sid_b)
    assert loaded_a == [{"type": "for-a"}]
    assert loaded_b == [{"type": "for-b"}]


async def test_empty_batch_is_no_op(conn: aiosqlite.Connection) -> None:
    """An empty batch causes no DB writes and no errors."""
    sid = await _make_session(conn)
    await sdk_entries_db.append(conn, session_id=sid, entries=[])
    assert await sdk_entries_db.count_for_session(conn, session_id=sid) == 0


async def test_delete_for_session_removes_entries(
    conn: aiosqlite.Connection,
) -> None:
    """``delete_for_session`` clears all rows and returns the count."""
    sid = await _make_session(conn)
    await sdk_entries_db.append(
        conn,
        session_id=sid,
        entries=[{"type": "a"}, {"type": "b"}],
    )
    deleted = await sdk_entries_db.delete_for_session(conn, session_id=sid)
    assert deleted == 2
    assert await sdk_entries_db.count_for_session(conn, session_id=sid) == 0


async def test_delete_for_session_on_empty_returns_zero(
    conn: aiosqlite.Connection,
) -> None:
    """Deleting on a session with no entries returns 0."""
    sid = await _make_session(conn)
    deleted = await sdk_entries_db.delete_for_session(conn, session_id=sid)
    assert deleted == 0


async def test_session_delete_cascades_to_entries(
    conn: aiosqlite.Connection,
) -> None:
    """The schema's ``ON DELETE CASCADE`` drops mirror rows when the session is deleted."""
    sid = await _make_session(conn)
    await sdk_entries_db.append(conn, session_id=sid, entries=[{"type": "a"}, {"type": "b"}])
    await conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    await conn.commit()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM sdk_session_entries WHERE session_id = ?", (sid,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    assert row is not None
    assert int(row[0]) == 0


async def test_unicode_entries_round_trip(conn: aiosqlite.Connection) -> None:
    """Non-ASCII content survives the JSON round trip."""
    sid = await _make_session(conn)
    batch = [{"type": "user", "content": "héllo — 日本語 — 🚀"}]
    await sdk_entries_db.append(conn, session_id=sid, entries=batch)
    loaded = await sdk_entries_db.load(conn, session_id=sid)
    assert loaded == batch
