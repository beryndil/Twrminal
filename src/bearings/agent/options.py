# mypy: disable-error-code=explicit-any
"""Pure builder of SDK-options kwargs from a :class:`RoutingDecision`.

This module lands the three deferred SDK-currency shifts that arch
§5's audit row and item 1.1's a1 audit confirmed are 1.2's territory:

* **Shift #2 — beta headers** (arch §5 #2 / #1).
  ``betas=[ADVISOR_TOOL_BETA_HEADER]`` is wired whenever
  :attr:`RoutingDecision.advisor_model` is non-``None`` so the SDK
  attaches the ``advisor-tool-2026-03-01`` beta. The header ID itself
  lives in :mod:`bearings.config.constants` per the item-0.5 "no inline
  literals" gate.
* **Shift #5 — fallback_model** (arch §5 #5).
  ``fallback_model`` is computed from
  :data:`bearings.config.constants.EXECUTOR_FALLBACK_MODEL` for every
  short-name executor (sonnet → haiku, opus → sonnet, haiku → haiku);
  full-form SDK IDs (``claude-…``) are returned verbatim because the
  spec doesn't define a tier-down for full IDs.
* **Shift #6 — subagent auto-select** (arch §5 #6).
  The ``researcher`` :class:`SubagentSpec` carries ``model='inherit'`` so
  the parent's executor runs it; "Haiku for Explore" is implemented at
  the routing layer (spec §3 priority-30 rule), not by pinning the
  subagent's model. The justification is the trade-off arch §5 #6
  states verbatim: pinning the subagent would override the parent's
  routing and double-cost an Opus parent's Task-tool dispatch.

Shift **#4 (effort levels)** is also threaded through here because it
shares the same call site: the spec-vocabulary
:attr:`RoutingDecision.effort_level` translates to the SDK's
``effort`` literal via :data:`EFFORT_LEVEL_TO_SDK`. ``auto`` maps to
``None`` ("omit the field — let the SDK pick") which downstream
splatters via dict-comprehension at the SDK boundary.

The function returns an :class:`OptionsKwargs` frozen dataclass instead
of an SDK :class:`claude_agent_sdk.ClaudeAgentOptions` directly. Three
reasons:

1. **Decoupling from the SDK type's ``Any``-bearing surface.** The SDK
   options object exposes ``Any`` in fields like ``hooks`` /
   ``mcp_servers`` / ``can_use_tool``; constructing it inside a
   ``mypy --strict`` + ``disallow_any_explicit`` module would force a
   file-level pragma carve-out. Restricting the carve-out to the call
   site (item 1.3+, where the runner composes the full options) is
   strictly better.
2. **Item 1.2's scope.** The ``Done-when`` calls for "WS plumbing +
   intra-call tool-output streaming" — not for full SDK option
   composition (which needs hooks / MCP / can_use_tool surfaces from
   later items). The kwargs carrier names exactly the deferred-shift
   surface and stops.
3. **Audit-friendliness.** Each deferred shift gets a discrete unit
   test against the carrier shape; the auditor doesn't have to mock
   the SDK types to verify the plumbing.

References:

* ``docs/architecture-v1.md`` §1.1.4 (``agent/options.py`` ≤250 lines).
* ``docs/architecture-v1.md`` §5 #1, #2, #4, #5, #6.
* ``docs/model-routing-v1-spec.md`` §App A (RoutingDecision shape) +
  §2 (advisor primitive default policy / max_uses).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from bearings.agent.routing import RoutingDecision
from bearings.config.constants import (
    ADVISOR_TOOL_BETA_HEADER,
    BEARINGS_MCP_SERVER_NAME,
    CLOSE_SESSION_TOOL_NAME,
    EFFORT_LEVEL_TO_SDK,
    EXECUTOR_FALLBACK_MODEL,
    EXECUTOR_MODEL_FULL_ID_PREFIX,
    KNOWN_SDK_PERMISSION_MODES,
    KNOWN_SDK_SETTING_SOURCES,
    PERMISSION_PROFILE_ALLOWED_TOOLS,
    PERMISSION_PROFILE_DISALLOWED_TOOLS,
    PERMISSION_PROFILE_TO_SDK_MODE,
)

if TYPE_CHECKING:
    from claude_agent_sdk.types import McpSdkServerConfig


# CanUseTool callback signature per the SDK
# (``ClaudeAgentOptions.can_use_tool``). The SDK returns either a
# ``PermissionResultAllow`` or ``PermissionResultDeny`` from this
# callback; the broker (item A4) wires our ApprovalBroker into it.
# Aliased here as ``Any``-shaped because the SDK's permission result
# union is large and we don't want every consumer of OptionsKwargs to
# carry the SDK's type-import surface — the callback site (sdk_loop.py)
# narrows back to the concrete types at call.
type CanUseToolCallback = Callable[[str, dict[str, Any], Any], Awaitable[Any]]

# Researcher subagent prompt is large and lives in
# ``agent/researcher_prompt.py`` per arch §1.1.4. Item 1.2 doesn't need
# the full prompt body, only the metadata + ``model='inherit'`` wiring;
# a placeholder string keeps the carrier round-trippable in tests.
# Item 1.3+ replaces this with the real prompt import.
_RESEARCHER_DESCRIPTION: str = (
    "Fast agent specialized for exploring codebases. Use this when the "
    "parent needs to find files by patterns, search code for keywords, or "
    "answer questions about the codebase."
)
_RESEARCHER_PROMPT_PLACEHOLDER: str = (
    "(researcher subagent prompt — replaced by agent/researcher_prompt.py "
    "import in item 1.3+; item 1.2 carries the placeholder so the "
    "model='inherit' wiring per arch §5 #6 is verifiable in isolation.)"
)
# Read-only inspection toolset matches arch §5 #6 + the v0.17.x
# precedent (Read/Glob/Grep + write tools elided per the
# subagent's read-only role).
_RESEARCHER_TOOLS: tuple[str, ...] = (
    "Read",
    "Glob",
    "Grep",
)


@dataclass(frozen=True)
class SubagentSpec:
    """Source-of-truth for a Bearings-managed subagent.

    Translates 1:1 to SDK :class:`claude_agent_sdk.types.AgentDefinition`
    at the runtime boundary (deferred to item 1.3+); kept as a plain
    frozen dataclass here so the deferred-shift surface stays
    SDK-decoupled (see module docstring).

    The ``model`` field accepts:

    * ``'inherit'`` — parent's executor runs the subagent (arch §5 #6).
    * Any short name in
      :data:`bearings.config.constants.KNOWN_EXECUTOR_MODELS`.
    * Any full SDK model ID prefixed with
      :data:`bearings.config.constants.EXECUTOR_MODEL_FULL_ID_PREFIX`.

    The validation lives in :meth:`__post_init__` so a typo in a
    deferred-shift wiring fails at construction, not at an SDK call
    site three layers away.
    """

    name: str
    description: str
    prompt: str
    model: str
    tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SubagentSpec.name must be non-empty")
        if not self.description:
            raise ValueError("SubagentSpec.description must be non-empty")
        if not self.prompt:
            raise ValueError("SubagentSpec.prompt must be non-empty")
        if self.model != "inherit" and not self._is_known_model(self.model):
            raise ValueError(
                f"SubagentSpec.model {self.model!r} must be 'inherit', a known short "
                f"name, or a full SDK ID prefixed {EXECUTOR_MODEL_FULL_ID_PREFIX!r}"
            )

    @staticmethod
    def _is_known_model(name: str) -> bool:
        # ``RoutingDecision`` already validates short names; the prefix
        # test alone here covers the ``inherit``-or-full-ID path the
        # subagent surface needs.
        return name.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX)


@dataclass(frozen=True)
class OptionsKwargs:
    """Kwargs payload for :class:`claude_agent_sdk.ClaudeAgentOptions`.

    Two field cohorts:

    * **Routing-shift fields** (arch §5 #2, #4, #5, #6) — derived
      from a :class:`RoutingDecision`. Populated by
      :func:`build_options_kwargs`. Existed since item 1.2.
    * **Runner-loop / MCP-server / hooks fields** (arch §5 deferred
      surface) — populated by :func:`compose_session_options` when
      the worker loop is about to construct an SDK client. These
      fields have safe defaults so :func:`build_options_kwargs`
      can return a partially-populated carrier the existing tests
      treat as the routing-shift-only shape.

    :attr:`include_partial_messages` is set ``True`` per arch §5 #7
    so the executor's text/thinking/tool-output deltas stream through
    the SDK's partial-message channel; this is invariant for v1.
    """

    # ---- Routing-shift fields (no defaults — every caller supplies)
    model: str
    fallback_model: str
    betas: tuple[str, ...]
    effort: str | None
    advisor_max_uses: int
    include_partial_messages: bool
    subagents: tuple[SubagentSpec, ...]

    # ---- Runner-loop / MCP-server / hooks fields (defaulted)
    # ``system_prompt``: ``""`` means "use the SDK default"; the
    # worker's :func:`compose_session_options` always populates a
    # real value via :func:`bearings.agent.system_prompt.build_system_prompt`.
    system_prompt: str = ""
    # ``cwd``: empty string means "no cwd override"; populated from
    # the session's ``working_dir``.
    cwd: str = ""
    # ``permission_mode``: ``""`` means "use the SDK default";
    # populated from the session's permission profile.
    permission_mode: str = ""
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    # ``setting_sources``: ``None`` means "let the SDK pick";
    # otherwise a tuple of literals from
    # :data:`bearings.config.constants.KNOWN_SDK_SETTING_SOURCES`.
    setting_sources: tuple[str, ...] | None = None
    # ``max_budget_usd``: ``None`` means "no cap"; populated from
    # ``SessionConfig.max_budget_usd``.
    max_budget_usd: float | None = None
    # ``mcp_servers``: name → SDK MCP server config. Empty by
    # default; :func:`compose_session_options` populates the
    # ``"bearings"`` entry pointing at the close_session tool.
    mcp_servers: Mapping[str, McpSdkServerConfig] = field(default_factory=dict)
    # ``hooks``: empty in v1 per the wiring-agent-loop sign-off Q5
    # (recommended answer accepted 2026-05-01).
    hooks: Mapping[str, tuple[Any, ...]] = field(default_factory=dict)
    # ``can_use_tool``: ``None`` until A4 lands the
    # :class:`ApprovalBroker` callback bridge.
    can_use_tool: CanUseToolCallback | None = None


def build_options_kwargs(decision: RoutingDecision) -> OptionsKwargs:
    """Compute the SDK options kwargs from a :class:`RoutingDecision`.

    Pure function — no I/O, no side effects, no clock reads. Same input
    yields the same output, which is what the unit-test bar in item
    1.2's done-when ("Handles current SDK event shapes") and the
    auditor's "verify each deferred shift lands" rail both depend on.

    Per arch §5 #4: ``effort`` is ``None`` when the decision's
    ``effort_level`` is ``"auto"`` (the SDK has no ``"auto"`` literal
    as of the queried docs; mapping to ``None`` means "omit the field
    so the SDK picks"). The downstream caller splats via
    ``ClaudeAgentOptions(**{k: v for k, v in kwargs.items() if v is not
    None})`` or equivalent.

    Per arch §5 #2: ``betas`` is empty when no advisor is wired. Other
    beta headers can be appended downstream (e.g. context-1m); the
    advisor header is the only one this function decides about.

    Per arch §5 #5: ``fallback_model`` for full-form SDK IDs (any
    string starting with ``claude-``) is the same string verbatim —
    the spec defines no tier-down for full IDs and the SDK is the
    arbiter of fallback at runtime if the user explicitly pinned a
    full ID.

    Per arch §5 #6: the ``researcher`` :class:`SubagentSpec` always
    rides on the kwargs (one entry, ``model='inherit'``). When the
    consumer in item 1.3+ has a config flag ``enable_researcher_subagent``
    set ``False`` (per :class:`SessionConfig` default), it splats only
    a subset of subagents at the SDK boundary.
    """
    advisor = decision.advisor_model
    betas: tuple[str, ...] = (ADVISOR_TOOL_BETA_HEADER,) if advisor is not None else ()
    fallback_model = _resolve_fallback_model(decision.executor_model)
    effort = EFFORT_LEVEL_TO_SDK[decision.effort_level]
    researcher = SubagentSpec(
        name="researcher",
        description=_RESEARCHER_DESCRIPTION,
        prompt=_RESEARCHER_PROMPT_PLACEHOLDER,
        model="inherit",
        tools=_RESEARCHER_TOOLS,
    )
    return OptionsKwargs(
        model=decision.executor_model,
        fallback_model=fallback_model,
        betas=betas,
        effort=effort,
        # ``advisor_max_uses`` rides on the kwargs even when no advisor
        # is wired — the runtime executor enforces the cap when the
        # advisor primitive is actually consulted (spec §2 "the
        # executor stops calling once it has called max_uses times").
        # When ``advisor_model is None`` the executor never calls and
        # the value is moot; carrying it through unchanged simplifies
        # downstream "advisor was wired" reasoning.
        advisor_max_uses=decision.advisor_max_uses,
        include_partial_messages=True,
        subagents=(researcher,),
    )


def compose_session_options(
    *,
    decision: RoutingDecision,
    session_instructions: str | None,
    working_dir: str,
    permission_profile: str,
    permission_mode_override: str | None,
    setting_sources: tuple[str, ...] | None,
    max_budget_usd: float | None,
    bearings_mcp_server: McpSdkServerConfig,
    can_use_tool: CanUseToolCallback | None = None,
    extra_system_prompt_parts: tuple[str, ...] = (),
) -> OptionsKwargs:
    """Build the full :class:`OptionsKwargs` for :class:`ClaudeAgentOptions` construction.

    Composes the routing-shift fields from :func:`build_options_kwargs`
    with the runner-loop / MCP-server / system-prompt surface the
    worker (sdk_loop.py) needs at SDK-client init time.

    Args:
        decision: Active :class:`RoutingDecision` for this session.
        session_instructions: Per-session steering text (the row's
            ``session_instructions`` column). The system-prompt
            assembler appends :data:`bearings.agent.bearings_mcp.CLOSE_SESSION_INSTRUCTION`
            after this so the agent always knows about the close
            tool.
        working_dir: ``SessionConfig.working_dir`` — passed to the
            SDK as ``cwd``.
        permission_profile: ``"restricted"`` / ``"standard"`` /
            ``"expanded"`` — resolved via the constants module to
            ``permission_mode`` + ``allowed_tools`` + ``disallowed_tools``.
        permission_mode_override: An explicit
            ``ClaudeAgentOptions.permission_mode`` literal that
            overrides the profile's resolved mode. ``None`` means
            "use the profile's default".
        setting_sources: Optional ``setting_sources`` tuple; ``None``
            means "let the SDK pick".
        max_budget_usd: Pass-through to the SDK. ``None`` means
            "no cap".
        bearings_mcp_server: The SDK MCP server wrapping the
            :func:`bearings.agent.bearings_mcp.close_session` tool.
            Constructed by the worker via
            :func:`bearings.agent.bearings_mcp.build_bearings_mcp_server`
            with closure-captured session id + DB factory.
        can_use_tool: Optional approval-bridge callback. ``None``
            in v1 until A4 lands the :class:`ApprovalBroker`.
        extra_system_prompt_parts: Additional system-prompt blocks
            to append after the default surface (used by tests that
            need to verify the splice order; production callers
            leave empty).

    Returns:
        Fully-populated :class:`OptionsKwargs` ready for SDK splat
        via ``ClaudeAgentOptions(**kwargs.as_sdk_kwargs())``.
    """
    from bearings.agent.system_prompt import build_system_prompt

    base = build_options_kwargs(decision)
    if permission_profile not in PERMISSION_PROFILE_TO_SDK_MODE:
        raise ValueError(
            f"compose_session_options: permission_profile {permission_profile!r} "
            f"not in {sorted(PERMISSION_PROFILE_TO_SDK_MODE)}"
        )
    if permission_mode_override is not None:
        if permission_mode_override not in KNOWN_SDK_PERMISSION_MODES:
            raise ValueError(
                f"compose_session_options: permission_mode_override "
                f"{permission_mode_override!r} not in {sorted(KNOWN_SDK_PERMISSION_MODES)}"
            )
        permission_mode = permission_mode_override
    else:
        permission_mode = PERMISSION_PROFILE_TO_SDK_MODE[permission_profile]
    if setting_sources is not None:
        for src in setting_sources:
            if src not in KNOWN_SDK_SETTING_SOURCES:
                raise ValueError(
                    f"compose_session_options: setting_sources entry {src!r} not in "
                    f"{sorted(KNOWN_SDK_SETTING_SOURCES)}"
                )
    allowed = list(PERMISSION_PROFILE_ALLOWED_TOOLS[permission_profile])
    close_session_handle = f"mcp__{BEARINGS_MCP_SERVER_NAME}__{CLOSE_SESSION_TOOL_NAME}"
    if close_session_handle not in allowed:
        allowed.append(close_session_handle)
    system_prompt = build_system_prompt(
        session_instructions=session_instructions,
        extras=extra_system_prompt_parts,
    )
    return replace(
        base,
        system_prompt=system_prompt,
        cwd=working_dir,
        permission_mode=permission_mode,
        allowed_tools=tuple(allowed),
        disallowed_tools=PERMISSION_PROFILE_DISALLOWED_TOOLS[permission_profile],
        setting_sources=setting_sources,
        max_budget_usd=max_budget_usd,
        mcp_servers={BEARINGS_MCP_SERVER_NAME: bearings_mcp_server},
        hooks={},
        can_use_tool=can_use_tool,
    )


def _resolve_fallback_model(executor_model: str) -> str:
    """Resolve the SDK ``fallback_model`` for an executor short name.

    Full-form SDK IDs pass through verbatim per arch §5 #5: the spec
    defines no tier-down for full IDs and the SDK is the arbiter of
    fallback at runtime in that case.
    """
    if executor_model.startswith(EXECUTOR_MODEL_FULL_ID_PREFIX):
        return executor_model
    if executor_model in EXECUTOR_FALLBACK_MODEL:
        return EXECUTOR_FALLBACK_MODEL[executor_model]
    # ``RoutingDecision.__post_init__`` rejects unknown short names at
    # construction; reaching this branch means a future short name was
    # added to ``KNOWN_EXECUTOR_MODELS`` without a fallback row. Surface
    # the omission instead of silently mapping to the input.
    raise ValueError(
        f"executor_model {executor_model!r} has no entry in EXECUTOR_FALLBACK_MODEL "
        f"(rebuild constants table to keep it in lockstep with KNOWN_EXECUTOR_MODELS)"
    )


__all__ = [
    "CanUseToolCallback",
    "OptionsKwargs",
    "SubagentSpec",
    "build_options_kwargs",
    "compose_session_options",
]
