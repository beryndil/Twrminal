"""Session-isolation guard for the ``close_session`` MCP tool.

Per Slice B5 of ``~/.claude/plans/unblocking-v1-dogfood.md``: the
agent must NOT be able to close a session other than the one its
runtime context is bound to. Server-side resolution from
:class:`bearings.agent.bearings_mcp.CloseSessionDeps` is the only
defence — the tool's input schema deliberately exposes no session-id
parameter, so a confused agent cannot even attempt a cross-session
close through legitimate channels.

These tests confirm the pin:

* The deps-bound session is the only row that gets closed, even when
  another session exists in the same DB.
* An adversarial extra ``session_id`` field on the input dict is
  silently ignored — the closure pin wins.
* The tool's input schema declares only ``summary``, so the SDK won't
  forward any agent-attempted ``session_id`` field downstream.
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
from bearings.config.constants import SESSION_KIND_CHAT
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


async def test_only_deps_session_is_closed_other_rows_untouched(
    conn: aiosqlite.Connection,
) -> None:
    """Closing session A leaves session B open, and vice versa."""
    bound = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="bound",
        working_dir="/wd",
        model="sonnet",
    )
    sibling = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="sibling",
        working_dir="/wd",
        model="sonnet",
    )

    deps = CloseSessionDeps(session_id=bound.id, db_factory=_factory(conn))
    tool_obj = make_close_session_tool(deps)

    result = await tool_obj.handler({"summary": "Done."})
    assert result.get("is_error") is not True

    bound_after = await sessions_db.get(conn, bound.id)
    sibling_after = await sessions_db.get(conn, sibling.id)
    assert bound_after is not None and bound_after.closed_at is not None
    assert sibling_after is not None and sibling_after.closed_at is None


async def test_adversarial_session_id_in_input_is_ignored(
    conn: aiosqlite.Connection,
) -> None:
    """Even if the agent smuggles a ``session_id`` field, the closure wins."""
    bound = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="bound",
        working_dir="/wd",
        model="sonnet",
    )
    target = await sessions_db.create(
        conn,
        kind=SESSION_KIND_CHAT,
        title="target",
        working_dir="/wd",
        model="sonnet",
    )

    deps = CloseSessionDeps(session_id=bound.id, db_factory=_factory(conn))
    tool_obj = make_close_session_tool(deps)

    # Adversarial payload — agent tries to redirect the close at the
    # ``target`` session by piggybacking a session_id alongside the
    # legit summary. The handler must ignore the extra field.
    result = await tool_obj.handler(
        {
            "summary": "Done with the OTHER session.",
            "session_id": target.id,
        }
    )
    assert result.get("is_error") is not True

    bound_after = await sessions_db.get(conn, bound.id)
    target_after = await sessions_db.get(conn, target.id)
    assert bound_after is not None and bound_after.closed_at is not None
    assert target_after is not None and target_after.closed_at is None


async def test_input_schema_does_not_expose_session_id() -> None:
    """The tool's MCP-side schema declares only ``summary``."""
    deps = CloseSessionDeps(session_id="ses_x", db_factory=_unused_factory())
    tool_obj = make_close_session_tool(deps)
    schema = tool_obj.input_schema
    assert isinstance(schema, dict)
    assert set(schema.keys()) == {"summary"}


def _unused_factory() -> Callable[[], Awaitable[aiosqlite.Connection]]:
    async def _never() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError("schema-only test should not invoke the factory")

    return _never
