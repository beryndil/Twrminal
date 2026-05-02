"""Happy-path + idempotency tests for the ``close_session`` MCP tool.

Per Slice B5 of ``~/.claude/plans/unblocking-v1-dogfood.md``:

* Invoking the tool with a valid summary stamps ``closed_at`` and
  persists ``closing_summary``.
* A second invocation on the same session is a no-op (returns the
  ``is_error`` shape rather than overwriting the prior summary).

Tests reach through the SDK's ``SdkMcpTool.handler`` attribute so the
handler runs in-process without booting an SDK subprocess. The
session id closure pin is exercised here too — every assertion
confirms the row that *got* closed matches the deps-bound id, never
some other id sourced from input.
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
    BEARINGS_MCP_SERVER_NAME,
    CLOSE_SESSION_TOOL_NAME,
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


async def test_tool_metadata_uses_constants() -> None:
    """Tool name + description come from the constants module."""
    deps = CloseSessionDeps(session_id="ses_test", db_factory=_factory_for_id())
    tool_obj = make_close_session_tool(deps)
    assert tool_obj.name == CLOSE_SESSION_TOOL_NAME
    # Description is the agent-facing rationale; non-empty assertion
    # is enough — the exact wording is product copy.
    assert tool_obj.description
    # Schema declares ``summary: str`` and nothing else.
    assert tool_obj.input_schema == {"summary": str}


async def test_close_with_valid_summary_stamps_closed_at_and_summary(
    conn: aiosqlite.Connection,
) -> None:
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="needs closing",
        working_dir="/tmp/wd",
        model="sonnet",
    )
    deps = CloseSessionDeps(session_id=session.id, db_factory=_factory(conn))
    tool_obj = make_close_session_tool(deps)

    summary = "Implemented feature X and verified the gate set."
    result = await tool_obj.handler({"summary": summary})

    assert result.get("is_error") is not True
    text = _first_text(result)
    assert session.id in text
    assert "Closed session" in text

    refreshed = await sessions_db.get(conn, session.id)
    assert refreshed is not None
    assert refreshed.closed_at is not None
    assert refreshed.closing_summary == summary


async def test_second_close_is_idempotent_no_op(conn: aiosqlite.Connection) -> None:
    """Re-calling close_session never overwrites the prior summary."""
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="t",
        working_dir="/wd",
        model="sonnet",
    )
    deps = CloseSessionDeps(session_id=session.id, db_factory=_factory(conn))
    tool_obj = make_close_session_tool(deps)

    first = await tool_obj.handler({"summary": "First close — canonical."})
    assert first.get("is_error") is not True

    after_first = await sessions_db.get(conn, session.id)
    assert after_first is not None
    canonical_closed_at = after_first.closed_at
    canonical_summary = after_first.closing_summary

    second = await tool_obj.handler({"summary": "Second attempt — should not land."})
    assert second.get("is_error") is True
    assert "missing or already closed" in _first_text(second)

    after_second = await sessions_db.get(conn, session.id)
    assert after_second is not None
    assert after_second.closed_at == canonical_closed_at
    assert after_second.closing_summary == canonical_summary


async def test_close_returns_error_when_session_missing(conn: aiosqlite.Connection) -> None:
    deps = CloseSessionDeps(session_id="ses_does_not_exist", db_factory=_factory(conn))
    tool_obj = make_close_session_tool(deps)

    result = await tool_obj.handler({"summary": "Nothing to close."})

    assert result.get("is_error") is True
    assert "missing or already closed" in _first_text(result)


async def test_server_name_and_tool_handle_match_constants() -> None:
    """The agent-facing handle is ``mcp__<server>__<tool>``."""
    from bearings.agent.bearings_mcp import build_bearings_mcp_server

    deps = CloseSessionDeps(session_id="ses_x", db_factory=_factory_for_id())
    server_config = build_bearings_mcp_server(deps)
    assert server_config["type"] == "sdk"
    assert server_config["name"] == BEARINGS_MCP_SERVER_NAME


def _factory_for_id() -> Callable[[], Awaitable[aiosqlite.Connection]]:
    """A factory that never yields a real connection — for metadata-only tests."""

    async def _never_called() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError("metadata-only test should not invoke the factory")

    return _never_called


def _first_text(result: dict[str, object]) -> str:
    """Pull the first text block out of an SDK tool result."""
    content = result.get("content")
    assert isinstance(content, list) and content
    block = content[0]
    assert isinstance(block, dict)
    text = block.get("text")
    assert isinstance(text, str)
    return text
