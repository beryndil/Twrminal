"""Shell bridge for the context-menu `open_in` submenu.

Phase 4a.1 of docs/context-menu-plan.md. A single `POST /shell/open`
route dispatches to one of five configured host commands — editor,
terminal, file explorer, git GUI, Claude CLI — so the frontend can
offer "Open in VS Code" / "Open terminal here" / etc. without each
menu action having to know the user's preferred tool.

Command strings live in `config.toml` under `[shell]` (see
`bearings.config.ShellCfg`). Each is an argv list; `{path}` in any
argv element is substituted with the requested path, and if no
placeholder appears the path is appended as the last arg. That keeps
the common case (`["code"]`, `["xdg-open"]`) working with zero
template boilerplate while still letting power users pass flags like
`["alacritty", "--working-directory", "{path}"]`.

Security posture: Bearings binds localhost-only and the caller is
always the bundled SvelteKit SPA. We use `subprocess.Popen` with an
argv list (no `shell=True`) so a path containing whitespace or quotes
can't inject additional arguments. The process is detached
(`start_new_session=True`, stdout/stderr → DEVNULL) so Bearings
returns 204 immediately without waiting on GUI app startup.
"""

from __future__ import annotations

import subprocess
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from bearings.api.auth import require_auth
from bearings.config import ShellCfg

router = APIRouter(
    prefix="/shell",
    tags=["shell"],
    dependencies=[Depends(require_auth)],
)


# Declared as a Literal so a typo in the request body surfaces as a
# 422 at the Pydantic boundary instead of landing in the dispatcher
# and matching no branch. Keep in sync with `ShellCfg` field names
# and the `_KIND_TO_FIELD` mapping below.
ShellKind = Literal[
    "editor",
    "terminal",
    "file_explorer",
    "git_gui",
    "claude_cli",
]


# Wire-level `kind` → `ShellCfg` attribute name. Keeping the mapping
# explicit (rather than f-stringing `f"{kind}_command"`) means adding
# a new kind requires a conscious edit here + in the Literal above,
# which is the right amount of friction for a surface that spawns
# subprocesses.
_KIND_TO_FIELD: dict[ShellKind, str] = {
    "editor": "editor_command",
    "terminal": "terminal_command",
    "file_explorer": "file_explorer_command",
    "git_gui": "git_gui_command",
    "claude_cli": "claude_cli_command",
}

# Path length cap — anything longer is almost certainly malformed or
# pathological. Real filesystem paths cap out at PATH_MAX (4096 on
# Linux); matching that keeps the route honest without rejecting any
# legitimate filesystem path.
_MAX_PATH_CHARS = 4096

# Token substituted into argv elements. A single literal token rather
# than e.g. `str.format(path=...)` so a path containing curly braces
# can't trigger a KeyError or cross-contaminate adjacent args.
_PATH_PLACEHOLDER = "{path}"


class ShellOpenRequest(BaseModel):
    """Body for `POST /shell/open`. `kind` picks which configured
    command to dispatch to; `path` is the filesystem path (file or
    directory) handed to that command."""

    kind: ShellKind
    path: str = Field(min_length=1, max_length=_MAX_PATH_CHARS)


def _build_argv(template: list[str], path: str) -> list[str]:
    """Substitute `{path}` into each template arg, or append `path` as
    the trailing arg when no placeholder appears. Pure — separated out
    for unit tests and to keep the route handler a straight line."""
    if any(_PATH_PLACEHOLDER in arg for arg in template):
        return [arg.replace(_PATH_PLACEHOLDER, path) for arg in template]
    return [*template, path]


def _resolve_command(cfg: ShellCfg, kind: ShellKind) -> list[str]:
    """Return the configured argv for `kind`, or raise 400 if unset.

    The 400 body names the exact config key the user needs to set so
    the frontend tooltip can be actionable ("Configure
    `shell.editor_command` in config.toml") rather than a bare
    "not configured" string."""
    field = _KIND_TO_FIELD[kind]
    argv: list[str] | None = getattr(cfg, field)
    if not argv:
        raise HTTPException(
            status_code=400,
            detail=f"shell.{field} is not configured",
        )
    return list(argv)


@router.post("/open", status_code=204)
async def open_shell(body: ShellOpenRequest, request: Request) -> Response:
    """Dispatch to the configured host command for `body.kind`.

    Returns 204 once the subprocess is spawned; we do not wait on the
    spawned GUI app to finish (that could take seconds and the user's
    terminal / editor outliving the request is the whole point).
    Returns 400 when the requested kind has no command configured, so
    the frontend can surface a "Configure in settings" tooltip."""
    cfg: ShellCfg = request.app.state.settings.shell
    template = _resolve_command(cfg, body.kind)
    argv = _build_argv(template, body.path)
    try:
        subprocess.Popen(  # noqa: S603 — argv-list form, no shell=True
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        # The configured binary doesn't exist on PATH. Surface as 400
        # so the frontend treats it the same as "not configured" — a
        # misconfiguration the user needs to fix in config.toml.
        raise HTTPException(
            status_code=400,
            detail=f"command not found: {argv[0]!r}",
        ) from exc
    except OSError as exc:
        # Any other spawn failure (permission denied, ENOEXEC on a
        # non-executable, etc.) is the server's problem to surface,
        # not something the user can fix via retry.
        raise HTTPException(
            status_code=500,
            detail=f"failed to spawn {argv[0]!r}: {exc}",
        ) from exc
    return Response(status_code=204)
