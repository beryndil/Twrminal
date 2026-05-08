# mypy: disable-error-code=explicit-any
"""7-step onboarding ritual, brief composition, and dir_init tool body (arch §1.1.6).

The onboarding ritual probes the project directory and produces a concise
brief that is injected into the agent's system-prompt layer for every
session opened in that directory.  The brief format matches the
``directory_onboarding`` system-prompt layer the Bearings server injects.

7 steps
-------
1. Find primary marker (``.git``, ``pyproject.toml``, etc.)
2. Inspect git status (branch, dirty/clean, changed-file count, stash count)
3. Detect environment (lockfile freshness)
4. Count unfinished markers (``TODO`` / ``FIXME`` / ``XXX`` / ``WIP``)
5. Count pending operations from ``.bearings/pending.toml`` (if present)
6. Count recent sessions from ``.bearings/history.jsonl`` (if present)
7. Compose the brief string

:func:`dir_init_body` runs all seven steps and writes the three
``.bearings/`` files (``manifest.toml``, ``state.toml``, ``pending.toml``).
It is the backing implementation for the ``mcp__bearings__dir_init`` tool;
``agent/bearings_mcp.py`` (finding-003) wires it into the MCP server.

Pydantic carve-out
------------------
``# mypy: disable-error-code=explicit-any`` covers the
``dict[str, Any]`` surface coming from :mod:`bearings.bearings_dir.io`
(``bdir_io.read_jsonl`` returns ``list[dict[str, Any]]``).

Layer isolation
---------------
No imports from ``bearings.agent.*``, ``bearings.web.*``, or
``bearings.cli.*`` per arch §3 line 549.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bearings.bearings_dir import io as bdir_io
from bearings.bearings_dir.contract import ManifestModel, StateModel
from bearings.config.constants import (
    BEARINGS_DIR_HISTORY_FILENAME,
    BEARINGS_DIR_MANIFEST_FILENAME,
    BEARINGS_DIR_PENDING_FILENAME,
    BEARINGS_DIR_SCHEMA_VERSION,
    BEARINGS_DIR_STATE_FILENAME,
    BEARINGS_DIR_SUBDIR,
)

_log = logging.getLogger(__name__)

# Ordered list of file/directory names that indicate the project type.
# First match wins; the name appears verbatim in the brief's
# "Primary marker" line.
_PRIMARY_MARKERS: tuple[str, ...] = (
    ".git",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
)

# Lockfile → companion deps-file pairs for freshness detection.
# A lockfile is "fresh" when its mtime >= the deps file's mtime.
_LOCKFILE_PAIRS: tuple[tuple[str, str], ...] = (
    ("uv.lock", "pyproject.toml"),
    ("poetry.lock", "pyproject.toml"),
    ("Pipfile.lock", "Pipfile"),
    ("package-lock.json", "package.json"),
    ("yarn.lock", "package.json"),
    ("pnpm-lock.yaml", "package.json"),
    ("Cargo.lock", "Cargo.toml"),
    ("go.sum", "go.mod"),
)

# Subprocess timeout (seconds) for git commands.
_GIT_TIMEOUT_S: int = 5

# Subprocess timeout (seconds) for the grep marker count.
_GREP_TIMEOUT_S: int = 30


# ---------------------------------------------------------------------------
# Step 1 — Primary marker
# ---------------------------------------------------------------------------


def _find_primary_marker(directory: Path) -> str:
    """Return the first recognised project-type marker found in *directory*."""
    for name in _PRIMARY_MARKERS:
        if (directory / name).exists():
            return name
    return "(none found)"


# ---------------------------------------------------------------------------
# Step 2 — Git status
# ---------------------------------------------------------------------------


def _git_status(directory: Path) -> str:
    """Return a one-line git status summary for *directory*.

    Format: ``"dirty, branch <name>, <N> changed, <S> stashes"`` or
    ``"clean, branch <name>, 0 changed, 0 stashes"``.
    Returns ``"not a git repo"`` when git is unavailable or *directory*
    is outside any git tree.
    """
    try:
        branch_proc = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
        if branch_proc.returncode != 0:
            return "not a git repo"
        branch = branch_proc.stdout.strip() or "HEAD"

        status_proc = subprocess.run(
            ["git", "-C", str(directory), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
        changed = len([line for line in status_proc.stdout.splitlines() if line.strip()])
        state = "dirty" if changed > 0 else "clean"

        stash_proc = subprocess.run(
            ["git", "-C", str(directory), "stash", "list"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
        stashes = len([line for line in stash_proc.stdout.splitlines() if line.strip()])

        return f"{state}, branch {branch}, {changed} changed, {stashes} stashes"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "not a git repo"


# ---------------------------------------------------------------------------
# Step 3 — Environment (lockfile freshness)
# ---------------------------------------------------------------------------


def _env_status(directory: Path) -> str:
    """Return a one-line lockfile-freshness summary for *directory*."""
    for lockfile_name, deps_name in _LOCKFILE_PAIRS:
        lockfile = directory / lockfile_name
        deps = directory / deps_name
        if lockfile.exists() and deps.exists():
            if lockfile.stat().st_mtime >= deps.stat().st_mtime:
                return "lockfile fresh."
            return "lockfile stale."
        if lockfile.exists():
            return "lockfile found (no matching deps file)."
    return "no lockfile detected."


# ---------------------------------------------------------------------------
# Step 4 — Unfinished markers
# ---------------------------------------------------------------------------


def _count_markers(directory: Path) -> int:
    """Count lines matching TODO/FIXME/XXX/WIP across common source files."""
    try:
        result = subprocess.run(
            [
                "grep",
                "-r",
                "-E",
                "--binary-files=without-match",
                "TODO|FIXME|XXX|WIP",
                str(directory),
                "--include=*.py",
                "--include=*.ts",
                "--include=*.js",
                "--include=*.svelte",
                "--include=*.md",
                "--include=*.toml",
                "--exclude-dir=.git",
                "--exclude-dir=node_modules",
                "--exclude-dir=.venv",
                "--exclude-dir=__pycache__",
            ],
            capture_output=True,
            text=True,
            timeout=_GREP_TIMEOUT_S,
        )
        return len(result.stdout.splitlines())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


# ---------------------------------------------------------------------------
# Step 5 — Pending operations
# ---------------------------------------------------------------------------


def _count_pending_ops(directory: Path) -> int:
    """Return the number of pending ops in ``.bearings/pending.toml``."""
    pending_path = directory / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_PENDING_FILENAME
    if not pending_path.exists():
        return 0
    try:
        data = bdir_io.read_toml(pending_path)
        ops: Any = data.get("ops", {})
        if isinstance(ops, dict):
            return len(ops)
    except Exception:
        _log.debug("Failed to read pending.toml in %s", directory)
    return 0


# ---------------------------------------------------------------------------
# Step 6 — Recent sessions
# ---------------------------------------------------------------------------


def _count_recent_sessions(directory: Path) -> int:
    """Return the number of entries in ``.bearings/history.jsonl``."""
    history_path = directory / BEARINGS_DIR_SUBDIR / BEARINGS_DIR_HISTORY_FILENAME
    return len(bdir_io.read_jsonl(history_path))


# ---------------------------------------------------------------------------
# Step 7 — Compose brief
# ---------------------------------------------------------------------------


def _compose_brief(
    directory: Path,
    primary_marker: str,
    git_stat: str,
    env_stat: str,
    marker_count: int,
    pending_count: int,
    session_count: int,
) -> str:
    """Assemble the brief text from the seven-step results."""
    lines = [
        f"Directory: {directory}",
        f"Primary marker: {primary_marker}",
        f"Git: {git_stat}",
        f"Environment: {env_stat}",
        f"Unfinished markers: {marker_count} TODO/FIXME/XXX/WIP hits",
    ]
    if pending_count > 0:
        lines.append(f"Pending operations: {pending_count}")
    if session_count > 0:
        lines.append(f"Recent sessions: {session_count}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def run_onboarding_ritual(directory: Path) -> str:
    """Run all 7 steps and return the brief string.

    This is a **pure probe** — it does not write any files.  Call
    :func:`dir_init_body` to persist the results to ``.bearings/``.
    """
    marker = _find_primary_marker(directory)
    git_stat = _git_status(directory)
    env_stat = _env_status(directory)
    marker_count = _count_markers(directory)
    pending_count = _count_pending_ops(directory)
    session_count = _count_recent_sessions(directory)
    return _compose_brief(
        directory,
        marker,
        git_stat,
        env_stat,
        marker_count,
        pending_count,
        session_count,
    )


def dir_init_body(directory: Path) -> None:
    """Write (or overwrite) ``.bearings/{manifest,state,pending}.toml``.

    This is the body of the ``mcp__bearings__dir_init`` tool.  The function
    is **idempotent** — re-running it refreshes the brief and resets state
    cleanly.  The brief in ``manifest.toml`` is regenerated on every call.

    Writes:

    * ``manifest.toml`` — directory metadata + onboarding brief.
    * ``state.toml`` — fresh state (no session id, no timestamp).
    * ``pending.toml`` — empty ops table.

    Raises :exc:`OSError` when the ``.bearings/`` directory cannot be
    created or any file cannot be written.
    """
    now = datetime.now(UTC)
    primary_marker = _find_primary_marker(directory)
    brief = run_onboarding_ritual(directory)

    bearings_subdir = directory / BEARINGS_DIR_SUBDIR
    bearings_subdir.mkdir(parents=True, exist_ok=True)

    # manifest.toml
    manifest = ManifestModel(
        schema_version=BEARINGS_DIR_SCHEMA_VERSION,
        directory=str(directory),
        primary_marker=primary_marker,
        created_at=now,
        brief=brief,
    )
    bdir_io.write_toml(
        bearings_subdir / BEARINGS_DIR_MANIFEST_FILENAME,
        manifest.model_dump(),
    )

    # state.toml — fresh; no session recorded yet
    state = StateModel(schema_version=BEARINGS_DIR_SCHEMA_VERSION)
    bdir_io.write_toml(
        bearings_subdir / BEARINGS_DIR_STATE_FILENAME,
        state.model_dump(exclude_none=True),
    )

    # pending.toml — empty ops table
    bdir_io.write_toml(
        bearings_subdir / BEARINGS_DIR_PENDING_FILENAME,
        {},
    )


__all__ = [
    "dir_init_body",
    "run_onboarding_ritual",
]
