"""Tests for the ``bearings__get_tool_output`` MCP tool.

Exercises:
* Success path — known tool_use_id returns the persisted output.
* Missing tool_use_id — unknown id returns is_error.
* Cross-session isolation — a tool_call_id from another session returns is_error.
* Output capped — output exceeding cap_chars is truncated with the marker.
* Validation — non-string or empty tool_use_id returns is_error.

Tests reach the handler directly via ``tool_obj.handler(...)``; DB is a
real in-process aiosqlite so ``tool_calls.insert_batch`` + the retrieval
path are both exercised.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import aiosqlite
import pytest

from bearings.agent.bearings_mcp import GetToolOutputDeps, make_get_tool_output_tool
from bearings.config.constants import (
    DEFAULT_TOOL_OUTPUT_CAP_CHARS,
    GET_TOOL_OUTPUT_TOOL_NAME,
    SESSION_KIND_CHAT,
    STREAM_TRUNCATION_MARKER_TEMPLATE,
)
from bearings.db import sessions as sessions_db
from bearings.db import tool_calls as tool_calls_db
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


def _first_text(result: dict[str, object]) -> str:
    content = result.get("content")
    assert isinstance(content, list) and content
    block = content[0]
    assert isinstance(block, dict)
    text = block.get("text")
    assert isinstance(text, str)
    return text


async def _create_session_with_tool_call(
    conn: aiosqlite.Connection,
    *,
    tool_call_id: str,
    output: str,
) -> str:
    """Create a session + message + tool_call row; return session_id."""
    session = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="test",
        working_dir="/tmp",
        model="sonnet",
    )
    # Insert a minimal messages row so message_id FK is satisfiable.
    from bearings.db import messages as messages_db

    msg = await messages_db.insert_user(conn, session_id=session.id, content="q")
    await tool_calls_db.insert_batch(
        conn,
        session_id=session.id,
        message_id=msg.id,
        records=[
            tool_calls_db.ToolCallRecord(
                tool_call_id=tool_call_id,
                tool_name="Bash",
                input_json='{"command": "ls"}',
                output=output,
                ok=True,
                duration_ms=50,
                error_message=None,
            )
        ],
    )
    return session.id


async def test_tool_name_matches_constant() -> None:
    async def _unused() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError

    deps = GetToolOutputDeps(session_id="ses_x", db_factory=_unused)
    tool_obj = make_get_tool_output_tool(deps)
    assert tool_obj.name == GET_TOOL_OUTPUT_TOOL_NAME


async def test_tool_has_description() -> None:
    async def _unused() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError

    deps = GetToolOutputDeps(session_id="ses_x", db_factory=_unused)
    assert make_get_tool_output_tool(deps).description


async def test_tool_input_schema_has_tool_use_id() -> None:
    async def _unused() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError

    deps = GetToolOutputDeps(session_id="ses_x", db_factory=_unused)
    assert make_get_tool_output_tool(deps).input_schema == {"tool_use_id": str}


async def test_success_returns_persisted_output(conn: aiosqlite.Connection) -> None:
    tool_call_id = "toolu_01abc"
    expected_output = "total 8\n-rw-r--r-- 1 user group 100 Jan 1 README.md\n"
    session_id = await _create_session_with_tool_call(
        conn, tool_call_id=tool_call_id, output=expected_output
    )

    deps = GetToolOutputDeps(session_id=session_id, db_factory=_factory(conn))
    tool_obj = make_get_tool_output_tool(deps)
    result = await tool_obj.handler({"tool_use_id": tool_call_id})

    assert result.get("is_error") is not True
    assert _first_text(result) == expected_output


async def test_missing_tool_use_id_returns_error(conn: aiosqlite.Connection) -> None:
    """Unknown tool_use_id returns is_error."""
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    deps = GetToolOutputDeps(session_id=session.id, db_factory=_factory(conn))
    tool_obj = make_get_tool_output_tool(deps)
    result = await tool_obj.handler({"tool_use_id": "toolu_does_not_exist"})

    assert result.get("is_error") is True
    assert "no tool call" in _first_text(result).lower()


async def test_cross_session_isolation(conn: aiosqlite.Connection) -> None:
    """A tool_call_id from a different session is not accessible."""
    other_tool_call_id = "toolu_01other"
    _other_session_id = await _create_session_with_tool_call(
        conn, tool_call_id=other_tool_call_id, output="secret output"
    )
    # Create a second session and try to read the first session's tool call.
    my_session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="mine", working_dir="/tmp", model="sonnet"
    )
    deps = GetToolOutputDeps(session_id=my_session.id, db_factory=_factory(conn))
    tool_obj = make_get_tool_output_tool(deps)
    result = await tool_obj.handler({"tool_use_id": other_tool_call_id})

    assert result.get("is_error") is True
    # Must not leak the other session's output.
    assert "secret output" not in _first_text(result)


async def test_output_capped_at_cap_chars(conn: aiosqlite.Connection) -> None:
    """Output exceeding cap_chars is truncated and the marker appended."""
    long_output = "x" * 500
    tool_call_id = "toolu_01long"
    session_id = await _create_session_with_tool_call(
        conn, tool_call_id=tool_call_id, output=long_output
    )
    cap = 100
    deps = GetToolOutputDeps(session_id=session_id, db_factory=_factory(conn), cap_chars=cap)
    tool_obj = make_get_tool_output_tool(deps)
    result = await tool_obj.handler({"tool_use_id": tool_call_id})

    assert result.get("is_error") is not True
    text = _first_text(result)
    # Truncated body + marker must be present.
    elided = 500 - cap
    expected_marker = STREAM_TRUNCATION_MARKER_TEMPLATE.format(n=elided)
    assert expected_marker in text
    assert text.startswith("x" * cap)


async def test_non_string_tool_use_id_returns_error(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    deps = GetToolOutputDeps(session_id=session.id, db_factory=_factory(conn))
    tool_obj = make_get_tool_output_tool(deps)
    result = await tool_obj.handler({"tool_use_id": None})
    assert result.get("is_error") is True


async def test_empty_tool_use_id_returns_error(conn: aiosqlite.Connection) -> None:
    session = await sessions_db.create(
        conn, kind=SESSION_KIND_CHAT, title="t", working_dir="/tmp", model="sonnet"
    )
    deps = GetToolOutputDeps(session_id=session.id, db_factory=_factory(conn))
    tool_obj = make_get_tool_output_tool(deps)
    result = await tool_obj.handler({"tool_use_id": ""})
    assert result.get("is_error") is True


async def test_deps_rejects_empty_session_id() -> None:
    async def _unused() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError

    with pytest.raises(ValueError, match="session_id"):
        GetToolOutputDeps(session_id="", db_factory=_unused)


async def test_deps_rejects_nonpositive_cap_chars() -> None:
    async def _unused() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError

    with pytest.raises(ValueError, match="cap_chars"):
        GetToolOutputDeps(session_id="ses_x", db_factory=_unused, cap_chars=0)


async def test_default_cap_chars_matches_constant() -> None:
    async def _unused() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError

    deps = GetToolOutputDeps(session_id="ses_x", db_factory=_unused)
    assert deps.cap_chars == DEFAULT_TOOL_OUTPUT_CAP_CHARS
