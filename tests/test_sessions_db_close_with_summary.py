"""Tests for ``bearings.db.sessions.close_with_summary``.

Backs the ``close_session`` MCP tool's persistence layer. Coverage:

* Stamps ``closed_at`` + ``closing_summary`` in the same transaction.
* Idempotent on a row that's already closed (returns ``None`` rather
  than overwriting).
* Returns ``None`` for a missing session.
* Validates summary bounds at the DB-helper layer (defence in depth
  for any direct caller bypassing the MCP tool).
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from bearings.config.constants import (
    SESSION_CLOSING_SUMMARY_MAX_LENGTH,
    SESSION_CLOSING_SUMMARY_MIN_LENGTH,
    SESSION_KIND_CHAT,
)
from bearings.db import sessions as sessions_db
from bearings.db.connection import load_schema


@pytest.fixture
async def conn(tmp_path: Path):
    db_path = tmp_path / "test.db"
    async with aiosqlite.connect(db_path) as connection:
        await load_schema(connection)
        yield connection


async def test_close_with_summary_stamps_both_fields(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/wd",
        model="sonnet",
    )
    summary = "Implemented the feature and verified the gate."

    closed = await sessions_db.close_with_summary(conn, session.id, summary=summary)

    assert closed is not None
    assert closed.id == session.id
    assert closed.closed_at is not None
    assert closed.closing_summary == summary


async def test_close_with_summary_is_idempotent_on_already_closed(
    conn: aiosqlite.Connection,
) -> None:
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/wd",
        model="sonnet",
    )
    first = await sessions_db.close_with_summary(conn, session.id, summary="first close")
    assert first is not None

    # Second call must not overwrite.
    second = await sessions_db.close_with_summary(conn, session.id, summary="LATER edit")

    assert second is None
    refreshed = await sessions_db.get(conn, session.id)
    assert refreshed is not None
    assert refreshed.closing_summary == "first close"


async def test_close_with_summary_returns_none_for_missing(conn: aiosqlite.Connection) -> None:
    result = await sessions_db.close_with_summary(conn, "ses_missing", summary="should not land")
    assert result is None


async def test_close_with_summary_rejects_empty(conn: aiosqlite.Connection) -> None:
    with pytest.raises(ValueError, match=str(SESSION_CLOSING_SUMMARY_MIN_LENGTH)):
        await sessions_db.close_with_summary(conn, "ses_x", summary="")


async def test_close_with_summary_rejects_oversized(conn: aiosqlite.Connection) -> None:
    oversized = "y" * (SESSION_CLOSING_SUMMARY_MAX_LENGTH + 1)
    with pytest.raises(ValueError, match=str(SESSION_CLOSING_SUMMARY_MAX_LENGTH)):
        await sessions_db.close_with_summary(conn, "ses_x", summary=oversized)
