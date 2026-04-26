"""`bearings here init` — run onboarding and persist the `.bearings/`
files on confirmation.

v0.6.0 CLI-only: this module assembles the brief and writes the
three TOML files (`manifest.toml`, `state.toml`, `pending.toml`) on
the caller's OK. The WS-open auto-onboarding in v0.6.2 reuses the
same writers, driven by chat-prose confirmation instead of a TTY
prompt.

v0.6.3 polish — read-only graceful degrade: `init_directory_safe`
catches the read-only-FS variants of OSError (EROFS / EACCES / EPERM
/ ENOSPC) so the MCP `dir_init` tool can return success-with-warning
and the agent still has a usable brief for this session, even when
persistence isn't possible.
"""

from __future__ import annotations

import errno
import logging
from dataclasses import dataclass
from pathlib import Path

from bearings.bearings_dir.io import (
    MANIFEST_FILE,
    STATE_FILE,
    bearings_path,
    ensure_bearings_dir,
    write_toml_model,
)
from bearings.bearings_dir.onboard import Brief, run_onboarding
from bearings.bearings_dir.schema import (
    EnvironmentBlock,
    Manifest,
    Pending,
    State,
)

log = logging.getLogger(__name__)

# OSError errnos that map to "the filesystem won't accept a write,
# but the directory is otherwise readable" — i.e. graceful-degrade
# territory. Other errnos (ENOENT, EISDIR, EFAULT, etc.) signal a
# real bug and bubble up.
_READ_ONLY_ERRNOS = frozenset({errno.EROFS, errno.EACCES, errno.EPERM, errno.ENOSPC})


@dataclass(frozen=True)
class InitOutcome:
    """Result of `init_directory_safe`. `root` is `None` when the
    write was skipped because the FS rejected it; `warning` carries
    the human-readable reason in that case so the MCP tool can echo
    it back to the agent."""

    brief: Brief
    root: Path | None
    warning: str | None


def _manifest_from_brief(brief: Brief) -> Manifest:
    """Turn a `Brief` into the `manifest.toml` identity record."""
    git = brief.git
    identity = brief.identity
    readme = identity.get("readme_head") or []
    description_lines = [ln for ln in readme if ln.strip()][:3]
    description = " ".join(description_lines)[:500]

    language: str | None = None
    pins = brief.environment.get("version_pins", {}) or {}
    if ".python-version" in pins:
        language = f"python {pins['.python-version']}"
    elif ".nvmrc" in pins:
        language = f"node {pins['.nvmrc']}"
    elif "rust-toolchain.toml" in pins or "rust-toolchain" in pins:
        language = "rust"

    # Pull the remote from the git step's side channel; the step
    # itself doesn't surface it (it asks only about state), so we
    # refetch. Cheap — already cached in git's config file.
    from bearings.bearings_dir.onboard import git_remote

    remote = git_remote(brief.directory) if git.get("is_repo") else None

    return Manifest(
        name=brief.directory.name,
        path=str(brief.directory),
        description=description,
        git_remote=remote,
        language=language,
    )


def _state_from_brief(brief: Brief) -> State:
    """Initial `state.toml` after onboarding. Mirrors what
    `bearings check` would write, minus the narrative re-scan
    (onboarding's step 5 already captured that at a richer fidelity).
    """
    env = brief.environment
    notes = list(env.get("notes", []))
    unfinished = brief.unfinished or {}
    for finding in unfinished.get("naming_findings", []):
        notes.append(
            f"naming note: '{finding['variant']}' in {finding['file']} "
            f"(canonical '{finding['canonical']}')"
        )
    return State(
        branch=brief.git.get("branch"),
        dirty=brief.git.get("dirty"),
        environment=EnvironmentBlock(
            venv_path=env.get("venv_path"),
            lockfile_fresh=env.get("lockfile_fresh"),
            notes=notes[:16],
        ),
    )


def write_bearings(directory: Path, brief: Brief) -> Path:
    """Persist manifest/state/pending for `directory`. Returns the
    `.bearings/` path. Pending starts empty; the user adds entries
    via `bearings pending add` as in-flight work is noticed.
    """
    ensure_bearings_dir(directory)
    bearings_root = bearings_path(directory)

    write_toml_model(bearings_root / MANIFEST_FILE, _manifest_from_brief(brief))
    write_toml_model(bearings_root / STATE_FILE, _state_from_brief(brief))
    # Pending starts empty — writing an empty file so the flock target
    # exists and concurrent access doesn't race on creation.
    from bearings.bearings_dir.io import PENDING_FILE

    write_toml_model(bearings_root / PENDING_FILE, Pending())

    return bearings_root


def init_directory(directory: Path) -> tuple[Brief, Path]:
    """End-to-end onboarding: run the ritual, write the files, return
    both the brief (for rendering) and the `.bearings/` path. Caller
    is responsible for any confirm step; this function commits.

    Raises `OSError` on a read-only filesystem. Callers that need to
    degrade gracefully should use `init_directory_safe` instead.
    """
    directory = directory.resolve()
    brief = run_onboarding(directory)
    root = write_bearings(directory, brief)
    return brief, root


def init_directory_safe(directory: Path) -> InitOutcome:
    """Like `init_directory`, but degrades gracefully when the target
    filesystem rejects the write (read-only mount, no-write-perm
    bind, exhausted quota).

    Behaviour:
      - happy path: identical to `init_directory`. Returns
        `InitOutcome(brief, root, warning=None)`.
      - read-only-style OSError (EROFS / EACCES / EPERM / ENOSPC):
        the brief is still returned (it's a pure read of the working
        dir), `root` is `None`, and `warning` carries a human-readable
        reason. The agent can quote the brief to the user and explain
        that persistence is unavailable on this mount; nothing else
        about the session is affected.
      - any other OSError: re-raised. EISDIR / EFAULT / similar are
        real bugs and shouldn't be papered over.

    The brief is always built before the write attempt so a write-
    blocked FS never starves the user of context.
    """
    directory = directory.resolve()
    brief = run_onboarding(directory)
    try:
        root = write_bearings(directory, brief)
    except OSError as exc:
        if exc.errno in _READ_ONLY_ERRNOS:
            warning = (
                f"persist skipped: {exc.strerror or exc} "
                f"(errno {exc.errno}). The brief is available in this "
                "session's prompt but `.bearings/` was not written, so "
                "future sessions in this directory will see the "
                "onboarding prompt again until the filesystem accepts "
                "writes."
            )
            log.info(
                "directory_context: init persist skipped for %s (%s)",
                directory,
                exc.strerror or exc,
            )
            return InitOutcome(brief=brief, root=None, warning=warning)
        raise
    return InitOutcome(brief=brief, root=root, warning=None)


__all__ = [
    "InitOutcome",
    "init_directory",
    "init_directory_safe",
    "write_bearings",
]
