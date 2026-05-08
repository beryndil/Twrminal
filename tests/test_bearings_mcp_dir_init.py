"""Tests for the ``bearings__dir_init`` MCP tool.

Exercises:
* Success path — creates ``.bearings/`` with three TOML files.
* Idempotent re-run — calling a second time on an already-initialised
  directory succeeds (``dir_init_body`` is idempotent by design).
* Error path — OSError from the filesystem (directory not writable)
  returns is_error rather than propagating as an unhandled exception.

The tool body lives in ``bearings_dir/onboarding.dir_init_body`` (arch
§1.1.6); this shim only tests the MCP dispatch layer.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bearings.agent.bearings_mcp import DirInitDeps, make_dir_init_tool
from bearings.config.constants import DIR_INIT_TOOL_NAME


def _first_text(result: dict[str, object]) -> str:
    content = result.get("content")
    assert isinstance(content, list) and content
    block = content[0]
    assert isinstance(block, dict)
    text = block.get("text")
    assert isinstance(text, str)
    return text


async def test_tool_name_matches_constant() -> None:
    deps = DirInitDeps(working_dir=Path("/tmp"))
    tool_obj = make_dir_init_tool(deps)
    assert tool_obj.name == DIR_INIT_TOOL_NAME


async def test_tool_has_description() -> None:
    deps = DirInitDeps(working_dir=Path("/tmp"))
    tool_obj = make_dir_init_tool(deps)
    assert tool_obj.description


async def test_tool_input_schema_is_empty() -> None:
    """dir_init takes no user inputs — working_dir is captured in deps."""
    deps = DirInitDeps(working_dir=Path("/tmp"))
    tool_obj = make_dir_init_tool(deps)
    assert tool_obj.input_schema == {}


async def test_success_creates_bearings_files(tmp_path: Path) -> None:
    """Success path: ``.bearings/`` is created with the three TOML files."""
    deps = DirInitDeps(working_dir=tmp_path)
    tool_obj = make_dir_init_tool(deps)
    result = await tool_obj.handler({})

    assert result.get("is_error") is not True
    text = _first_text(result)
    assert "manifest.toml" in text
    assert "state.toml" in text
    assert "pending.toml" in text

    bearings_dir = tmp_path / ".bearings"
    assert (bearings_dir / "manifest.toml").exists()
    assert (bearings_dir / "state.toml").exists()
    assert (bearings_dir / "pending.toml").exists()


async def test_success_message_contains_path(tmp_path: Path) -> None:
    deps = DirInitDeps(working_dir=tmp_path)
    tool_obj = make_dir_init_tool(deps)
    result = await tool_obj.handler({})

    text = _first_text(result)
    # The success message should reference the .bearings path.
    assert ".bearings" in text


async def test_idempotent_second_call_also_succeeds(tmp_path: Path) -> None:
    """Re-running on an already-initialised directory must not error."""
    deps = DirInitDeps(working_dir=tmp_path)
    tool_obj = make_dir_init_tool(deps)

    first = await tool_obj.handler({})
    assert first.get("is_error") is not True

    second = await tool_obj.handler({})
    assert second.get("is_error") is not True


async def test_oserror_returns_error_result(tmp_path: Path) -> None:
    """When dir_init_body raises OSError, the tool returns is_error=True."""
    deps = DirInitDeps(working_dir=tmp_path)
    tool_obj = make_dir_init_tool(deps)

    with patch(
        "bearings.agent.bearings_mcp.dir_init_body",
        side_effect=OSError("permission denied"),
    ):
        result = await tool_obj.handler({})

    assert result.get("is_error") is True
    text = _first_text(result)
    assert "dir_init failed" in text or "permission denied" in text
