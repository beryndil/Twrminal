"""Factory for the ``bearings__dir_init`` MCP tool (v0.6.2).

Pure side-effect tool: runs the seven-step onboarding ritual against
the session's `working_dir` and persists `.bearings/` (manifest +
state + empty pending). Called by the agent on user confirmation
when the v0.6.2 auto-onboarding system-prompt layer is in play
(see ``bearings_dir/auto_onboard.py``).

Split out of ``agent/mcp_tools.py`` so that file stays under the
project's 400-line cap. The factory shape mirrors
``_build_get_tool_output``: closure-capture the runtime getter,
return the SDK-decorated handler.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

log = logging.getLogger(__name__)

WorkingDirGetter = Callable[[], str | None]


def _err(text: str) -> dict[str, Any]:
    """Wrap an error message in the SDK's expected content envelope."""
    return {"content": [{"type": "text", "text": text}], "is_error": True}


def build_dir_init_tool(working_dir_getter: WorkingDirGetter) -> Any:
    """Build the ``bearings__dir_init`` SDK tool.

    Refuses (with `is_error=True`) when:
      - the session has no working_dir wired
      - `.bearings/manifest.toml` already exists (re-running would
        clobber the existing identity record; users who want to
        re-onboard should `rm -rf .bearings/` first)
      - the directory has no project markers (would write a
        contentless manifest for a random `~/Downloads`)
      - the onboarding ritual itself fails (subprocess crash, etc.)
    """

    @tool(
        "dir_init",
        (
            "Persist Bearings directory context for the session's "
            "working directory. Writes `.bearings/manifest.toml`, "
            "`.bearings/state.toml`, and an empty "
            "`.bearings/pending.toml` after running the onboarding "
            "ritual. Call this ONLY after the user has clearly "
            "confirmed they want the brief saved (yes / save / "
            "persist / 'go ahead' / equivalent). The tool takes no "
            "arguments — the working directory comes from the "
            "session, not the model. Returns the rendered brief and "
            "the path written, or an error message if onboarding is "
            "not applicable (already onboarded / no project markers / "
            "scan failed)."
        ),
        {},
    )
    async def dir_init(args: dict[str, Any]) -> dict[str, Any]:
        # `args` is unused — declared `{}` so the SDK accepts the
        # zero-arg call. Touch it so linters don't flag the binding.
        del args
        working_dir = working_dir_getter()
        if not working_dir:
            return _err(
                "bearings: this session has no working directory wired. "
                "Cannot run dir_init. Set the session's working_dir via "
                "`PATCH /api/sessions/<id>` and retry."
            )
        # Late import so the prompt-assembly hot path doesn't pull
        # `subprocess`-heavy modules just to maybe register a tool.
        from bearings.bearings_dir.auto_onboard import (
            is_onboarded,
            should_offer_onboarding,
        )
        from bearings.bearings_dir.init_dir import init_directory
        from bearings.bearings_dir.onboard import render_brief

        target = Path(working_dir)
        if is_onboarded(target):
            return _err(
                f"bearings: `{target}/.bearings/` already exists. "
                "Re-onboarding would clobber the existing identity "
                "record. If you really want to start over, ask the user "
                "to remove the directory first."
            )
        if not should_offer_onboarding(target):
            return _err(
                f"bearings: `{target}` does not look like a project "
                "(no .git / pyproject.toml / package.json / Cargo.toml / "
                "go.mod). Refusing to write `.bearings/`."
            )
        try:
            brief, root = init_directory(target)
        except (OSError, FileNotFoundError) as exc:
            log.exception("bearings.dir_init: failed for %s", target)
            return _err(f"bearings: dir_init failed for `{target}`: {type(exc).__name__}: {exc}")
        rendered = render_brief(brief)
        body = (
            f"bearings: wrote `{root}` (manifest, state, empty "
            "pending). The next turn will see this brief on every "
            "prompt via the regular directory_bearings layer.\n\n"
            f"{rendered}"
        )
        return {"content": [{"type": "text", "text": body}]}

    return dir_init


__all__ = ["WorkingDirGetter", "build_dir_init_tool"]
