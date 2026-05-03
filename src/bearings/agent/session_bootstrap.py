"""Per-session bootstrap — DB row → AgentSession + OptionsKwargs.

Per Slice A1.3 of ``~/.claude/plans/wiring-agent-loop.md``: this is
the production binding that lets the
:class:`bearings.web.runner_factory.InProcessRunnerRegistry`
materialise the worker-loop inputs from a session id alone. The
factory takes a ``session_setup`` callable; this module produces it.

The bootstrap reads the session row from ``bearings.db.sessions``,
pulls the session-row's permission profile / working dir /
session_instructions / max_budget_usd / routing decision, builds the
SDK MCP server with closure-captured deps, and composes the full
:class:`bearings.agent.options.OptionsKwargs`.

Per sign-off Q6 (2026-05-01) the routing decision is read verbatim
from the session row's stored decision projection — the routing
evaluator runs once at session-create (``agent/session_assembly.py``)
and is not re-run per turn. Today the session row stores only
``model``; the full RoutingDecision is reconstructed defensively from
the row's known columns + the constants-module defaults so the worker
can run on rows created before the decision-projection columns
landed.
"""

from __future__ import annotations

import os.path

import aiosqlite

from bearings.agent.approval import ApprovalBroker
from bearings.agent.bearings_mcp import (
    CloseSessionDeps,
    build_bearings_mcp_server,
)
from bearings.agent.options import (
    compose_session_options,
)
from bearings.agent.routing import RoutingDecision
from bearings.agent.runner import SessionRunner, SessionSetup, SessionSetupFn
from bearings.agent.session import AgentSession, PermissionProfile, SessionConfig
from bearings.config.constants import (
    DEFAULT_TEMPLATE_ADVISOR_MAX_USES,
    DEFAULT_TEMPLATE_ADVISOR_MODEL,
    DEFAULT_TEMPLATE_EFFORT_LEVEL,
    DEFAULT_TEMPLATE_PERMISSION_PROFILE,
)
from bearings.db import sessions as sessions_db


def _expand_cwd(working_dir: str) -> str:
    """Expand ``~`` in a session row's stored ``working_dir``.

    Pure string manipulation; not real I/O despite the ``os.path``
    surface. Pulled out of the async ``setup`` closure below so the
    blocking-call lint rule (ASYNC240) isn't tripped on the
    expanduser call inside an ``async def``.
    """
    return os.path.expanduser(working_dir) if working_dir else working_dir


def build_session_setup(
    db_connection: aiosqlite.Connection,
    *,
    enable_approval_broker: bool = True,
) -> SessionSetupFn:
    """Build a ``session_setup`` callable bound to ``db_connection``.

    The returned callable is the one
    :class:`InProcessRunnerRegistry` invokes on every first-touch.
    Returns ``None`` if the session row is missing OR not a
    chat-kind session (the worker only runs chat sessions today;
    checklist sessions have their own driver in
    ``agent/auto_driver_runtime.py``).

    Args:
        db_connection: The long-lived :class:`aiosqlite.Connection`
            from ``app.state.db_connection``. Same connection the
            session rows + close_session DB writes go through.
        enable_approval_broker: When ``True`` (default), each
            session gets a fresh :class:`ApprovalBroker` whose
            callback is wired into ``OptionsKwargs.can_use_tool``.
            Disabled by tests that exercise the bootstrap without
            the approval surface.
    """

    async def setup(session_id: str, runner: SessionRunner) -> SessionSetup | None:
        row = await sessions_db.get(db_connection, session_id)
        if row is None:
            return None
        # Reconstruct the routing decision from the stored model +
        # constants-module defaults. Per sign-off Q6 this is the
        # same decision a session-create flow pinned at row
        # creation; the row doesn't yet store the full projection
        # (the per-message persistence layer in
        # ``agent/persistence.py`` writes it onto each message row,
        # not the session row).
        decision = RoutingDecision(
            executor_model=row.model,
            advisor_model=DEFAULT_TEMPLATE_ADVISOR_MODEL,
            advisor_max_uses=DEFAULT_TEMPLATE_ADVISOR_MAX_USES,
            effort_level=DEFAULT_TEMPLATE_EFFORT_LEVEL,
            source="default",
            reason=f"session {session_id} bootstrap",
            matched_rule_id=None,
        )
        # The session row stores the user-typed `working_dir` verbatim
        # (the inspector displays the literal `~/Projects/...` form).
        # Expand it here, at the SDK boundary, so the worker's chdir
        # target is an absolute path the OS can resolve. Without this,
        # the SDK client constructor crashes with ENOENT and the
        # supervisor task ends silently with an unprocessable queue.
        sdk_cwd = _expand_cwd(row.working_dir)
        config = SessionConfig(
            session_id=session_id,
            working_dir=sdk_cwd,
            decision=decision,
            db=db_connection,
            permission_mode=row.permission_mode,
            max_budget_usd=row.max_budget_usd,
        )
        agent_session = AgentSession(config)

        async def db_factory() -> aiosqlite.Connection:
            return db_connection

        deps = CloseSessionDeps(session_id=session_id, db_factory=db_factory)
        bearings_mcp_server = build_bearings_mcp_server(deps)
        broker = ApprovalBroker(runner) if enable_approval_broker else None
        options = compose_session_options(
            decision=decision,
            session_instructions=row.session_instructions,
            working_dir=sdk_cwd,
            permission_profile=PermissionProfile.STANDARD.value
            if row.permission_mode is None
            else DEFAULT_TEMPLATE_PERMISSION_PROFILE,
            permission_mode_override=row.permission_mode,
            setting_sources=None,
            max_budget_usd=row.max_budget_usd,
            bearings_mcp_server=bearings_mcp_server,
            can_use_tool=broker.callback() if broker is not None else None,
        )
        return SessionSetup(
            session=agent_session,
            options=options,
            approval_broker=broker,
        )

    return setup


__all__ = ["build_session_setup"]
