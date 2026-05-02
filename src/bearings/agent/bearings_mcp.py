# mypy: disable-error-code=explicit-any
"""Bearings-internal MCP tools — exposed to the agent via in-process MCP server.

Per ``docs/architecture-v1.md`` §1.1.4 + Slice B of
``~/.claude/plans/unblocking-v1-dogfood.md``: the agent calls
:func:`close_session` when it judges the user's task complete and
provides a 1-3 sentence ``summary``. The tool persists ``closed_at`` +
``closing_summary`` via :func:`bearings.db.sessions.close_with_summary`.

Two shape decisions worth naming:

* **The session id is closure-captured, never on the tool input.**
  :class:`CloseSessionDeps` carries the calling session's id; the
  agent cannot pass a sibling session's id through tool input and
  close it. Server-side resolution is the only safety surface that
  defends against a confused (or compromised) agent attempting to
  reach across sessions.
* **``Any`` carve-out at file scope.** The SDK's ``@tool`` decorator
  and ``SdkMcpTool`` shape expose ``Any`` (input schema, args dict,
  result dict) — same architectural pressure as the Pydantic
  metaclass surface in :mod:`bearings.agent.events`. Restricting the
  pragma to this single boundary file keeps the carve-out narrow.

Wire-shape:

* Tool name: :data:`bearings.config.constants.CLOSE_SESSION_TOOL_NAME`
  (``close_session``). Server name:
  :data:`bearings.config.constants.BEARINGS_MCP_SERVER_NAME`
  (``bearings``). Together these compose the agent-facing handle
  ``mcp__bearings__close_session``.
* Parameter shape: ``{"summary": str}``. Bounds are
  :data:`bearings.config.constants.SESSION_CLOSING_SUMMARY_MIN_LENGTH`
  / ``..._MAX_LENGTH`` and are validated both client-side here AND
  again at the DB-helper layer (defence in depth).

System-prompt augmentation:
:data:`CLOSE_SESSION_INSTRUCTION` is the text the SDK system-prompt
assembler (item 1.3+) appends so the agent knows **when** to call the
tool. Owned here so a future tweak to the instruction does not
require a cross-module diff hunt.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiosqlite
from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from bearings.config.constants import (
    BEARINGS_MCP_SERVER_NAME,
    CLOSE_SESSION_TOOL_NAME,
    SESSION_CLOSING_SUMMARY_MAX_LENGTH,
    SESSION_CLOSING_SUMMARY_MIN_LENGTH,
)
from bearings.db import sessions as sessions_db

# Human-readable description the agent reads to decide when to call.
# The SDK exposes this verbatim as the tool's MCP ``description`` so
# Claude's tool-selection rationale gets the same text the operator
# reads in the system prompt — keeping both in sync via one source.
CLOSE_SESSION_DESCRIPTION: str = (
    "Close the current Bearings session and record a 1-3 sentence "
    "summary of what was accomplished. Call this when you judge the "
    "user's task complete; do not pre-announce the call. The user "
    "can reopen the session if you misjudge."
)


# System-prompt instruction the SDK options assembler (item 1.3+)
# appends to the executor's system prompt. The agent-facing handle
# ``mcp__bearings__close_session`` is rendered from constants so a
# server- or tool-name change cannot drift the instruction text.
CLOSE_SESSION_INSTRUCTION: str = (
    f"When you judge the user's current task complete, call the "
    f"`mcp__{BEARINGS_MCP_SERVER_NAME}__{CLOSE_SESSION_TOOL_NAME}` "
    "tool with a 1-3 sentence `summary` of what you accomplished. "
    "Don't pre-announce the call; just invoke the tool. The session "
    "id is resolved server-side from your runtime context — do not "
    "attempt to pass one. The user can reopen the session if you "
    "misjudge."
)


@dataclass(frozen=True)
class CloseSessionDeps:
    """Runtime dependencies for the ``close_session`` tool.

    The :attr:`session_id` is closure-captured so the tool cannot
    target a sibling session no matter what the agent passes (or
    fails to pass) on the input shape.

    :attr:`db_factory` is an async callable that yields the live
    :class:`aiosqlite.Connection` the tool persists through. The MCP
    server runs in-process inside the FastAPI app so the factory is
    typically a lambda capturing ``request.app.state.db_connection``;
    tests pass an explicit factory pointing at a tmp-db.
    """

    session_id: str
    db_factory: Callable[[], Awaitable[aiosqlite.Connection]]

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("CloseSessionDeps.session_id must be non-empty")


def make_close_session_tool(deps: CloseSessionDeps) -> SdkMcpTool[Any]:
    """Build the ``close_session`` :class:`SdkMcpTool` bound to ``deps``.

    Returned as an :class:`SdkMcpTool` so call sites (the MCP server
    factory below, plus tests that exercise the handler directly via
    ``tool_obj.handler({"summary": ...})``) can both reach it.

    The handler returns the SDK's standard tool-result shape:

    * Success — ``{"content": [{"type": "text", "text": "..."}]}``
      describing the row that was just closed.
    * Failure — same shape with ``"is_error": True`` and a
      human-readable message in the text body. The SDK fans this back
      to the agent so the model can react (e.g. apologise + continue
      the conversation rather than retrying).

    Validation strategy: the tool guards bounds + type at the input
    boundary so a malformed input never reaches the DB helper. The DB
    helper's own ``ValueError`` is therefore unreachable from a
    well-formed agent call — it remains as defence-in-depth for any
    direct caller bypassing the MCP layer.
    """

    @tool(
        CLOSE_SESSION_TOOL_NAME,
        CLOSE_SESSION_DESCRIPTION,
        {"summary": str},
    )
    async def close_session(args: dict[str, Any]) -> dict[str, Any]:
        raw = args.get("summary")
        if not isinstance(raw, str):
            return _error_result("summary must be a string")
        summary = raw
        length = len(summary)
        if length < SESSION_CLOSING_SUMMARY_MIN_LENGTH:
            return _error_result(
                f"summary must be at least "
                f"{SESSION_CLOSING_SUMMARY_MIN_LENGTH} character(s); got {length}"
            )
        if length > SESSION_CLOSING_SUMMARY_MAX_LENGTH:
            return _error_result(
                f"summary must be at most "
                f"{SESSION_CLOSING_SUMMARY_MAX_LENGTH} characters; got {length}"
            )
        connection = await deps.db_factory()
        row = await sessions_db.close_with_summary(
            connection,
            deps.session_id,
            summary=summary,
        )
        if row is None:
            return _error_result(
                f"session {deps.session_id!r} is missing or already closed; "
                "the prior close stays canonical"
            )
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Closed session {row.id} at {row.closed_at}; "
                        f"summary persisted ({length} chars)."
                    ),
                }
            ]
        }

    return close_session


def build_bearings_mcp_server(deps: CloseSessionDeps) -> McpSdkServerConfig:
    """Build the in-process MCP server exposing every Bearings-internal tool.

    Today the server exposes only :func:`close_session`; future tools
    register the same way (factory function, append to the ``tools``
    list). The server name is
    :data:`bearings.config.constants.BEARINGS_MCP_SERVER_NAME` —
    agent-facing handles render as
    ``mcp__<BEARINGS_MCP_SERVER_NAME>__<tool>``.
    """
    return create_sdk_mcp_server(
        name=BEARINGS_MCP_SERVER_NAME,
        tools=[make_close_session_tool(deps)],
    )


def _error_result(message: str) -> dict[str, Any]:
    """Build the SDK's standard error-result shape from a human message."""
    return {
        "content": [{"type": "text", "text": message}],
        "is_error": True,
    }


__all__ = [
    "CLOSE_SESSION_DESCRIPTION",
    "CLOSE_SESSION_INSTRUCTION",
    "CloseSessionDeps",
    "build_bearings_mcp_server",
    "make_close_session_tool",
]
