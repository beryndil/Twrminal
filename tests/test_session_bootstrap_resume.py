"""Resume / first-spawn wiring tests for :func:`build_session_setup`.

The bootstrap chooses between two SDK option shapes based on whether
the session has prior SDK transcript entries in ``sdk_session_entries``:

* **First spawn** (no entries): pass ``sdk_session_id=<uuid>`` to pin
  the CLI's session UUID. The store starts collecting entries as the
  turn runs.
* **Subsequent spawn** (entries present): pass ``resume=<uuid>``. The
  SDK calls ``store.load`` to materialise the JSONL, the CLI starts
  with ``--resume <uuid>``, and the new subprocess inherits the full
  conversation context.

These tests exercise the bootstrap directly with a stubbed approval
broker disabled and inspect the returned :class:`SessionSetup.options`
to verify the right kwargs are populated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.runner import SessionRunner
from bearings.agent.sdk_session_id import bearings_to_sdk_uuid
from bearings.agent.session_bootstrap import build_session_setup
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


async def _make_chat_session(conn: aiosqlite.Connection) -> str:
    row = await sessions_db.create(
        conn,
        kind="chat",
        title="t",
        working_dir="/tmp/wd",
        model="sonnet",
    )
    return row.id


async def test_first_spawn_uses_sdk_session_id_not_resume(
    conn: aiosqlite.Connection,
) -> None:
    """Fresh session — bootstrap pins ``sdk_session_id``, leaves ``resume`` None."""
    sid = await _make_chat_session(conn)
    runner = SessionRunner(sid)
    setup_fn = build_session_setup(conn, enable_approval_broker=False)

    setup = await setup_fn(sid, runner)
    assert setup is not None
    options = setup.options
    expected_uuid = bearings_to_sdk_uuid(sid)
    assert options.sdk_session_id == expected_uuid
    assert options.resume is None
    assert isinstance(options.session_store, BearingsSessionStore)


async def test_subsequent_spawn_uses_resume_not_sdk_session_id(
    conn: aiosqlite.Connection,
) -> None:
    """Session with prior entries — bootstrap pins ``resume``, leaves ``sdk_session_id`` None."""
    sid = await _make_chat_session(conn)
    # Simulate a prior turn having written transcript entries.
    await sdk_entries_db.append(
        conn,
        session_id=sid,
        entries=[{"type": "user", "uuid": "u-1", "content": "hi"}],
    )

    runner = SessionRunner(sid)
    setup_fn = build_session_setup(conn, enable_approval_broker=False)

    setup = await setup_fn(sid, runner)
    assert setup is not None
    options = setup.options
    expected_uuid = bearings_to_sdk_uuid(sid)
    assert options.resume == expected_uuid
    assert options.sdk_session_id is None
    assert isinstance(options.session_store, BearingsSessionStore)


async def test_session_store_is_always_set_for_chat_sessions(
    conn: aiosqlite.Connection,
) -> None:
    """The session_store adapter is wired regardless of first/subsequent spawn."""
    sid_fresh = await _make_chat_session(conn)
    sid_resumed = await _make_chat_session(conn)
    await sdk_entries_db.append(
        conn,
        session_id=sid_resumed,
        entries=[{"type": "x"}],
    )

    setup_fn = build_session_setup(conn, enable_approval_broker=False)
    fresh_setup = await setup_fn(sid_fresh, SessionRunner(sid_fresh))
    resumed_setup = await setup_fn(sid_resumed, SessionRunner(sid_resumed))

    assert fresh_setup is not None
    assert resumed_setup is not None
    assert isinstance(fresh_setup.options.session_store, BearingsSessionStore)
    assert isinstance(resumed_setup.options.session_store, BearingsSessionStore)


async def test_missing_session_returns_none(
    conn: aiosqlite.Connection,
) -> None:
    """Bootstrap returns ``None`` for a session row that doesn't exist."""
    setup_fn = build_session_setup(conn, enable_approval_broker=False)
    setup = await setup_fn("ses_doesnotexist000000000000000000", SessionRunner("ses_x"))
    assert setup is None
