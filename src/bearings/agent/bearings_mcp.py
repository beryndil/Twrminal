# mypy: disable-error-code=explicit-any
"""Bearings-internal MCP tools — exposed to the agent via in-process MCP server.

Per ``docs/architecture-v1.md`` §1.1.4 + Slice B of
``~/.claude/plans/unblocking-v1-dogfood.md``: the agent calls
:func:`close_session` when it judges the user's task complete and
provides a 1-3 sentence ``summary``. The tool persists ``closed_at`` +
``closing_summary`` via :func:`bearings.db.sessions.close_with_summary`.

Finding-003 adds three further tools that mirror the live v0.17.x MCP
surface agents depend on:

* ``bash`` — shell command execution; validates argv[0] against an
  allowlist, runs with a bounded timeout, kills on timeout, ``shell=False``
  always.  Reuses :mod:`bearings.agent.shell`'s :func:`validate_argv`
  machinery so there is no parallel allowlist implementation.
* ``dir_init`` — directory-context initialisation; dispatches to
  :func:`bearings.bearings_dir.onboarding.dir_init_body` (arch §1.1.6).
  This file is a thin shim only — the ritual logic lives in ``bearings_dir``.
* ``get_tool_output`` — large-output retrieval escape hatch; the agent
  passes a prior ``tool_use_id`` to fetch the full persisted output when
  the in-context runner cap truncated what was shown in-line.

``Any`` carve-out
-----------------
The SDK's ``@tool`` decorator and ``SdkMcpTool`` shape expose ``Any``
(input schema, args dict, result dict) — same architectural pressure as
the Pydantic metaclass surface in :mod:`bearings.agent.events`. The
pragma is restricted to this single boundary file.

Wire-shape
----------
Server name: :data:`bearings.config.constants.BEARINGS_MCP_SERVER_NAME`
(``bearings``). Tool names come from the constants module. Agent-facing
handles compose as ``mcp__<server>__<tool>``.

Layer isolation
---------------
``bearings_mcp.py`` may import ``bearings.agent.shell`` (same package)
and ``bearings.bearings_dir.onboarding`` (downward cross-package).
``bearings_dir.*`` must NOT import ``bearings.agent.*`` (arch §3 line 549).
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool
from claude_agent_sdk.types import McpSdkServerConfig

from bearings.agent.shell import ShellValidationError, validate_argv
from bearings.bearings_dir.onboarding import dir_init_body
from bearings.config.constants import (
    BASH_TOOL_DEFAULT_TIMEOUT_S,
    BASH_TOOL_NAME,
    BASH_TOOL_OUTPUT_MAX_CHARS,
    BEARINGS_MCP_SERVER_NAME,
    CLOSE_SESSION_TOOL_NAME,
    DEFAULT_TOOL_OUTPUT_CAP_CHARS,
    DIR_INIT_TOOL_NAME,
    GET_TOOL_OUTPUT_TOOL_NAME,
    SESSION_CLOSING_SUMMARY_MAX_LENGTH,
    SESSION_CLOSING_SUMMARY_MIN_LENGTH,
    STREAM_TRUNCATION_MARKER_TEMPLATE,
)
from bearings.db import sessions as sessions_db
from bearings.db import tool_calls as tool_calls_db

# ---------------------------------------------------------------------------
# close_session
# ---------------------------------------------------------------------------

# Human-readable description the agent reads to decide when to call.
CLOSE_SESSION_DESCRIPTION: str = (
    "Close the current Bearings session and record a 1-3 sentence "
    "summary of what was accomplished. Call this when you judge the "
    "user's task complete; do not pre-announce the call. The user "
    "can reopen the session if you misjudge."
)

# System-prompt instruction the SDK options assembler appends.
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
    :class:`aiosqlite.Connection` the tool persists through.
    """

    session_id: str
    db_factory: Callable[[], Awaitable[aiosqlite.Connection]]

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("CloseSessionDeps.session_id must be non-empty")


def make_close_session_tool(deps: CloseSessionDeps) -> SdkMcpTool[Any]:
    """Build the ``close_session`` :class:`SdkMcpTool` bound to ``deps``."""

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


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------

BASH_TOOL_DESCRIPTION: str = (
    "Execute a shell command in the session's working directory. "
    "Pass a command string exactly as you would type it at a shell "
    "prompt (e.g. ``uv run pytest -q`` or ``git status``). "
    "Returns combined stdout + stderr and the exit code. "
    "Commands that exceed the configured timeout are killed."
)


@dataclass(frozen=True)
class BashToolDeps:
    """Runtime dependencies for the ``bash`` MCP tool.

    :attr:`working_dir` is the CWD the subprocess inherits; typically
    the session's ``working_dir`` field.

    :attr:`allowed_commands` is the argv[0] allowlist validated by
    :func:`bearings.agent.shell.validate_argv`. An empty frozenset
    rejects every command; callers should pass
    :data:`bearings.config.constants.DEFAULT_BASH_TOOL_ALLOWED_COMMANDS`
    or a superset for a usable tool.

    :attr:`timeout_s` caps how long the subprocess may run; the child
    is killed on expiry.

    :attr:`output_max_chars` caps combined stdout+stderr before the
    result is returned; over-cap text is truncated tail-style.
    """

    working_dir: str
    allowed_commands: frozenset[str]
    timeout_s: float
    output_max_chars: int

    def __post_init__(self) -> None:
        if self.timeout_s <= 0:
            raise ValueError(f"BashToolDeps.timeout_s must be > 0 (got {self.timeout_s})")
        if self.output_max_chars <= 0:
            raise ValueError(
                f"BashToolDeps.output_max_chars must be > 0 (got {self.output_max_chars})"
            )


def make_bash_tool(deps: BashToolDeps) -> SdkMcpTool[Any]:
    """Build the ``bash`` :class:`SdkMcpTool` bound to ``deps``.

    The handler:

    1. Parses the command string with :func:`shlex.split`.
    2. Validates argv[0] via :func:`bearings.agent.shell.validate_argv`
       (allowlist + structural checks — no ``shell=True``).
    3. Spawns the process with :func:`asyncio.create_subprocess_exec`
       (no shell, inherits ``deps.working_dir`` as CWD).
    4. Applies ``deps.timeout_s``; kills the child on expiry and returns
       an error result.
    5. Decodes and caps combined stdout+stderr at ``deps.output_max_chars``;
       over-cap text gets the standard truncation marker.
    6. Returns ``exit_code=<N>\\n<combined>`` as the text body.

    Success and error both use the SDK's standard content-block shape so
    the agent receives consistent structure regardless of outcome.
    """

    @tool(BASH_TOOL_NAME, BASH_TOOL_DESCRIPTION, {"command": str})
    async def bash(args: dict[str, Any]) -> dict[str, Any]:
        raw = args.get("command")
        if not isinstance(raw, str):
            return _error_result("command must be a string")

        try:
            argv = shlex.split(raw)
        except ValueError as exc:
            return _error_result(f"command parse error: {exc}")

        try:
            cleaned = validate_argv(argv, deps.allowed_commands)
        except ShellValidationError as exc:
            return _error_result(str(exc))

        cwd: str | None = deps.working_dir if deps.working_dir else None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cleaned,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
        except (FileNotFoundError, PermissionError) as exc:
            return _error_result(f"spawn error: {exc}")

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=deps.timeout_s,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return _error_result(
                f"command timed out after {deps.timeout_s}s (process killed, exit_code=-1)"
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        if stdout and stderr:
            combined = stdout + "\n[stderr]\n" + stderr
        elif stderr:
            combined = stderr
        else:
            combined = stdout

        cap = deps.output_max_chars
        if len(combined) > cap:
            elided = len(combined) - cap
            combined = combined[:cap] + STREAM_TRUNCATION_MARKER_TEMPLATE.format(n=elided)

        return {"content": [{"type": "text", "text": f"exit_code={exit_code}\n{combined}"}]}

    return bash


# ---------------------------------------------------------------------------
# dir_init
# ---------------------------------------------------------------------------

DIR_INIT_TOOL_DESCRIPTION: str = (
    "Initialise the ``.bearings/`` directory-context store for the "
    "current working directory. Writes ``manifest.toml``, ``state.toml``, "
    "and ``pending.toml`` under ``.bearings/`` (creating the directory if "
    "it does not exist). The operation is idempotent — re-running it "
    "refreshes the onboarding brief. "
    "Only call when the user explicitly confirms they want to save context."
)


@dataclass(frozen=True)
class DirInitDeps:
    """Runtime dependencies for the ``dir_init`` MCP tool.

    :attr:`working_dir` is the project directory to initialise.  The
    tool writes ``.bearings/`` as a subdirectory of this path.
    """

    working_dir: Path


def make_dir_init_tool(deps: DirInitDeps) -> SdkMcpTool[Any]:
    """Build the ``dir_init`` :class:`SdkMcpTool` bound to ``deps``.

    The handler is a thin dispatch shim — all ritual logic lives in
    :func:`bearings.bearings_dir.onboarding.dir_init_body` per
    ``docs/architecture-v1.md`` §1.1.6 line 288. This file does not
    duplicate the onboarding steps.

    On :exc:`OSError` (e.g. permission denied creating ``.bearings/``),
    the tool returns an error result rather than letting the exception
    propagate through the SDK boundary.
    """

    @tool(DIR_INIT_TOOL_NAME, DIR_INIT_TOOL_DESCRIPTION, {})
    async def dir_init(args: dict[str, Any]) -> dict[str, Any]:
        try:
            await asyncio.get_running_loop().run_in_executor(None, dir_init_body, deps.working_dir)
        except OSError as exc:
            return _error_result(f"dir_init failed for {deps.working_dir}: {exc}")
        bearings_path = deps.working_dir / ".bearings"
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Initialised {bearings_path} — "
                        "manifest.toml, state.toml, and pending.toml written."
                    ),
                }
            ]
        }

    return dir_init


# ---------------------------------------------------------------------------
# get_tool_output
# ---------------------------------------------------------------------------

GET_TOOL_OUTPUT_DESCRIPTION: str = (
    "Retrieve the full captured output of a prior tool call by its "
    "``tool_use_id``. Use this when the in-context runner truncated a "
    "large output and you need the complete text. The returned output "
    "is capped at the server-configured ``cap_chars`` limit."
)


@dataclass(frozen=True)
class GetToolOutputDeps:
    """Runtime dependencies for the ``get_tool_output`` MCP tool.

    :attr:`session_id` is closure-captured and used as a secondary DB
    filter so the agent cannot retrieve output from a sibling session.

    :attr:`db_factory` yields the DB connection used to query
    ``tool_calls.output``.

    :attr:`cap_chars` is the character ceiling applied to the returned
    output.  Defaults to :data:`bearings.config.constants.DEFAULT_TOOL_OUTPUT_CAP_CHARS`.
    """

    session_id: str
    db_factory: Callable[[], Awaitable[aiosqlite.Connection]]
    cap_chars: int = DEFAULT_TOOL_OUTPUT_CAP_CHARS

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("GetToolOutputDeps.session_id must be non-empty")
        if self.cap_chars <= 0:
            raise ValueError(f"GetToolOutputDeps.cap_chars must be > 0 (got {self.cap_chars})")


def make_get_tool_output_tool(deps: GetToolOutputDeps) -> SdkMcpTool[Any]:
    """Build the ``get_tool_output`` :class:`SdkMcpTool` bound to ``deps``.

    The handler looks up ``tool_calls.output`` by the SDK ``tool_use_id``
    (the ``tool_calls.id`` primary key) restricted to ``deps.session_id``
    so cross-session reads are structurally impossible. Over-cap output
    is truncated at ``deps.cap_chars``.
    """

    @tool(
        GET_TOOL_OUTPUT_TOOL_NAME,
        GET_TOOL_OUTPUT_DESCRIPTION,
        {"tool_use_id": str},
    )
    async def get_tool_output(args: dict[str, Any]) -> dict[str, Any]:
        raw = args.get("tool_use_id")
        if not isinstance(raw, str) or not raw:
            return _error_result("tool_use_id must be a non-empty string")
        tool_use_id = raw
        connection = await deps.db_factory()
        output = await tool_calls_db.get_output_for_session(
            connection,
            tool_call_id=tool_use_id,
            session_id=deps.session_id,
        )
        if output is None:
            return _error_result(
                f"no tool call {tool_use_id!r} found in this session; "
                "tool calls are only persisted after the turn completes"
            )
        if len(output) > deps.cap_chars:
            elided = len(output) - deps.cap_chars
            output = output[: deps.cap_chars] + STREAM_TRUNCATION_MARKER_TEMPLATE.format(n=elided)
        return {"content": [{"type": "text", "text": output}]}

    return get_tool_output


# ---------------------------------------------------------------------------
# BearingsMcpDeps + server builder
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BearingsMcpDeps:
    """Bundled deps for all four Bearings MCP tools.

    Pass this to :func:`build_bearings_mcp_server` to register the
    complete tool surface. Use :meth:`minimal` to build a lightweight
    instance for tests that only need *a* server (not specific tool
    behaviour).
    """

    close_session: CloseSessionDeps
    bash: BashToolDeps
    dir_init: DirInitDeps
    get_tool_output: GetToolOutputDeps

    @classmethod
    def minimal(cls, close_session: CloseSessionDeps) -> BearingsMcpDeps:
        """Build a minimal deps bundle for callers that only need *a* server.

        The bash tool allows no commands (empty allowlist — every call
        is rejected), dir_init targets ``/tmp``, and get_tool_output
        shares the close_session DB factory.  This is suitable for tests
        exercising other subsystems that require an MCP server object but
        do not exercise the tool handlers themselves.
        """
        return cls(
            close_session=close_session,
            bash=BashToolDeps(
                working_dir="/tmp",
                allowed_commands=frozenset(),
                timeout_s=BASH_TOOL_DEFAULT_TIMEOUT_S,
                output_max_chars=BASH_TOOL_OUTPUT_MAX_CHARS,
            ),
            dir_init=DirInitDeps(working_dir=Path("/tmp")),
            get_tool_output=GetToolOutputDeps(
                session_id=close_session.session_id,
                db_factory=close_session.db_factory,
            ),
        )


def build_bearings_mcp_server(deps: BearingsMcpDeps) -> McpSdkServerConfig:
    """Build the in-process MCP server exposing all four Bearings-internal tools.

    Registers:

    * ``close_session`` — agent signals task completion + persists summary.
    * ``bash`` — shell command execution (allowlist + timeout + no shell=True).
    * ``dir_init`` — ``~/.bearings/`` directory-context initialisation shim.
    * ``get_tool_output`` — large-output retrieval by ``tool_use_id``.

    The server name is :data:`bearings.config.constants.BEARINGS_MCP_SERVER_NAME`;
    agent-facing handles render as ``mcp__<name>__<tool>``.
    """
    return create_sdk_mcp_server(
        name=BEARINGS_MCP_SERVER_NAME,
        tools=[
            make_close_session_tool(deps.close_session),
            make_bash_tool(deps.bash),
            make_dir_init_tool(deps.dir_init),
            make_get_tool_output_tool(deps.get_tool_output),
        ],
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _error_result(message: str) -> dict[str, Any]:
    """Build the SDK's standard error-result shape from a human message."""
    return {
        "content": [{"type": "text", "text": message}],
        "is_error": True,
    }


__all__ = [
    "BASH_TOOL_DESCRIPTION",
    "CLOSE_SESSION_DESCRIPTION",
    "CLOSE_SESSION_INSTRUCTION",
    "DIR_INIT_TOOL_DESCRIPTION",
    "GET_TOOL_OUTPUT_DESCRIPTION",
    "BashToolDeps",
    "BearingsMcpDeps",
    "CloseSessionDeps",
    "DirInitDeps",
    "GetToolOutputDeps",
    "build_bearings_mcp_server",
    "make_bash_tool",
    "make_close_session_tool",
    "make_dir_init_tool",
    "make_get_tool_output_tool",
]
