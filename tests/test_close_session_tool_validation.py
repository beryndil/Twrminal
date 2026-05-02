"""Input-validation tests for the ``close_session`` MCP tool.

Per Slice B5 of ``~/.claude/plans/unblocking-v1-dogfood.md``: an
empty summary, an over-cap summary, a non-string summary, and a
missing-key payload must all surface as ``is_error`` results — never
as ``ValueError`` propagated up to the SDK runtime, and never as
silent successful closes.

The tool is the boundary; if these checks fail the agent could close
sessions with degenerate metadata, defeating the "what did the agent
think it finished" sidebar tooltip.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.bearings_mcp import (
    CloseSessionDeps,
    make_close_session_tool,
)
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


def _factory(connection: aiosqlite.Connection) -> Callable[[], Awaitable[aiosqlite.Connection]]:
    async def get_connection() -> aiosqlite.Connection:
        return connection

    return get_connection


async def _make_tool_for_open_session(conn: aiosqlite.Connection):
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="open",
        working_dir="/wd",
        model="sonnet",
    )
    deps = CloseSessionDeps(session_id=session.id, db_factory=_factory(conn))
    return session, make_close_session_tool(deps)


async def test_empty_summary_rejected(conn: aiosqlite.Connection) -> None:
    session, tool_obj = await _make_tool_for_open_session(conn)

    result = await tool_obj.handler({"summary": ""})

    assert result.get("is_error") is True
    text = _first_text(result)
    assert "at least" in text
    assert str(SESSION_CLOSING_SUMMARY_MIN_LENGTH) in text

    refreshed = await sessions_db.get(conn, session.id)
    assert refreshed is not None
    assert refreshed.closed_at is None  # session must remain open
    assert refreshed.closing_summary is None


async def test_over_cap_summary_rejected(conn: aiosqlite.Connection) -> None:
    session, tool_obj = await _make_tool_for_open_session(conn)

    oversized = "x" * (SESSION_CLOSING_SUMMARY_MAX_LENGTH + 1)
    result = await tool_obj.handler({"summary": oversized})

    assert result.get("is_error") is True
    text = _first_text(result)
    assert "at most" in text
    assert str(SESSION_CLOSING_SUMMARY_MAX_LENGTH) in text

    refreshed = await sessions_db.get(conn, session.id)
    assert refreshed is not None
    assert refreshed.closed_at is None
    assert refreshed.closing_summary is None


async def test_summary_at_exact_max_length_accepted(conn: aiosqlite.Connection) -> None:
    """The boundary value (max length, exact match) is accepted."""
    session, tool_obj = await _make_tool_for_open_session(conn)

    boundary = "x" * SESSION_CLOSING_SUMMARY_MAX_LENGTH
    result = await tool_obj.handler({"summary": boundary})

    assert result.get("is_error") is not True
    refreshed = await sessions_db.get(conn, session.id)
    assert refreshed is not None
    assert refreshed.closed_at is not None
    assert refreshed.closing_summary == boundary


async def test_non_string_summary_rejected(conn: aiosqlite.Connection) -> None:
    """A wrong-type summary surfaces as a tool error, not a server crash."""
    session, tool_obj = await _make_tool_for_open_session(conn)

    # Pretend the agent sent a number — the SDK input shape says ``str``
    # but we defend at runtime so a malformed call cannot reach the DB.
    result = await tool_obj.handler({"summary": 42})

    assert result.get("is_error") is True
    assert "must be a string" in _first_text(result)

    refreshed = await sessions_db.get(conn, session.id)
    assert refreshed is not None
    assert refreshed.closed_at is None


async def test_missing_summary_key_rejected(conn: aiosqlite.Connection) -> None:
    """A payload that lacks the summary key surfaces the same error."""
    session, tool_obj = await _make_tool_for_open_session(conn)

    result = await tool_obj.handler({})

    assert result.get("is_error") is True
    assert "must be a string" in _first_text(result)

    refreshed = await sessions_db.get(conn, session.id)
    assert refreshed is not None
    assert refreshed.closed_at is None


async def test_close_session_deps_rejects_empty_session_id() -> None:
    """The deps carrier validates session_id at construction."""
    with pytest.raises(ValueError, match="session_id must be non-empty"):
        CloseSessionDeps(session_id="", db_factory=_unused_factory())


def _unused_factory() -> Callable[[], Awaitable[aiosqlite.Connection]]:
    async def _never() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError("validation should fail before factory call")

    return _never


def _first_text(result: dict[str, object]) -> str:
    content = result.get("content")
    assert isinstance(content, list) and content
    block = content[0]
    assert isinstance(block, dict)
    text = block.get("text")
    assert isinstance(text, str)
    return text
