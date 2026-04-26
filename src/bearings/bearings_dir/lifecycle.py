"""Session-lifecycle hooks for the Directory Context System (v0.6.1).

Two writes per runner-lifetime:
  - `record_session_start` appends an `in_progress` `HistoryEntry` to
    `<working_dir>/.bearings/history.jsonl` and returns a handle the
    caller stashes on the runner. Returns `None` when the directory
    hasn't been onboarded — there's no `.bearings/` to write into.
  - `record_session_end` consumes that handle and appends a closing
    entry: same `session_id`, `ended` set, `commits` enumerated from
    the start-snapshot HEAD, `status` `clean`/`unclean` based on the
    current tree.

Append-only by design (matches `io.append_history` semantics): a
crash between start and end leaves the start marker in place so the
next session sees the prior one ended unclean. The brief renderer
treats a start without a matching end as "likely crashed."

Stale-state revalidation (`maybe_revalidate`) is the third v0.6.1
piece. Reads `state.toml.environment.last_validated`; if it's older
than `_STALE_STATE_THRESHOLD`, runs `check.run_check` to refresh
state.toml. Fire-and-forget — the caller dispatches it via
`asyncio.create_task` so the user doesn't wait on `uv sync`.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bearings.bearings_dir.io import (
    HISTORY_FILE,
    MANIFEST_FILE,
    STATE_FILE,
    append_history,
    bearings_path,
    read_toml_model,
)
from bearings.bearings_dir.schema import HistoryEntry, State

log = logging.getLogger(__name__)

# State older than this triggers a `run_check()` revalidation at
# session start. The v0.4 spec calls for a 24h cheap-check threshold
# and a 7-day full-check threshold; v0.6.1 collapses both into a
# single 24h trigger for the existing `run_check` (which already runs
# steps 2/3/5). Splitting the two thresholds is v0.6.3 polish.
_STALE_STATE_THRESHOLD = timedelta(hours=24)

# Cap for `git rev-list <start>..HEAD` enumeration on session end.
# Matches `HistoryEntry._cap_commits` (64). Anything beyond that is
# truncated; the count is still available via the entry's `summary`.
_MAX_COMMITS_PER_END = 64

# Subprocess timeout for git lookups. Short — these are local repo
# operations on cached refs. Hitting the timeout is more often a sign
# of a hung git index lock than a slow disk; the lifecycle hook
# degrades to no-branch / no-commits rather than blocking.
_GIT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class SessionLifecycleHandle:
    """Snapshot captured at session start so the end hook can write a
    matching closing entry. Frozen so a stray mutation in the runner
    can't desync the start vs end records."""

    working_dir: Path
    session_id: str
    started: datetime
    branch: str | None
    head_sha: str | None


def _git_capture(args: list[str], cwd: Path) -> str | None:
    """Run `git <args>` in `cwd`, return stripped stdout on rc==0,
    `None` on any failure. Quiet on miss — the lifecycle path must
    not raise on a directory that lacks `.git`."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def _current_branch(directory: Path) -> str | None:
    return _git_capture(["rev-parse", "--abbrev-ref", "HEAD"], directory)


def _current_head(directory: Path) -> str | None:
    return _git_capture(["rev-parse", "HEAD"], directory)


def _is_dirty(directory: Path) -> bool | None:
    """True iff `git status --porcelain` has any output. `None` when
    the directory isn't a git repo (so the end hook can stamp
    `status="in_progress"` rather than guessing clean/unclean)."""
    out = _git_capture(["status", "--porcelain"], directory)
    if out is None:
        return None
    return bool(out)


def _commits_since(directory: Path, start_sha: str) -> list[str]:
    """SHAs reachable from HEAD but not from `start_sha`, oldest last
    (git's default rev-list ordering reversed via `--reverse` would be
    nicer for chronology, but commit shas are the data; ordering is
    cosmetic). Caps at `_MAX_COMMITS_PER_END`."""
    raw = _git_capture(
        ["rev-list", f"{start_sha}..HEAD", f"--max-count={_MAX_COMMITS_PER_END}"],
        directory,
    )
    if raw is None:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def record_session_start(working_dir: Path | str, session_id: str) -> SessionLifecycleHandle | None:
    """Append an `in_progress` start marker. No-op (returns `None`)
    when the directory hasn't been onboarded.

    Failure to write the JSONL line is logged and swallowed — the
    history is advisory and a torn write must not break runner
    construction. The handle is still returned so the end hook can
    attempt its own write; if that one also fails, the on-disk record
    just lacks this session, which is the same as a pre-onboarding
    directory (i.e. graceful degrade)."""
    directory = Path(working_dir)
    root = bearings_path(directory)
    if not (root / MANIFEST_FILE).exists():
        return None

    started = datetime.now(UTC)
    branch = _current_branch(directory)
    head_sha = _current_head(directory)

    entry = HistoryEntry(
        session_id=session_id,
        started=started,
        ended=None,
        branch=branch,
        commits=[],
        summary="",
        status="in_progress",
    )
    try:
        append_history(root / HISTORY_FILE, entry)
    except OSError as exc:
        log.warning(
            "directory_context: failed to append start marker for %s: %s",
            session_id,
            exc,
        )

    return SessionLifecycleHandle(
        working_dir=directory,
        session_id=session_id,
        started=started,
        branch=branch,
        head_sha=head_sha,
    )


def record_session_end(handle: SessionLifecycleHandle | None) -> None:
    """Append a closing entry derived from `handle`. No-op when the
    handle is `None` (start hook also no-op'd, or runner shut down
    before start ran)."""
    if handle is None:
        return
    directory = handle.working_dir
    root = bearings_path(directory)
    if not root.exists():
        # The directory may have been removed under us between start
        # and end (test cleanup, manual rm). Nothing we can do; the
        # start marker is also gone, so the next session won't see a
        # phantom in-progress.
        return

    end_branch = _current_branch(directory) or handle.branch
    dirty = _is_dirty(directory)
    if dirty is True:
        status: str = "unclean"
    elif dirty is False:
        status = "clean"
    else:
        status = "in_progress"

    commits: list[str] = []
    if handle.head_sha:
        commits = _commits_since(directory, handle.head_sha)

    entry = HistoryEntry(
        session_id=handle.session_id,
        started=handle.started,
        ended=datetime.now(UTC),
        branch=end_branch,
        commits=commits,
        summary="",
        status=status,  # type: ignore[arg-type]
    )
    try:
        append_history(root / HISTORY_FILE, entry)
    except OSError as exc:
        log.warning(
            "directory_context: failed to append end marker for %s: %s",
            handle.session_id,
            exc,
        )


def needs_revalidation(working_dir: Path | str) -> bool:
    """True iff `.bearings/state.toml` exists and its
    `environment.last_validated` is older than `_STALE_STATE_THRESHOLD`.

    False on missing/corrupt state — the caller's policy is "if state
    is missing, onboarding will write a fresh one." Stale-state
    revalidation is for the long-running already-onboarded case, not
    the never-onboarded case."""
    directory = Path(working_dir)
    state_path = bearings_path(directory) / STATE_FILE
    state = read_toml_model(state_path, State)
    if state is None:
        return False
    last = state.environment.last_validated
    return (datetime.now(UTC) - last) >= _STALE_STATE_THRESHOLD


def maybe_run_on_open(working_dir: Path | str) -> bool:
    """Run `.bearings/checks/on_open.sh` if installed, persist result.

    Wrapper kept here (not imported directly from `on_open`) so the
    runner's `note_directory_context_start` only depends on the
    `lifecycle` module — single import surface for all session-start
    bearings work. Synchronous; the caller dispatches via
    `asyncio.to_thread` so the 10s subprocess budget never blocks the
    event loop.

    Returns True iff the script ran AND persistence succeeded. False
    on no-script, persist-failed (read-only FS), or any internal
    fault. Failure is advisory — the brief still works without
    `last_on_open.json` present."""
    directory = Path(working_dir)
    if not (bearings_path(directory) / MANIFEST_FILE).exists():
        # Same gate as `record_session_start`: no manifest → no
        # `.bearings/` to write the sidecar into. Skip silently.
        return False
    # Local import — `on_open` pulls subprocess machinery; keep it out
    # of the lifecycle hot path for sessions whose directory has no
    # `checks/on_open.sh`.
    from bearings.bearings_dir import on_open

    try:
        result = on_open.maybe_run_on_open(directory)
    except OSError as exc:
        log.warning(
            "directory_context: on_open run failed for %s: %s",
            directory,
            exc,
        )
        return False
    return result is not None


def maybe_revalidate(working_dir: Path | str) -> bool:
    """If state is stale, re-run `check.run_check` and return True.
    Returns False on no-op (state fresh, missing manifest, or
    revalidation raised). Synchronous — callers in async code should
    dispatch via `asyncio.to_thread` so the subprocess calls inside
    `run_check` don't block the event loop.

    Failure modes (manifest missing, subprocess crash, write error)
    are logged and swallowed: the brief still renders from whatever
    `state.toml` is on disk, and the next session will try again."""
    directory = Path(working_dir)
    if not (bearings_path(directory) / MANIFEST_FILE).exists():
        return False
    if not needs_revalidation(directory):
        return False
    # Local import — `check` imports from `onboard` which runs git
    # subprocesses; keeping the import lazy avoids a fan-out for
    # callers that never trip the stale path.
    from bearings.bearings_dir import check

    try:
        check.run_check(directory)
    except (OSError, FileNotFoundError) as exc:
        log.warning(
            "directory_context: revalidation failed for %s: %s",
            directory,
            exc,
        )
        return False
    # `run_check` persists a fresh `State` with `last_validated=now()`
    # before returning — nothing further to do here.
    return True


__all__ = [
    "SessionLifecycleHandle",
    "maybe_revalidate",
    "maybe_run_on_open",
    "needs_revalidation",
    "record_session_end",
    "record_session_start",
]
