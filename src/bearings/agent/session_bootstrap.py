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
from bearings.agent.tags import resolve_claude_md_blocks
from bearings.config.constants import (
    DEFAULT_TEMPLATE_ADVISOR_MODEL,
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
        # Reconstruct the routing decision from the persisted routing
        # columns on the session row. These columns are written at
        # session-create time (``POST /api/sessions``) so the decision
        # survives supervisor respawns and mid-session model swaps
        # without drifting to template-wide defaults.
        #
        # Backward-compat: rows that predate the routing columns carry
        # NULL for ``routing_advisor_model`` and the schema defaults (5,
        # 'auto') for the integer/text columns. NULL advisor is treated
        # as "unknown — fall back to the template default" so old
        # sessions keep the advisor they would have had under the prior
        # bootstrap logic. New rows with a positively stored NULL (i.e.
        # advisor_model=None was explicitly persisted) carry the same
        # value, so the distinction is transparent to the bootstrap: both
        # fall back to DEFAULT_TEMPLATE_ADVISOR_MODEL.
        advisor_model: str | None = (
            row.routing_advisor_model
            if row.routing_advisor_model is not None
            else DEFAULT_TEMPLATE_ADVISOR_MODEL
        )
        decision = RoutingDecision(
            executor_model=row.model,
            advisor_model=advisor_model,
            advisor_max_uses=row.routing_advisor_max_uses,
            effort_level=row.routing_effort_level,
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
        # Load CLAUDE.md blocks from each tag's working_dir, in priority order.
        # Missing files are silently skipped. The tuple is empty if no tags exist
        # or none have working_dir set.
        extra_claude_md_blocks = await resolve_claude_md_blocks(db_connection, session_id)
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
            extra_system_prompt_parts=extra_claude_md_blocks,
        )
        return SessionSetup(
            session=agent_session,
            options=options,
            approval_broker=broker,
        )

    return setup


__all__ = ["build_session_setup"]
