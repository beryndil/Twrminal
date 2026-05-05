# mypy: disable-error-code=explicit-any
"""Unit tests for :class:`bearings.agent.session_store.BearingsSessionStore`.

The adapter bridges the SDK's :class:`SessionStore` Protocol to the
Bearings DB-backed mirror table. Tests verify:

* ``append`` translates the SDK's UUID-form ``key.session_id`` back to
  the Bearings ``ses_<hex>`` id and writes via :func:`bearings.db.sdk_entries.append`.
* ``load`` returns ``None`` when the session has no entries (SDK
  contract: ``None`` == "never written").
* ``load`` returns the parsed entry list when the session has entries.
* Subagent batches (``key`` carries ``subpath``) are dropped silently
  per the v1 deferral.
* End-to-end round trip — append-then-load via the adapter yields the
  original entries.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from bearings.agent.sdk_session_id import bearings_to_sdk_uuid
from bearings.agent.session_store import BearingsSessionStore
from bearings.db import sdk_entries as sdk_entries_db
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema


@pytest.fixture
async def conn(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute("PRAGMA foreign_keys = ON")
        await load_schema(connection)
        yield connection


async def _make_session(conn: aiosqlite.Connection) -> str:
    row = await sessions_db.create(
        conn,
        kind="chat",
        title="t",
        working_dir="/tmp/wd",
        model="sonnet",
    )
    return row.id


def _make_store(conn: aiosqlite.Connection) -> BearingsSessionStore:
    """Build a store closure-capturing a single connection."""

    async def db_factory() -> aiosqlite.Connection:
        return conn

    return BearingsSessionStore(db_factory=db_factory)


async def test_append_writes_via_dbf(conn: aiosqlite.Connection) -> None:
    """``store.append`` writes entries to the DB under the Bearings session id."""
    sid = await _make_session(conn)
    sdk_uuid = bearings_to_sdk_uuid(sid)
    store = _make_store(conn)
    batch: list[dict[str, Any]] = [
        {"type": "user", "uuid": "u-1", "content": "hi"},
    ]
    await store.append({"project_key": "/tmp/wd", "session_id": sdk_uuid}, batch)
    loaded = await sdk_entries_db.load(conn, session_id=sid)
    assert loaded == batch


async def test_load_returns_none_when_empty(conn: aiosqlite.Connection) -> None:
    """SDK contract: ``None`` (not ``[]``) signals 'never written'."""
    sid = await _make_session(conn)
    sdk_uuid = bearings_to_sdk_uuid(sid)
    store = _make_store(conn)
    result = await store.load({"project_key": "/tmp/wd", "session_id": sdk_uuid})
    assert result is None


async def test_load_returns_entries_when_present(conn: aiosqlite.Connection) -> None:
    """When entries exist, ``load`` returns them in write order."""
    sid = await _make_session(conn)
    sdk_uuid = bearings_to_sdk_uuid(sid)
    batch: list[dict[str, Any]] = [
        {"type": "a", "uuid": "u-a"},
        {"type": "b", "uuid": "u-b"},
    ]
    await sdk_entries_db.append(conn, session_id=sid, entries=batch)
    store = _make_store(conn)
    result = await store.load({"project_key": "/tmp/wd", "session_id": sdk_uuid})
    assert result == batch


async def test_subagent_batch_dropped_on_append(
    conn: aiosqlite.Connection,
) -> None:
    """Batches with ``subpath`` set are silently dropped (v1 deferral)."""
    sid = await _make_session(conn)
    sdk_uuid = bearings_to_sdk_uuid(sid)
    store = _make_store(conn)
    batch: list[dict[str, Any]] = [{"type": "user", "uuid": "u-sub"}]
    await store.append(
        {
            "project_key": "/tmp/wd",
            "session_id": sdk_uuid,
            "subpath": "subagents/agent-x",
        },
        batch,
    )
    # No write happened — main-transcript count stays zero.
    assert await sdk_entries_db.count_for_session(conn, session_id=sid) == 0


async def test_subagent_load_returns_none(conn: aiosqlite.Connection) -> None:
    """Subagent ``load`` calls also short-circuit to ``None``."""
    sid = await _make_session(conn)
    sdk_uuid = bearings_to_sdk_uuid(sid)
    # Even with main-transcript entries present, a subagent key returns None.
    await sdk_entries_db.append(conn, session_id=sid, entries=[{"type": "main"}])
    store = _make_store(conn)
    result = await store.load(
        {
            "project_key": "/tmp/wd",
            "session_id": sdk_uuid,
            "subpath": "subagents/agent-x",
        }
    )
    assert result is None


async def test_round_trip_via_adapter(conn: aiosqlite.Connection) -> None:
    """``append`` then ``load`` via the adapter yields the original entries."""
    sid = await _make_session(conn)
    sdk_uuid = bearings_to_sdk_uuid(sid)
    store = _make_store(conn)
    batch: list[dict[str, Any]] = [
        {"type": "user", "uuid": f"u-{i}", "content": f"msg-{i}"} for i in range(5)
    ]
    key = {"project_key": "/tmp/wd", "session_id": sdk_uuid}
    await store.append(key, batch)
    result = await store.load(key)
    assert result == batch


async def test_empty_batch_append_is_safe(conn: aiosqlite.Connection) -> None:
    """An empty append batch is a no-op; subsequent load still returns None."""
    sid = await _make_session(conn)
    sdk_uuid = bearings_to_sdk_uuid(sid)
    store = _make_store(conn)
    await store.append({"project_key": "/tmp/wd", "session_id": sdk_uuid}, [])
    result = await store.load({"project_key": "/tmp/wd", "session_id": sdk_uuid})
    assert result is None
