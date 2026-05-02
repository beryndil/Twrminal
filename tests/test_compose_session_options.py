"""Tests for ``bearings.agent.options.compose_session_options``.

Per Slice A2 of ``~/.claude/plans/wiring-agent-loop.md``: this is
the worker-loop entry point that closes the gap between the
routing-shift ``OptionsKwargs`` carrier and the full SDK options
surface (system_prompt, cwd, permission_mode, allowed_tools,
mcp_servers, hooks, can_use_tool).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import aiosqlite
import pytest

if TYPE_CHECKING:
    from claude_agent_sdk.types import McpSdkServerConfig

from bearings.agent.bearings_mcp import (
    CLOSE_SESSION_INSTRUCTION,
    CloseSessionDeps,
    build_bearings_mcp_server,
)
from bearings.agent.options import (
    compose_session_options,
)
from bearings.agent.routing import RoutingDecision
from bearings.config.constants import (
    BEARINGS_MCP_SERVER_NAME,
    CLOSE_SESSION_TOOL_NAME,
    PERMISSION_PROFILE_ALLOWED_TOOLS,
    PERMISSION_PROFILE_DISALLOWED_TOOLS,
    PERMISSION_PROFILE_TO_SDK_MODE,
)


def _decision() -> RoutingDecision:
    return RoutingDecision(
        executor_model="sonnet",
        advisor_model=None,
        advisor_max_uses=0,
        effort_level="medium",
        source="default",
        reason="test",
        matched_rule_id=None,
    )


def _factory_unused() -> Callable[[], Awaitable[aiosqlite.Connection]]:
    async def _never() -> aiosqlite.Connection:  # pragma: no cover
        raise AssertionError("compose_session_options test should not call factory")

    return _never


def _server() -> McpSdkServerConfig:
    return build_bearings_mcp_server(
        CloseSessionDeps(session_id="ses_t", db_factory=_factory_unused())
    )


def test_routing_shift_fields_come_from_build_options_kwargs() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/tmp/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.model == "sonnet"
    assert kwargs.fallback_model == "haiku"
    assert kwargs.include_partial_messages is True


def test_system_prompt_includes_close_session_instruction() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions="be careful",
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert "be careful" in kwargs.system_prompt
    assert CLOSE_SESSION_INSTRUCTION in kwargs.system_prompt


def test_cwd_is_session_working_dir() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/home/dave/projects/foo",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.cwd == "/home/dave/projects/foo"


def test_permission_mode_resolved_from_profile() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.permission_mode == PERMISSION_PROFILE_TO_SDK_MODE["standard"]


def test_explicit_permission_mode_override_wins() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override="acceptEdits",
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.permission_mode == "acceptEdits"


def test_allowed_tools_includes_close_session_handle() -> None:
    """The agent-facing handle ``mcp__bearings__close_session`` must be
    present in allowed_tools so the SDK forwards calls to the
    in-process MCP server."""
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="restricted",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    expected_handle = f"mcp__{BEARINGS_MCP_SERVER_NAME}__{CLOSE_SESSION_TOOL_NAME}"
    assert expected_handle in kwargs.allowed_tools
    # The profile's existing allowlist is preserved.
    for tool in PERMISSION_PROFILE_ALLOWED_TOOLS["restricted"]:
        assert tool in kwargs.allowed_tools


def test_disallowed_tools_reflects_profile() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="restricted",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.disallowed_tools == PERMISSION_PROFILE_DISALLOWED_TOOLS["restricted"]


def test_mcp_servers_carries_bearings_entry() -> None:
    server = _server()
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=server,
    )
    assert kwargs.mcp_servers == {BEARINGS_MCP_SERVER_NAME: server}


def test_hooks_empty_in_v1() -> None:
    """Per sign-off Q5 (2026-05-01) v1 ships no Bearings-specific hooks."""
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.hooks == {}


def test_can_use_tool_defaults_to_none_in_v1() -> None:
    """Until A4 lands the ApprovalBroker, can_use_tool is None
    (the SDK falls back to its own default — accept-all in
    ``permission_mode == 'default'``)."""
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.can_use_tool is None


def test_max_budget_usd_passes_through() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=12.5,
        bearings_mcp_server=_server(),
    )
    assert kwargs.max_budget_usd == 12.5


def test_setting_sources_passes_through_when_set() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=("user", "project"),
        max_budget_usd=None,
        bearings_mcp_server=_server(),
    )
    assert kwargs.setting_sources == ("user", "project")


def test_unknown_permission_profile_rejected() -> None:
    with pytest.raises(ValueError, match="permission_profile"):
        compose_session_options(
            decision=_decision(),
            session_instructions=None,
            working_dir="/wd",
            permission_profile="bogus",
            permission_mode_override=None,
            setting_sources=None,
            max_budget_usd=None,
            bearings_mcp_server=_server(),
        )


def test_unknown_permission_mode_override_rejected() -> None:
    with pytest.raises(ValueError, match="permission_mode_override"):
        compose_session_options(
            decision=_decision(),
            session_instructions=None,
            working_dir="/wd",
            permission_profile="standard",
            permission_mode_override="not-a-mode",
            setting_sources=None,
            max_budget_usd=None,
            bearings_mcp_server=_server(),
        )


def test_unknown_setting_source_rejected() -> None:
    with pytest.raises(ValueError, match="setting_sources"):
        compose_session_options(
            decision=_decision(),
            session_instructions=None,
            working_dir="/wd",
            permission_profile="standard",
            permission_mode_override=None,
            setting_sources=("bogus",),
            max_budget_usd=None,
            bearings_mcp_server=_server(),
        )


def test_extra_system_prompt_parts_appended_after_close_instruction() -> None:
    kwargs = compose_session_options(
        decision=_decision(),
        session_instructions=None,
        working_dir="/wd",
        permission_profile="standard",
        permission_mode_override=None,
        setting_sources=None,
        max_budget_usd=None,
        bearings_mcp_server=_server(),
        extra_system_prompt_parts=("Trailing memory block.",),
    )
    close_idx = kwargs.system_prompt.index(CLOSE_SESSION_INSTRUCTION)
    extra_idx = kwargs.system_prompt.index("Trailing memory block.")
    assert close_idx < extra_idx


def test_options_kwargs_field_names_align_with_sdk_options() -> None:
    """Shape pin: every new ``OptionsKwargs`` field that targets the
    SDK's ``ClaudeAgentOptions`` shares its name with the SDK field.
    A future SDK rename would surface here as a missing field rather
    than at live-session init time on the dogfood box."""
    import dataclasses

    from claude_agent_sdk import ClaudeAgentOptions

    from bearings.agent.options import OptionsKwargs

    sdk_field_names = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
    bearings_to_sdk = {
        "model",
        "fallback_model",
        "betas",
        "effort",
        "include_partial_messages",
        "system_prompt",
        "cwd",
        "permission_mode",
        "allowed_tools",
        "disallowed_tools",
        "setting_sources",
        "max_budget_usd",
        "mcp_servers",
        "hooks",
        "can_use_tool",
    }
    bearings_field_names = {f.name for f in dataclasses.fields(OptionsKwargs)}
    # Every Bearings field that targets SDK must exist on SDK side.
    missing = bearings_to_sdk - sdk_field_names
    assert not missing, f"OptionsKwargs targets SDK fields not present: {missing}"
    # Every name in our SDK-target set must also exist on OptionsKwargs.
    not_in_carrier = bearings_to_sdk - bearings_field_names
    assert not not_in_carrier, (
        f"SDK-target set has names not declared on OptionsKwargs: {not_in_carrier}"
    )
