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
from pathlib import Path

import aiosqlite

from bearings.agent.analytics_capture import assemble_plug_blocks, capture_session_plug
from bearings.agent.approval import ApprovalBroker
from bearings.agent.bearings_mcp import (
    BashToolDeps,
    BearingsMcpDeps,
    CloseSessionDeps,
    DirInitDeps,
    GetToolOutputDeps,
    build_bearings_mcp_server,
)
from bearings.agent.options import (
    compose_session_options,
)
from bearings.agent.routing import RoutingDecision
from bearings.agent.runner import SessionRunner, SessionSetup, SessionSetupFn
from bearings.agent.sdk_session_id import bearings_to_sdk_uuid
from bearings.agent.session import AgentSession, PermissionProfile, SessionConfig
from bearings.agent.session_store import BearingsSessionStore
from bearings.agent.tags import resolve_claude_md_blocks, resolve_tag_memory_blocks
from bearings.config.constants import (
    BASH_TOOL_DEFAULT_TIMEOUT_S,
    BASH_TOOL_OUTPUT_MAX_CHARS,
    DEFAULT_BASH_TOOL_ALLOWED_COMMANDS,
    DEFAULT_TEMPLATE_ADVISOR_MODEL,
    DEFAULT_TEMPLATE_PERMISSION_PROFILE,
    DEFAULT_TOOL_OUTPUT_CAP_CHARS,
)
from bearings.db import sdk_entries as sdk_entries_db
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

        close_deps = CloseSessionDeps(session_id=session_id, db_factory=db_factory)
        mcp_deps = BearingsMcpDeps(
            close_session=close_deps,
            bash=BashToolDeps(
                working_dir=sdk_cwd,
                allowed_commands=DEFAULT_BASH_TOOL_ALLOWED_COMMANDS,
                timeout_s=BASH_TOOL_DEFAULT_TIMEOUT_S,
                output_max_chars=BASH_TOOL_OUTPUT_MAX_CHARS,
            ),
            dir_init=DirInitDeps(working_dir=Path(sdk_cwd)),
            get_tool_output=GetToolOutputDeps(
                session_id=session_id,
                db_factory=db_factory,
                cap_chars=DEFAULT_TOOL_OUTPUT_CAP_CHARS,
            ),
        )
        bearings_mcp_server = build_bearings_mcp_server(mcp_deps)
        broker = ApprovalBroker(runner) if enable_approval_broker else None
        # Load CLAUDE.md blocks from each tag's working_dir, ordered by tag-class
        # precedence (project > general > severity) so the highest-precedence
        # block lands last and wins on directive conflicts. Missing files are
        # silently skipped; the tuple is empty if no tags exist or none have
        # working_dir set.
        extra_claude_md_blocks = await resolve_claude_md_blocks(db_connection, session_id)
        # Load enabled tag-memory bodies from the tag_memories table, in the
        # same precedence order. Memories are re-read on every worker spawn so
        # edits take effect on the next prompt without a runner respawn.
        extra_memory_blocks = await resolve_tag_memory_blocks(db_connection, session_id)
        # SDK history-replay wiring (lands the model-swap context-loss fix
        # diagnosed 2026-05-05). The SessionStore mirrors the CLI's JSONL
        # transcript to ``sdk_session_entries``; on every spawn after the
        # first, ``resume=<uuid>`` triggers materialisation from the store
        # so the new subprocess inherits full conversation context. On the
        # first spawn (no mirror rows yet) ``sdk_session_id=<uuid>`` pins
        # the CLI's session UUID to ours so subsequent ``append`` calls
        # are routable back to this Bearings session id.
        store = BearingsSessionStore(db_factory=db_factory)
        sdk_uuid = bearings_to_sdk_uuid(session_id)
        prior_entry_count = await sdk_entries_db.count_for_session(
            db_connection, session_id=session_id
        )
        if prior_entry_count > 0:
            sdk_session_id_arg: str | None = None
            resume_arg: str | None = sdk_uuid
        else:
            sdk_session_id_arg = sdk_uuid
            resume_arg = None
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
            extra_system_prompt_parts=(*extra_claude_md_blocks, *extra_memory_blocks),
            session_store=store,
            sdk_session_id=sdk_session_id_arg,
            resume=resume_arg,
        )
        # Analytics Phase 2 — capture plug blocks for this session
        # (spec §5.1). capture_session_plug uses INSERT OR IGNORE so
        # supervisor respawns that call setup() again are no-ops.
        # DB failures are caught and logged inside capture_session_plug
        # so analytics never blocks the agent loop start.
        _plug_blocks = assemble_plug_blocks(
            sdk_cwd,
            extra_claude_md_blocks,
            extra_memory_blocks,
            row.session_instructions,
        )
        await capture_session_plug(db_connection, session_id, row.model, _plug_blocks)
        return SessionSetup(
            session=agent_session,
            options=options,
            approval_broker=broker,
        )

    return setup


__all__ = ["build_session_setup"]
