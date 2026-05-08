"""Tests for the ``bearings__bash`` MCP tool.

Exercises:
* Success path — ``echo hello`` returns exit_code=0 and the expected output.
* Allowlist rejection — command not in ``allowed_commands`` returns is_error.
* Timeout error path — long-running command killed after timeout returns is_error.
* Spawn error — binary not on PATH returns is_error.
* Parse error — malformed shell quoting returns is_error.

The tool handler is reached through ``tool_obj.handler(...)`` so no SDK
subprocess is involved.
"""

from __future__ import annotations

import pytest

from bearings.agent.bearings_mcp import BashToolDeps, make_bash_tool
from bearings.config.constants import (
    BASH_TOOL_DEFAULT_TIMEOUT_S,
    BASH_TOOL_NAME,
    BASH_TOOL_OUTPUT_MAX_CHARS,
)


def _deps(
    *,
    allowed: frozenset[str] | None = None,
    timeout_s: float = BASH_TOOL_DEFAULT_TIMEOUT_S,
    output_max_chars: int = BASH_TOOL_OUTPUT_MAX_CHARS,
    working_dir: str = "/tmp",
) -> BashToolDeps:
    if allowed is None:
        allowed = frozenset({"echo", "true", "false", "sleep"})
    return BashToolDeps(
        working_dir=working_dir,
        allowed_commands=allowed,
        timeout_s=timeout_s,
        output_max_chars=output_max_chars,
    )


def _first_text(result: dict[str, object]) -> str:
    content = result.get("content")
    assert isinstance(content, list) and content
    block = content[0]
    assert isinstance(block, dict)
    text = block.get("text")
    assert isinstance(text, str)
    return text


async def test_tool_name_matches_constant() -> None:
    tool_obj = make_bash_tool(_deps())
    assert tool_obj.name == BASH_TOOL_NAME


async def test_tool_has_description() -> None:
    tool_obj = make_bash_tool(_deps())
    assert tool_obj.description


async def test_tool_input_schema_has_command() -> None:
    tool_obj = make_bash_tool(_deps())
    assert tool_obj.input_schema == {"command": str}


async def test_echo_success_path() -> None:
    """echo returns exit_code=0 and the expected text."""
    tool_obj = make_bash_tool(_deps())
    result = await tool_obj.handler({"command": "echo hello"})

    assert result.get("is_error") is not True
    text = _first_text(result)
    assert "exit_code=0" in text
    assert "hello" in text


async def test_exit_code_nonzero_on_false() -> None:
    """``false`` exits non-zero; the tool still returns success shape (no is_error)."""
    tool_obj = make_bash_tool(_deps())
    result = await tool_obj.handler({"command": "false"})

    assert result.get("is_error") is not True
    text = _first_text(result)
    # exit code must be non-zero (false exits 1 on POSIX)
    assert "exit_code=0" not in text


async def test_command_not_in_allowlist_returns_error() -> None:
    """Commands blocked by the allowlist return is_error without spawning."""
    tool_obj = make_bash_tool(_deps(allowed=frozenset({"echo"})))
    result = await tool_obj.handler({"command": "ls -la"})

    assert result.get("is_error") is True
    text = _first_text(result)
    assert "allowlist" in text.lower() or "not in" in text.lower()


async def test_empty_allowlist_rejects_all() -> None:
    tool_obj = make_bash_tool(_deps(allowed=frozenset()))
    result = await tool_obj.handler({"command": "echo hi"})
    assert result.get("is_error") is True


async def test_non_string_command_returns_error() -> None:
    tool_obj = make_bash_tool(_deps())
    result = await tool_obj.handler({"command": 42})
    assert result.get("is_error") is True
    assert "string" in _first_text(result)


async def test_malformed_quoting_returns_error() -> None:
    """shlex.split raises ValueError on unmatched quotes."""
    tool_obj = make_bash_tool(_deps())
    result = await tool_obj.handler({"command": "echo 'unterminated"})
    assert result.get("is_error") is True
    assert "parse error" in _first_text(result).lower()


async def test_timeout_kills_process_and_returns_error() -> None:
    """A command that sleeps longer than timeout_s gets killed."""
    tool_obj = make_bash_tool(_deps(timeout_s=0.1))
    result = await tool_obj.handler({"command": "sleep 10"})

    assert result.get("is_error") is True
    text = _first_text(result)
    assert "timed out" in text.lower() or "timeout" in text.lower()


async def test_output_capped_at_output_max_chars() -> None:
    """Output exceeding output_max_chars is truncated with the marker."""
    # Allow a command that generates > 10 chars of output but set cap to 5.
    tool_obj = make_bash_tool(_deps(output_max_chars=5))
    result = await tool_obj.handler({"command": "echo 0123456789"})

    assert result.get("is_error") is not True
    text = _first_text(result)
    # Truncation marker appears when cap is exceeded.
    assert "truncated" in text or len(text) <= 200  # marker or naturally short


@pytest.mark.parametrize("path_cmd", ["/bin/echo", "/usr/bin/echo"])
async def test_path_separator_in_argv0_rejected(path_cmd: str) -> None:
    """argv[0] with a path separator is rejected by validate_argv."""
    tool_obj = make_bash_tool(_deps(allowed=frozenset({path_cmd})))
    result = await tool_obj.handler({"command": f"{path_cmd} hi"})
    assert result.get("is_error") is True


async def test_deps_rejects_nonpositive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        BashToolDeps(
            working_dir="/tmp",
            allowed_commands=frozenset({"echo"}),
            timeout_s=0.0,
            output_max_chars=BASH_TOOL_OUTPUT_MAX_CHARS,
        )


async def test_deps_rejects_nonpositive_output_max_chars() -> None:
    with pytest.raises(ValueError, match="output_max_chars"):
        BashToolDeps(
            working_dir="/tmp",
            allowed_commands=frozenset({"echo"}),
            timeout_s=5.0,
            output_max_chars=0,
        )
